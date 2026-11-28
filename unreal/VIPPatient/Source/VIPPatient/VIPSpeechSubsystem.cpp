#include "VIPSpeechSubsystem.h"

#include "VIPPatients.h"
#include "VIPSpeechSource.h"

#include "Animation/AnimInstance.h"
#include "Audio.h"
#include "Components/AudioComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "EngineUtils.h"
#include "Features/IModularFeatures.h"
#include "ILiveLinkClient.h"
#include "LiveLinkTypes.h"
#include "Roles/LiveLinkBasicRole.h"
#include "Kismet/GameplayStatics.h"
#include "MetaHumanAudioBaseLiveLinkSubjectSettings.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Sound/SoundWaveProcedural.h"

DEFINE_LOG_CATEGORY_STATIC(LogVIP, Log, All);

namespace
{
	// Must match the subject build_scene.py assigns to the patient
	const TCHAR* SubjectName = TEXT("VIPSpeech");

	// ElevenLabs' default PCM rate; speech at other rates is converted
	constexpr int32 VoiceSampleRate = 24000;

	// Solver look-ahead plus processing
	constexpr double SoundDelaySeconds = 0.12;

	bool LoadWav(const FString& Path, TArray<int16>& OutSamples, int32& OutRate)
	{
		TArray<uint8> Bytes;
		FWaveModInfo Wave;
		FString Error;
		if (!FFileHelper::LoadFileToArray(Bytes, *Path) || !Wave.ReadWaveInfo(Bytes.GetData(), Bytes.Num(), &Error)
			|| *Wave.pBitsPerSample != 16)
		{
			UE_LOG(LogVIP, Error, TEXT("Cannot read 16-bit WAV '%s' %s"), *Path, *Error);
			return false;
		}

		const int32 Channels = *Wave.pChannels;
		const int16* Data = reinterpret_cast<const int16*>(Wave.SampleDataStart);
		const int32 Frames = Wave.SampleDataSize / (sizeof(int16) * Channels);
		OutRate = *Wave.pSamplesPerSec;
		OutSamples.SetNumUninitialized(Frames);
		for (int32 Frame = 0; Frame < Frames; ++Frame)
		{
			OutSamples[Frame] = Data[Frame * Channels];
		}
		return Frames > 0;
	}

	EAudioDrivenAnimationMood ToMood(const FString& Emotion)
	{
		static const TMap<FString, EAudioDrivenAnimationMood> Moods = {
			{TEXT("neutral"), EAudioDrivenAnimationMood::Neutral},
			{TEXT("happy"), EAudioDrivenAnimationMood::Happiness},
			{TEXT("sad"), EAudioDrivenAnimationMood::Sadness},
			{TEXT("fear"), EAudioDrivenAnimationMood::Fear},
			{TEXT("disgust"), EAudioDrivenAnimationMood::Disgust},
			{TEXT("anger"), EAudioDrivenAnimationMood::Anger},
			{TEXT("surprise"), EAudioDrivenAnimationMood::Surprise},
			{TEXT("boredom"), EAudioDrivenAnimationMood::Boredom},
			{TEXT("confidence"), EAudioDrivenAnimationMood::Confidence},
			{TEXT("confusion"), EAudioDrivenAnimationMood::Confusion},
			{TEXT("excitement"), EAudioDrivenAnimationMood::Excitement},
			{TEXT("playfulness"), EAudioDrivenAnimationMood::Playfulness},
		};
		const EAudioDrivenAnimationMood* Mood = Moods.Find(Emotion.ToLower());
		return Mood ? *Mood : EAudioDrivenAnimationMood::Neutral;
	}
}

bool UVIPSpeechSubsystem::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

TStatId UVIPSpeechSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVIPSpeechSubsystem, STATGROUP_Tickables);
}

void UVIPSpeechSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);

	FString Wav;
	if (FParse::Value(FCommandLine::Get(), TEXT("VIPWav="), Wav) && LoadWav(Wav, TestSpeech, TestRate))
	{
		NextTestAt = FPlatformTime::Seconds() + 5;
		bLogFace = true;
	}

	StartSource(VoiceSampleRate);

	// Which patient: from the case later (#24); for now from the command line
	FString Gender;
	int32 Age = -1;
	FParse::Value(FCommandLine::Get(), TEXT("VIPGender="), Gender);
	FParse::Value(FCommandLine::Get(), TEXT("VIPAge="), Age);
	VIPPatients::Choose(InWorld, Gender, Age);

	DriveFace();

	FString Emotion = TEXT("neutral");
	FParse::Value(FCommandLine::Get(), TEXT("VIPMood="), Emotion);
	SetEmotion(Emotion, 1.0f);
}

void UVIPSpeechSubsystem::DriveFace()
{
	// The MetaHuman blueprint only switches the face to Live Link in the editor, so do it here
	UClass* LiveLinkAnim = LoadClass<UAnimInstance>(nullptr, TEXT("/Game/MetaHumans/Common/Animation/ABP_MH_LiveLink.ABP_MH_LiveLink_C"));
	if (!LiveLinkAnim)
	{
		UE_LOG(LogVIP, Error, TEXT("ABP_MH_LiveLink not found"));
		return;
	}

	for (TActorIterator<AActor> It(GetWorld()); It; ++It)
	{
		TInlineComponentArray<USkeletalMeshComponent*> Meshes(*It);
		for (USkeletalMeshComponent* Mesh : Meshes)
		{
			if (Mesh->GetName() != TEXT("Face"))
			{
				continue;
			}
			Mesh->SetAnimInstanceClass(LiveLinkAnim);
			UAnimInstance* Anim = Mesh->GetAnimInstance();
			FStructProperty* Subject = Anim ? FindFProperty<FStructProperty>(Anim->GetClass(), TEXT("LLink_Face_Subj")) : nullptr;
			if (!Subject || Subject->Struct != FLiveLinkSubjectName::StaticStruct())
			{
				UE_LOG(LogVIP, Error, TEXT("Face anim has no LLink_Face_Subj"));
				return;
			}
			*Subject->ContainerPtrToValuePtr<FLiveLinkSubjectName>(Anim) = FLiveLinkSubjectName(SubjectName);
			UE_LOG(LogVIP, Display, TEXT("Face of %s follows %s"), *It->GetName(), SubjectName);
			return;
		}
	}
	UE_LOG(LogVIP, Error, TEXT("No face mesh in the level"));
}

void UVIPSpeechSubsystem::StartSource(int32 SampleRate)
{
	IModularFeatures& Features = IModularFeatures::Get();
	if (!Features.IsModularFeatureAvailable(ILiveLinkClient::ModularFeatureName))
	{
		UE_LOG(LogVIP, Error, TEXT("Live Link is not available"));
		return;
	}

	Queue = MakeShared<FVIPSpeechQueue>(SampleRate);
	TSharedPtr<FVIPSpeechSource> SpeechSource = MakeShared<FVIPSpeechSource>(Queue.ToSharedRef());
	Features.GetModularFeature<ILiveLinkClient>(ILiveLinkClient::ModularFeatureName).AddSource(SpeechSource);
	Source = SpeechSource;

	Settings = SpeechSource->CreateSubjectSettings<UMetaHumanAudioBaseLiveLinkSubjectSettings>();
	const FLiveLinkSubjectKey Key = SpeechSource->RequestSubjectCreation(SubjectName, Settings);
	if (!Key.Source.IsValid())
	{
		UE_LOG(LogVIP, Error, TEXT("Could not create the speech subject"));
		Settings = nullptr;
		return;
	}
	UE_LOG(LogVIP, Display, TEXT("Speech subject ready at %d Hz"), SampleRate);

	Voice = NewObject<USoundWaveProcedural>(this);
	Voice->SetSampleRate(SampleRate);
	Voice->NumChannels = 1;
	Voice->Duration = INDEFINITELY_LOOPING_DURATION;
	Voice->SoundGroup = SOUNDGROUP_Voice;
	Voice->bLooping = false;
	VoicePlayer = UGameplayStatics::SpawnSound2D(GetWorld(), Voice, 1.0f, 1.0f, 0.0f, nullptr, true, false);
}

void UVIPSpeechSubsystem::Speak(const TArray<int16>& Samples, int32 SampleRate)
{
	if (!Settings || !Queue || SampleRate <= 0 || Samples.IsEmpty())
	{
		UE_LOG(LogVIP, Error, TEXT("Cannot speak: no speech subject or no audio"));
		return;
	}

	// The face and the sound both run at the rate chosen at start; convert anything else
	TArray<int16> Converted;
	const TArray<int16>& Audio = SampleRate == Queue->SampleRate ? Samples : Converted;
	if (SampleRate != Queue->SampleRate)
	{
		const double Step = static_cast<double>(SampleRate) / Queue->SampleRate;
		const int32 Count = static_cast<int32>(Samples.Num() / Step);
		Converted.SetNumUninitialized(Count);
		for (int32 Index = 0; Index < Count; ++Index)
		{
			const double Position = Index * Step;
			const int32 Left = FMath::Min(static_cast<int32>(Position), Samples.Num() - 1);
			const int32 Right = FMath::Min(Left + 1, Samples.Num() - 1);
			Converted[Index] = static_cast<int16>(FMath::Lerp<double>(Samples[Left], Samples[Right], Position - Left));
		}
	}

	TArray<float> Floats;
	Floats.Reserve(Audio.Num());
	for (const int16 Sample : Audio)
	{
		Floats.Add(Sample / 32768.0f);
	}
	Queue->Add(Floats);

	const double Now = FPlatformTime::Seconds();
	if (DelayedSound.IsEmpty())
	{
		PlaySoundAt = Now + SoundDelaySeconds;
	}
	DelayedSound.Append(Audio);
	SpeakingUntil = FMath::Max(SpeakingUntil, PlaySoundAt) + static_cast<double>(Audio.Num()) / Queue->SampleRate;
	UE_LOG(LogVIP, Display, TEXT("Speaking %.1f s"), static_cast<float>(Audio.Num()) / Queue->SampleRate);
}

void UVIPSpeechSubsystem::SetEmotion(const FString& Emotion, float Intensity)
{
	if (!Settings)
	{
		return;
	}

	if (Settings->Subject)
	{
		Settings->SetMood(ToMood(Emotion));
		Settings->SetMoodIntensity(Intensity);
	}
	else
	{
		// Live Link creates the subject a frame later and reads these then; the setters would crash now
		Settings->Mood = ToMood(Emotion);
		Settings->MoodIntensity = FMath::Clamp(Intensity, 0.0f, 1.0f);
	}
}

void UVIPSpeechSubsystem::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);

	const double Now = FPlatformTime::Seconds();
	if (Voice && DelayedSound.Num() > 0 && Now >= PlaySoundAt)
	{
		Voice->QueueAudio(reinterpret_cast<const uint8*>(DelayedSound.GetData()), DelayedSound.Num() * sizeof(int16));
		DelayedSound.Reset();
	}

	if (NextTestAt > 0 && Now >= NextTestAt)
	{
		Speak(TestSpeech, TestRate);
		NextTestAt = SpeakingUntil + 3;
	}

	if (bLogFace)
	{
		LogFace(DeltaTime);
	}
}

void UVIPSpeechSubsystem::LogFace(float DeltaTime)
{
	// Once a second: a few of the values the face receives, as evidence in the log without a screen
	LogTimer += DeltaTime;
	if (LogTimer < 1.0f)
	{
		return;
	}
	LogTimer = 0;

	IModularFeatures& Features = IModularFeatures::Get();
	if (!Features.IsModularFeatureAvailable(ILiveLinkClient::ModularFeatureName))
	{
		return;
	}
	FLiveLinkSubjectFrameData Frame;
	ILiveLinkClient& Client = Features.GetModularFeature<ILiveLinkClient>(ILiveLinkClient::ModularFeatureName);
	if (!Client.EvaluateFrame_AnyThread(FLiveLinkSubjectName(SubjectName), ULiveLinkBasicRole::StaticClass(), Frame))
	{
		UE_LOG(LogVIP, Display, TEXT("face: no frames yet"));
		return;
	}
	const FLiveLinkBaseStaticData* Static = Frame.StaticData.Cast<FLiveLinkBaseStaticData>();
	const FLiveLinkBaseFrameData* Data = Frame.FrameData.Cast<FLiveLinkBaseFrameData>();
	if (!Static || !Data)
	{
		return;
	}

	auto Value = [&](const TCHAR* Name)
	{
		const int32 Index = Static->PropertyNames.IndexOfByKey(FName(Name));
		return Data->PropertyValues.IsValidIndex(Index) ? Data->PropertyValues[Index] : -1.0f;
	};
	UE_LOG(LogVIP, Display, TEXT("face %s: jaw=%.2f blink=%.2f headSwitch=%.0f yaw=%.1f pitch=%.1f"),
		FPlatformTime::Seconds() < SpeakingUntil ? TEXT("speaking") : TEXT("silent"),
		Value(TEXT("CTRL_expressions_jawOpen")), Value(TEXT("CTRL_expressions_eyeBlinkL")),
		Value(TEXT("HeadControlSwitch")), Value(TEXT("HeadYaw")), Value(TEXT("HeadPitch")));
}

void UVIPSpeechSubsystem::Deinitialize()
{
	IModularFeatures& Features = IModularFeatures::Get();
	if (Source && Features.IsModularFeatureAvailable(ILiveLinkClient::ModularFeatureName))
	{
		Features.GetModularFeature<ILiveLinkClient>(ILiveLinkClient::ModularFeatureName).RemoveSource(Source);
	}
	Source.Reset();
	Settings = nullptr;

	Super::Deinitialize();
}
