#include "VIPSpeechSource.h"

#include "VIPExpressions.h"
#include "VIPLife.h"

#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

#include "MetaHumanAudioBaseLiveLinkSubjectSettings.h"
#include "MetaHumanHeadTransform.h"

namespace
{
	// The solver expects a steady stream, like a capture device delivers it
	constexpr int32 ChunksPerSecond = 50;
}

void FVIPSpeechQueue::Add(const TArray<float>& Samples)
{
	FScopeLock Lock(&Mutex);
	Pending.Append(Samples);
}

void FVIPSpeechQueue::Clear()
{
	FScopeLock Lock(&Mutex);
	Pending.Reset();
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
	TSharedRef<FVIPExpressionLayer> InExpressions, TSharedRef<FVIPLife> InLife)
	: FMetaHumanAudioBaseLiveLinkSubject(InClient, InSourceGuid, InName, InSettings)
	, Queue(InQueue)
	, Expressions(InExpressions)
	, Life(InLife)
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

	// Eyes, blinks, small face movement and head sway, so the patient never stares
	const FRotator Sway = Life->Apply(Animation.AnimationData, FPlatformTime::Seconds());

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
		CastChecked<UMetaHumanAudioBaseLiveLinkSubjectSettings>(InSettings), Queue, Expressions, Life);
}
