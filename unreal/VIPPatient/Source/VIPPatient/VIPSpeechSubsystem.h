#pragma once

#include "CoreMinimal.h"
#include "ILiveLinkSource.h"
#include "Subsystems/WorldSubsystem.h"
#include "VIPSpeechSubsystem.generated.h"

class FVIPSpeechQueue;
class UMetaHumanAudioBaseLiveLinkSubjectSettings;
class UAudioComponent;
class USoundWaveProcedural;

/**
 * Makes the patient speak: plays 16-bit PCM speech and animates the face from the same samples.
 *
 * For testing: -VIPWav=<16-bit WAV> says the file every few seconds and logs face values once a
 * second; -VIPMood=<emotion> sets the mood; -VIPGender=female -VIPAge=25 picks the patient.
 */
UCLASS()
class UVIPSpeechSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:

	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

	/** Mono 16-bit samples at any rate. Speech given while talking is queued behind it. */
	void Speak(const TArray<int16>& Samples, int32 SampleRate);

	/** One of the emotion names in the README. Unknown values fall back to neutral. */
	void SetEmotion(const FString& Emotion, float Intensity);

protected:

	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:

	void StartSource(int32 SampleRate);
	void DriveFace();
	void LogFace(float DeltaTime);

	UPROPERTY()
	TObjectPtr<UMetaHumanAudioBaseLiveLinkSubjectSettings> Settings;

	UPROPERTY()
	TObjectPtr<USoundWaveProcedural> Voice;

	UPROPERTY()
	TObjectPtr<UAudioComponent> VoicePlayer;

	TSharedPtr<FVIPSpeechQueue> Queue;
	TSharedPtr<ILiveLinkSource> Source;

	// Playback is held back so the sound leaves together with the lips
	TArray<int16> DelayedSound;
	double PlaySoundAt = 0;

	TArray<int16> TestSpeech;
	int32 TestRate = 0;
	double NextTestAt = 0;
	double SpeakingUntil = 0;

	bool bLogFace = false;
	float LogTimer = 0;
};
