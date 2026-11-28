#pragma once

#include "CoreMinimal.h"
#include "ILiveLinkSource.h"
#include "Subsystems/WorldSubsystem.h"
#include "VIPCase.h"
#include "VIPSpeechSubsystem.generated.h"

class FVIPExpressionLayer;
class FVIPLife;
class FVIPSpeechQueue;
class UMetaHumanAudioBaseLiveLinkSubjectSettings;
class UAudioComponent;
class USkeletalMeshComponent;
class UVIPBodyAnimInstance;
class USoundWaveProcedural;

/**
 * Makes the patient speak: plays 16-bit PCM speech and animates the face from the same samples.
 *
 * For testing: -VIPWav=<16-bit WAV> says the file every few seconds, logs the delay from Speak() to
 * the first open jaw ("VIP latency:") and logs face values once a
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

	/**
	 * What the patient is doing in the conversation (#37): "listening" (the student talks: eye
	 * contact, small nods), "thinking" (the answer is being generated: looks up and aside) or
	 * "idle". While speech plays the patient is "speaking" regardless. Unknown values mean listening.
	 */
	void SetAttention(const FString& State);

	/**
	 * Pain 0 to 10 from the case or the turn (#35). Shows as a lasting pain face that grows with the
	 * level, plus short winces now and then from level 3.
	 */
	void SetPain(float InLevel);

	/**
	 * Breathing (#36): breaths per minute, depth (1 normal, below shallow, above deep) and how much
	 * the shoulders lift (0 to 1, laboured breathing). Changes ease in over a few seconds.
	 */
	void SetBreathing(float PerMinute, float InDepth, float Shoulders);

	/** A named pattern: normal, fast_shallow, laboured, slow_deep, or a rate such as "22". */
	void SetBreathing(const FString& Pattern);

	/**
	 * Discomfort 0 to 1 (#38): on sensitive topics the patient avoids eye contact, looks down and to
	 * the side, blinks more and stops nodding. Eases back when it drops, e.g. after an empathetic
	 * question.
	 */
	void SetDiscomfort(float InDiscomfort);

	/**
	 * Shows the patient a case describes (#45): picks the patient (character, gender, age), sets the
	 * starting mood, personality body language, pain, breathing and discomfort. Pain and discomfort
	 * from the case are the floor: later turns can raise them, not drop below. Can be called again.
	 */
	void ApplyCase(const FVIPCase& Case);

	/** The student interrupted: stop talking now and look at them (#25, #37). */
	void StopSpeaking();

protected:

	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:

	void StartSource(int32 SampleRate);
	void DriveFace();
	void AnimateBody(USkeletalMeshComponent& Body);
	void ApplyBreathing();
	void UpdateEmotion(float DeltaTime);
	void UpdateLife();
	void ApplySolverMood();
	void LogFace(float DeltaTime);
	void ProbeLatency(double Now);
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
	float LifeMovement = 1;
	FString Attention = TEXT("listening");
	double AttentionSetAt = 0;
	float ThinkSide = 1;
	FString TargetEmotion = TEXT("neutral");
	float TargetIntensity = 0;
	double EmotionSetAt = 0;
	float Level = 0;
	float Rest = 1;
	UPROPERTY()
	TObjectPtr<UVIPBodyAnimInstance> BodyAnim;
	float BreathsPerMinute = 14;
	float BreathDepth = 1;
	float BreathShoulders = 0.15f;

	float Discomfort = 0;       // asked for
	float DiscomfortShown = 0;  // smoothed
	float AvoidSide = 1;

	FVIPPersonalityStyle Style;
	TWeakObjectPtr<AActor> Patient;
	float CasePain = 0;
	float CaseDiscomfort = 0;

	float PainLevel = 0;  // 0 to 10, what was asked for
	float PainShown = 0;  // 0 to 1, smoothed
	double WinceStart = -1;
	double NextWince = 0;
	TMap<FString, float> EmotionWeights;
	FString SolverEmotion = TEXT("neutral");
	float SolverIntensity = 0;
	FString AppliedSolverEmotion;
	float AppliedSolverIntensity = -1;

	TArray<FString> TestMoods;
	float TestMoodSeconds = 4;
	double NextOutfitCheck = 0;
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

	// Delay probe for test runs: time from Speak() to the first open jaw
	double LatencySpeakAt = 0;
	double LatencyVoiceOffset = 0;
	bool bLatencyPending = false;
	bool bLatencySoundPending = false;
};
