#pragma once

#include "CoreMinimal.h"
#include "MetaHumanAudioBaseLiveLinkSubject.h"
#include "MetaHumanLocalLiveLinkSource.h"

/** Speech waiting to be turned into face animation. Written by the game thread, read by the solver. */
class FVIPSpeechQueue
{
public:

	explicit FVIPSpeechQueue(int32 InSampleRate) : SampleRate(InSampleRate) {}

	/** Mono samples at SampleRate. */
	void Add(const TArray<float>& Samples);

	/** Fills Out with the next samples, padded with silence. */
	void Take(TArray<float>& Out, int32 Count);

	const int32 SampleRate;

private:

	FCriticalSection Mutex;
	TArray<float> Pending;
};

/**
 * MetaHuman audio subject fed with our own samples instead of a capture device, so generated
 * speech drives the face without a microphone or a virtual audio cable.
 */
class FVIPSpeechSubject : public FMetaHumanAudioBaseLiveLinkSubject
{
public:

	FVIPSpeechSubject(ILiveLinkClient* InClient, const FGuid& InSourceGuid, const FName& InName,
		UMetaHumanAudioBaseLiveLinkSubjectSettings* InSettings, TSharedRef<FVIPSpeechQueue> InQueue);

protected:

	virtual void MediaSamplerMain() override;

	/** Adds idle life on top of the solver: blinks and slight head motion. */
	virtual void ExtractPipelineData(TSharedPtr<UE::MetaHuman::Pipeline::FPipelineData> InPipelineData) override;

private:

	TSharedRef<FVIPSpeechQueue> Queue;

	// Only touched on the pipeline thread
	FRandomStream Random{FPlatformTime::Cycles()};
	double StartTime = FPlatformTime::Seconds();
	double NextBlink = 0;
	double BlinkStart = -1;
};

class FVIPSpeechSource : public FMetaHumanLocalLiveLinkSource
{
public:

	explicit FVIPSpeechSource(TSharedRef<FVIPSpeechQueue> InQueue) : Queue(InQueue) {}

	virtual FText GetSourceType() const override;

protected:

	virtual TSharedPtr<FMetaHumanLocalLiveLinkSubject> CreateSubject(const FName& InSubjectName,
		UMetaHumanLocalLiveLinkSubjectSettings* InSettings) override;

private:

	TSharedRef<FVIPSpeechQueue> Queue;
};
