#include "VIPSpeechSubsystem.h"

#include "VIPExpressions.h"
#include "VIPLife.h"
#include "VIPPatients.h"
#include "VIPSpeechSource.h"

#include "Animation/AnimInstance.h"
#include "Animation/AnimSequence.h"
#include "Audio.h"
#include "Components/AudioComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "EngineUtils.h"
#include "Features/IModularFeatures.h"
#include "ILiveLinkClient.h"
#include "LiveLinkTypes.h"
#include "Roles/LiveLinkBasicRole.h"
#include "Camera/CameraActor.h"
#include "Kismet/GameplayStatics.h"
#include "MetaHumanAudioBaseLiveLinkSubjectSettings.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Sound/SoundWaveProcedural.h"
#include "UnrealClient.h"

DEFINE_LOG_CATEGORY_STATIC(LogVIP, Log, All);

namespace
{
	// Must match the subject build_scene.py assigns to the patient
	const TCHAR* SubjectName = TEXT("VIPSpeech");

	// ElevenLabs' default PCM rate; speech at other rates is converted
	constexpr int32 VoiceSampleRate = 24000;

	// Solver look-ahead plus processing
	constexpr double SoundDelaySeconds = 0.12;

	// Emotion blending. Time constants: about 63 % of the way after this many seconds.
	constexpr float CrossfadeSeconds = 0.4f;   // from one emotion to the next
	constexpr float RiseSeconds = 0.3f;        // strength going up
	constexpr float FallSeconds = 1.5f;        // strength easing down to rest
	constexpr double HoldSeconds = 4.0;        // full strength after the mood is set or speech ends
	constexpr float RestFraction = 0.5f;       // resting strength between turns
	constexpr float MaxIntensity = 2.0f;
	constexpr float SolverRampPerSecond = 2.5f; // the solver has one mood: fade it out, switch, fade in
	constexpr float RestInSeconds = 0.5f;       // mouth closing after speech
	constexpr float RestOutSeconds = 0.04f;     // solver back in charge when speech starts

	float Approach(float Current, float Target, float DeltaTime, float TimeConstant)
	{
		return Target + (Current - Target) * FMath::Exp(-DeltaTime / TimeConstant);
	}

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

	Expressions = MakeShared<FVIPExpressionLayer>();
	Life = MakeShared<FVIPLife>();
	StartSource(VoiceSampleRate);

	// Which patient: from the case later (#24); for now from the command line
	FString Gender;
	int32 Age = -1;
	FParse::Value(FCommandLine::Get(), TEXT("VIPGender="), Gender);
	FParse::Value(FCommandLine::Get(), TEXT("VIPAge="), Age);
	int32 LooksAge = 72; // Walter, the patient placed in the level
	VIPPatients::Choose(InWorld, Gender, Age, &LooksAge);

	// Older patients move less and slower
	FVIPLifeParams LifeParams;
	LifeParams.Movement = LooksAge >= 70 ? 0.65f : LooksAge >= 55 ? 0.8f : 1.0f;
	Life->Set(LifeParams);

	DriveFace();

	FString Emotion = TEXT("neutral");
	float Intensity = 1.0f;
	FString Moods;
	FParse::Value(FCommandLine::Get(), TEXT("VIPMood="), Emotion);
	FParse::Value(FCommandLine::Get(), TEXT("VIPIntensity="), Intensity);
	FParse::Value(FCommandLine::Get(), TEXT("VIPMoodSeconds="), TestMoodSeconds);
	if (FParse::Value(FCommandLine::Get(), TEXT("VIPMoods="), Moods, false))
	{
		Moods.ParseIntoArray(TestMoods, TEXT(","));
		NextTestMoodAt = FPlatformTime::Seconds() + 3;
		bLogFace = true;
	}
	SetEmotion(Emotion, Intensity);

	// -VIPWide: pull the camera back to see the whole patient (clothing, posture, breathing checks)
	float Wide = 0;
	if (FParse::Value(FCommandLine::Get(), TEXT("VIPWide="), Wide))
	{
		for (TActorIterator<ACameraActor> It(&InWorld); It; ++It)
		{
			It->AddActorWorldOffset(FVector(0, Wide, -Wide * 0.35f));
		}
	}

	FString Shots;
	if (FParse::Value(FCommandLine::Get(), TEXT("VIPShots="), Shots, false))
	{
		Shots.ParseIntoArray(ShotSteps, TEXT(","));
		ShotDir = FPaths::ProjectSavedDir() / TEXT("VIPShots");
		FParse::Value(FCommandLine::Get(), TEXT("VIPShotDir="), ShotDir);
		NextShotAt = FPlatformTime::Seconds() + 6; // let the face and exposure settle
		bLogFace = true;
	}
}

void UVIPSpeechSubsystem::ApplyTestStep(const FString& Step)
{
	// "sad" or "sad@1.5": emotion at an intensity
	FString Name = Step;
	FString Strength;
	float Intensity = TargetIntensity > 0 ? TargetIntensity : 1.0f;
	if (Step.Split(TEXT("@"), &Name, &Strength))
	{
		Intensity = FCString::Atof(*Strength);
	}
	SetEmotion(Name, Intensity);
}

void UVIPSpeechSubsystem::RunShots(double Now)
{
	if (ShotSteps.Num() == 0 || Now < NextShotAt)
	{
		return;
	}
	if (ShotIndex >= ShotSteps.Num())
	{
		UE_LOG(LogVIP, Display, TEXT("VIP: SHOTS DONE in %s"), *ShotDir);
		ShotSteps.Reset();
		RequestEngineExit(TEXT("VIP shots done"));
		return;
	}
	if (!bShotApplied)
	{
		ApplyTestStep(ShotSteps[ShotIndex]);
		bShotApplied = true;
		NextShotAt = Now + ShotSettleSeconds;
		return;
	}
	const FString File = ShotDir / FString::Printf(TEXT("%02d_%s.png"), ShotIndex, *ShotSteps[ShotIndex].Replace(TEXT("@"), TEXT("_")));
	FScreenshotRequest::RequestScreenshot(File, false, false);
	UE_LOG(LogVIP, Display, TEXT("VIP: shot %s"), *File);
	bShotApplied = false;
	++ShotIndex;
	NextShotAt = Now + 0.5;
}

void UVIPSpeechSubsystem::AnimateBody(USkeletalMeshComponent& Body)
{
	// Without body data the MetaHuman stands in the A-pose with its arms out. Epic's idle loop gives
	// arms down, breathing and small weight shifts (#44, #36)
	FString Path = TEXT("/MetaHumanCharacter/Optional/Animation/UEFNAnimPreset/Locomotion/AS_MH_Neutral_Stand_Idle_Loop.AS_MH_Neutral_Stand_Idle_Loop");
	FParse::Value(FCommandLine::Get(), TEXT("VIPBodyAnim="), Path);
	if (Path == TEXT("none"))
	{
		return;
	}
	UAnimSequence* Idle = LoadObject<UAnimSequence>(nullptr, *Path);
	if (!Idle)
	{
		UE_LOG(LogVIP, Warning, TEXT("Body idle %s not found, body stays in its rest pose"), *Path);
		return;
	}
	Body.PlayAnimation(Idle, true);
	Body.SetPosition(FMath::FRandRange(0.0f, Idle->GetPlayLength())); // patients do not all start alike
	UE_LOG(LogVIP, Display, TEXT("Body plays %s"), *Idle->GetName());
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
			if (FParse::Param(FCommandLine::Get(), TEXT("VIPDumpControls")))
			{
				UE_LOG(LogVIP, Display, TEXT("mesh %s.%s: mode %d, anim %s, leader %s, bones %d"), *It->GetName(), *Mesh->GetName(),
					static_cast<int32>(Mesh->GetAnimationMode()), Mesh->GetAnimClass() ? *Mesh->GetAnimClass()->GetName() : TEXT("none"),
					Mesh->LeaderPoseComponent.IsValid() ? *Mesh->LeaderPoseComponent->GetName() : TEXT("none"), Mesh->GetNumBones());
			}
			if (Mesh->GetName() == TEXT("Body"))
			{
				AnimateBody(*Mesh);
				continue;
			}
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
	TSharedPtr<FVIPSpeechSource> SpeechSource = MakeShared<FVIPSpeechSource>(Queue.ToSharedRef(), Expressions.ToSharedRef(), Life.ToSharedRef());
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
	const FString Name = Emotion.TrimStartAndEnd().ToLower();
	if (!VIPExpressions::IsKnown(Name))
	{
		UE_LOG(LogVIP, Warning, TEXT("Unknown emotion '%s', using neutral"), *Emotion);
	}
	TargetEmotion = VIPExpressions::IsKnown(Name) ? Name : TEXT("neutral");
	TargetIntensity = FMath::Clamp(Intensity, 0.0f, MaxIntensity);
	EmotionSetAt = FPlatformTime::Seconds();
	UE_LOG(LogVIP, Display, TEXT("Emotion %s %.2f"), *TargetEmotion, TargetIntensity);
}

void UVIPSpeechSubsystem::UpdateEmotion(float DeltaTime)
{
	// Full strength while speaking and for a while after, then a resting level until the next turn
	const double Now = FPlatformTime::Seconds();
	const bool bHolding = Now < FMath::Max(EmotionSetAt, SpeakingUntil) + HoldSeconds;
	const float Wanted = TargetEmotion == TEXT("neutral") ? 0.0f : TargetIntensity * (bHolding ? 1.0f : RestFraction);
	Level = Approach(Level, Wanted, DeltaTime, Wanted > Level ? RiseSeconds : FallSeconds);

	// Our layer cross-fades: the old emotion fades out while the new one fades in
	TMap<FString, float> Offsets;
	for (const FString& Name : VIPExpressions::Names())
	{
		float& Weight = EmotionWeights.FindOrAdd(Name);
		Weight = Approach(Weight, Name == TargetEmotion ? 1.0f : 0.0f, DeltaTime, CrossfadeSeconds);
		VIPExpressions::Add(Name, Weight * Level, Offsets);
	}
	// In silence, fade the solver's open-mouthed idle pose out to a closed, relaxed mouth
	const bool bSpeaking = Now < SpeakingUntil;
	Rest = Approach(Rest, bSpeaking ? 0.0f : 1.0f, DeltaTime, bSpeaking ? RestOutSeconds : RestInSeconds);
	if (Expressions)
	{
		Expressions->Set(MoveTemp(Offsets));
		Expressions->SetRest(Rest);
	}

	// The solver holds one mood up to 1: ramp down, switch, ramp up, so there is no jump
	const float Step = SolverRampPerSecond * DeltaTime;
	if (SolverEmotion != TargetEmotion)
	{
		SolverIntensity = FMath::Max(0.0f, SolverIntensity - Step);
		if (SolverIntensity <= 0)
		{
			SolverEmotion = TargetEmotion;
		}
	}
	else
	{
		const float SolverTarget = FMath::Min(Level, 1.0f);
		SolverIntensity = SolverIntensity < SolverTarget ? FMath::Min(SolverTarget, SolverIntensity + Step) : SolverTarget;
	}
	ApplySolverMood();
}

void UVIPSpeechSubsystem::ApplySolverMood()
{
	if (!Settings || (SolverEmotion == AppliedSolverEmotion && FMath::Abs(SolverIntensity - AppliedSolverIntensity) < 0.01f))
	{
		return;
	}
	AppliedSolverEmotion = SolverEmotion;
	AppliedSolverIntensity = SolverIntensity;

	if (Settings->Subject)
	{
		Settings->Mood = ToMood(SolverEmotion);
		Settings->SetMoodIntensity(SolverIntensity); // passes mood and intensity to the solver
	}
	else
	{
		// Live Link creates the subject a frame later and reads these then; the setters would crash now
		Settings->Mood = ToMood(SolverEmotion);
		Settings->MoodIntensity = FMath::Clamp(SolverIntensity, 0.0f, 1.0f);
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

	if (NextTestMoodAt > 0 && Now >= NextTestMoodAt && TestMoods.Num() > 0)
	{
		SetEmotion(TestMoods[TestMoodIndex], TargetIntensity > 0 ? TargetIntensity : 1.0f);
		TestMoodIndex = (TestMoodIndex + 1) % TestMoods.Num();
		NextTestMoodAt = Now + TestMoodSeconds;
	}

	RunShots(Now);
	UpdateEmotion(DeltaTime);

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
	if (FParse::Param(FCommandLine::Get(), TEXT("VIPDumpControls")))
	{
		FString High;
		for (int32 i = 0; i < Static->PropertyNames.Num() && i < Data->PropertyValues.Num(); ++i)
		{
			if (FMath::Abs(Data->PropertyValues[i]) > 0.25f)
			{
				High += FString::Printf(TEXT("%s=%.2f "), *Static->PropertyNames[i].ToString(), Data->PropertyValues[i]);
			}
		}
		UE_LOG(LogVIP, Display, TEXT("frame %d names %d values, high: %s"), Static->PropertyNames.Num(), Data->PropertyValues.Num(), *High);
	}
	UE_LOG(LogVIP, Display, TEXT("face %s: jaw=%.2f blink=%.2f headSwitch=%.0f yaw=%.1f pitch=%.1f"),
		FPlatformTime::Seconds() < SpeakingUntil ? TEXT("speaking") : TEXT("silent"),
		Value(TEXT("CTRL_expressions_jawOpen")), Value(TEXT("CTRL_expressions_eyeBlinkL")),
		Value(TEXT("HeadControlSwitch")), Value(TEXT("HeadYaw")), Value(TEXT("HeadPitch")));
	UE_LOG(LogVIP, Display, TEXT("mood %s level=%.2f solver=%s %.2f: browDown=%.2f browRaiseIn=%.2f cornerPull=%.2f cornerDepress=%.2f"),
		*TargetEmotion, Level, *SolverEmotion, SolverIntensity,
		Value(TEXT("CTRL_expressions_browDownL")), Value(TEXT("CTRL_expressions_browRaiseInL")),
		Value(TEXT("CTRL_expressions_mouthCornerPullL")), Value(TEXT("CTRL_expressions_mouthCornerDepressL")));
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
