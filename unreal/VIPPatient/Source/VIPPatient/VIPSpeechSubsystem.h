#pragma once

#include "CoreMinimal.h"
#include "ILiveLinkSource.h"
#include "Subsystems/WorldSubsystem.h"
#include "VIPSpeechSubsystem.generated.h"

class FVIPExpressionLayer;
class FVIPLife;
class FVIPSpeechQueue;
class UMetaHumanAudioBaseLiveLinkSubjectSettings;
class UAudioComponent;
class USkeletalMeshComponent;
class USoundWaveProcedural;

/**
 * Makes the patient speak: plays 16-bit PCM speech and animates the face from the same samples.
 *
 * For testing: -VIPWav=<16-bit WAV> says the file every few seconds and logs face values once a
 * second; -VIPMood=<emotion> sets the mood and -VIPIntensity=<0 to 2> its strength;
 * -VIPMoods=neutral,sad,neutral,anger steps through moods every -VIPMoodSeconds (default 4);
 * -VIPGender=female -VIPAge=25 picks the patient.
 * -VIPShots=neutral,sad,sad@2 takes a screenshot of each step into Saved/VIPShots (or -VIPShotDir=)
 * and quits; it prints "VIP: SHOTS DONE" when finished.
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

	/**
	 * One of the emotion names in the README; unknown values fall back to neutral. Intensity 0 to 2:
	 * the face solver takes up to 1, our expression layer goes further so moods read at a distance.
	 * The new mood blends in over about a second, and eases to a resting level a few seconds after
	 * it was set or the patient stopped speaking.
	 */
	void SetEmotion(const FString& Emotion, float Intensity);

protected:

	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:

	void StartSource(int32 SampleRate);
	void DriveFace();
	void AnimateBody(USkeletalMeshComponent& Body);
	void UpdateEmotion(float DeltaTime);
	void ApplySolverMood();
	void LogFace(float DeltaTime);
	void ApplyTestStep(const FString& Step);
	void RunShots(double Now);

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

	// Emotion: what was asked for, and where the blend currently is
	TSharedPtr<FVIPExpressionLayer> Expressions;
	TSharedPtr<FVIPLife> Life;
	FString TargetEmotion = TEXT("neutral");
	float TargetIntensity = 0;
	double EmotionSetAt = 0;
	float Level = 0;
	float Rest = 1;
	TMap<FString, float> EmotionWeights;
	FString SolverEmotion = TEXT("neutral");
	float SolverIntensity = 0;
	FString AppliedSolverEmotion;
	float AppliedSolverIntensity = -1;

	TArray<FString> TestMoods;
	float TestMoodSeconds = 4;
	int32 TestMoodIndex = 0;
	double NextTestMoodAt = 0;

	// Screenshot test (-VIPShots)
	TArray<FString> ShotSteps;
	FString ShotDir;
	int32 ShotIndex = 0;
	double NextShotAt = 0;
	bool bShotApplied = false;
	static constexpr double ShotSettleSeconds = 2.5;

	bool bLogFace = false;
	float LogTimer = 0;
};
