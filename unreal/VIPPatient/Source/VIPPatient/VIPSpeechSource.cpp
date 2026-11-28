#include "VIPSpeechSource.h"

#include "VIPExpressions.h"

#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

#include "MetaHumanAudioBaseLiveLinkSubjectSettings.h"
#include "MetaHumanHeadTransform.h"

namespace
{
	// The solver expects a steady stream, like a capture device delivers it
	constexpr int32 ChunksPerSecond = 50;

	// Idle behaviour
	constexpr double BlinkSeconds = 0.2;
	constexpr double MinBlinkGap = 2.0;
	constexpr double MaxBlinkGap = 5.5;
	constexpr double HeadDegrees = 2.0;

	/** 0 to 1 and back: shuts quickly, opens a little slower, like a real blink. */
	float BlinkShape(double Phase)
	{
		constexpr double Closed = 0.35;
		return static_cast<float>(Phase < Closed ? Phase / Closed : 1.0 - (Phase - Closed) / (1.0 - Closed));
	}
}

void FVIPSpeechQueue::Add(const TArray<float>& Samples)
{
	FScopeLock Lock(&Mutex);
	Pending.Append(Samples);
}

void FVIPSpeechQueue::Take(TArray<float>& Out, int32 Count)
{
	Out.SetNumZeroed(Count);

	FScopeLock Lock(&Mutex);
	const int32 Available = FMath::Min(Count, Pending.Num());
	if (Available > 0)
	{
		FMemory::Memcpy(Out.GetData(), Pending.GetData(), Available * sizeof(float));
		Pending.RemoveAt(0, Available);
	}
}

FVIPSpeechSubject::FVIPSpeechSubject(ILiveLinkClient* InClient, const FGuid& InSourceGuid, const FName& InName,
	UMetaHumanAudioBaseLiveLinkSubjectSettings* InSettings, TSharedRef<FVIPSpeechQueue> InQueue,
	TSharedRef<FVIPExpressionLayer> InExpressions)
	: FMetaHumanAudioBaseLiveLinkSubject(InClient, InSourceGuid, InName, InSettings)
	, Queue(InQueue)
	, Expressions(InExpressions)
{
}

void FVIPSpeechSubject::MediaSamplerMain()
{
	// Start() launches this thread and the pipeline thread together; the pipeline only counts as
	// running once its thread has begun, so wait for that instead of quitting straight away
	const double GiveUp = FPlatformTime::Seconds() + 10;
	while (!IsRunning() && FPlatformTime::Seconds() < GiveUp)
	{
		FPlatformProcess::Sleep(0.005f);
	}

	const int32 Count = Queue->SampleRate / ChunksPerSecond;
	double Next = FPlatformTime::Seconds();

	while (IsRunning())
	{
		FAudioSample Sample;
		Sample.NumChannels = 1;
		Sample.SampleRate = Queue->SampleRate;
		Sample.NumSamples = Count;
		Queue->Take(Sample.Data, Count);
		GetSampleTime(FFrameRate(ChunksPerSecond, 1), Sample.Time, Sample.TimeSource);
		AddAudioSample(MoveTemp(Sample));

		Next += 1.0 / ChunksPerSecond;
		const double Wait = Next - FPlatformTime::Seconds();
		if (Wait > 0)
		{
			FPlatformProcess::Sleep(static_cast<float>(Wait));
		}
		else if (Wait < -0.5)
		{
			Next = FPlatformTime::Seconds(); // after a hitch, do not burst the backlog
		}
	}
}

void FVIPSpeechSubject::ExtractPipelineData(TSharedPtr<UE::MetaHuman::Pipeline::FPipelineData> InPipelineData)
{
	FMetaHumanAudioBaseLiveLinkSubject::ExtractPipelineData(InPipelineData);
	if (Animation.AnimationData.IsEmpty())
	{
		return;
	}

	static double NextDump = 0;
	const bool bDump = FParse::Param(FCommandLine::Get(), TEXT("VIPDumpControls")) && FPlatformTime::Seconds() > NextDump;
	auto Pick = [this](const TCHAR* Name) { const float* V = Animation.AnimationData.Find(Name); return V ? *V : -1.0f; };
	const float BeforeBrow = Pick(TEXT("CTRL_expressions_browDownL"));
	const float BeforeCorner = Pick(TEXT("CTRL_expressions_mouthCornerPullL"));
	Expressions->ApplyTo(Animation.AnimationData);
	if (bDump)
	{
		NextDump = FPlatformTime::Seconds() + 1;
		UE_LOG(LogTemp, Display, TEXT("VIP layer: browDownL %.2f -> %.2f, cornerPullL %.2f -> %.2f"),
			BeforeBrow, Pick(TEXT("CTRL_expressions_browDownL")), BeforeCorner, Pick(TEXT("CTRL_expressions_mouthCornerPullL")));
	}

	const double Now = FPlatformTime::Seconds();

	// The solver blinks rarely and stops after a while, which reads as staring
	if (Now >= NextBlink && BlinkStart < 0)
	{
		BlinkStart = Now;
		NextBlink = Now + Random.FRandRange(MinBlinkGap, MaxBlinkGap);
	}
	if (BlinkStart >= 0)
	{
		const double Phase = (Now - BlinkStart) / BlinkSeconds;
		const float Blink = Phase >= 1.0 ? 0.0f : BlinkShape(Phase);
		for (const TCHAR* Name : {TEXT("CTRL_expressions_eyeBlinkL"), TEXT("CTRL_expressions_eyeBlinkR")})
		{
			if (float* Value = Animation.AnimationData.Find(Name))
			{
				*Value = FMath::Max(*Value, Blink);
			}
		}
		if (Phase >= 1.0)
		{
			BlinkStart = -1;
		}
	}

	// Slow, slight head motion from overlapping sine waves, so it never repeats visibly
	const double T = Now - StartTime;
	const FRotator Sway(
		HeadDegrees * (0.6 * FMath::Sin(T * 0.31 + 2.0) + 0.3 * FMath::Sin(T * 0.87)),
		HeadDegrees * (1.0 * FMath::Sin(T * 0.23) + 0.4 * FMath::Sin(T * 0.61 + 1.0)),
		HeadDegrees * 0.4 * FMath::Sin(T * 0.17 + 4.0));
	// The audio solver leaves the pose all zero, which means "no head data"; start from rest then
	const bool bHasPose = Animation.Pose.GetRotation().SizeSquared() > 0.5;
	FTransform Bone = bHasPose ? FMetaHumanHeadTransform::MeshToBone(Animation.Pose) : FTransform::Identity;
	Bone.SetRotation(Sway.Quaternion() * Bone.GetRotation());
	const FVector Translation = Animation.Pose.GetTranslation();
	Animation.Pose = FMetaHumanHeadTransform::BoneToMesh(Bone);
	Animation.Pose.SetTranslation(Translation);
	HeadControlSwitch = 1;
	HeadPoseMode = EMetaHumanLiveLinkHeadPoseMode::Orientation; // otherwise the rotation is zeroed later
}

FText FVIPSpeechSource::GetSourceType() const
{
	return NSLOCTEXT("VIPPatient", "SpeechSource", "VIP Speech");
}

TSharedPtr<FMetaHumanLocalLiveLinkSubject> FVIPSpeechSource::CreateSubject(const FName& InSubjectName,
	UMetaHumanLocalLiveLinkSubjectSettings* InSettings)
{
	return MakeShared<FVIPSpeechSubject>(LiveLinkClient, SourceGuid, InSubjectName,
		CastChecked<UMetaHumanAudioBaseLiveLinkSubjectSettings>(InSettings), Queue, Expressions);
}
