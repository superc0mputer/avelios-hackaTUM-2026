#pragma once

#include "CoreMinimal.h"

/**
 * What the game thread wants from the idle behaviour. Later issues steer the patient through this:
 * listening and thinking (#37) and looking away (#38) move the gaze and head, age slows movement.
 */
struct FVIPLifeParams
{
	/** Where the eyes rest, in eye-control units: +X is the patient's left, +Y is up. 0,0 = the camera. */
	FVector2f Gaze = FVector2f::ZeroVector;

	/** Extra head rotation in degrees, added to the idle sway (for looking down or away). */
	float HeadPitch = 0;
	float HeadYaw = 0;

	/** 1 = normal. Older or tired patients move less and slower. */
	float Movement = 1;

	/** 1 = normal. Discomfort and nervousness blink more. */
	float BlinkRate = 1;

	/** 0 to 1: how often the eyes break contact with short glances aside. */
	float GlanceRate = 0.3f;

	/** Small nods per minute, for listening. */
	float NodsPerMinute = 0;
};

/**
 * Small involuntary movement on top of the solver, so the face is never still: eye saccades and
 * glances, blinks (sometimes double), slight brow and mouth movement, and head sway.
 * Runs on the pipeline thread; Set() is called from the game thread.
 */
class FVIPLife
{
public:

	void Set(const FVIPLifeParams& InParams);

	/** Adds idle movement to the face controls. Returns the head rotation to add, in degrees. */
	FRotator Apply(TMap<FString, float>& Controls, double Now);

private:

	void UpdateEyes(double Now, const FVIPLifeParams& P);
	void UpdateBlink(double Now, const FVIPLifeParams& P, TMap<FString, float>& Controls);

	FCriticalSection Mutex;
	FVIPLifeParams Params;

	// Pipeline thread only
	FRandomStream Random{FPlatformTime::Cycles()};
	double StartTime = FPlatformTime::Seconds();
	double LastTime = 0;
	FVector2f Eye = FVector2f::ZeroVector;      // where the eyes are
	FVector2f EyeTarget = FVector2f::ZeroVector; // offset from the gaze they are moving to
	double NextSaccade = 0;
	double GlanceUntil = 0;
	double NextBlink = 0;
	double BlinkStart = -1;
	bool bDoubleBlink = false;
	FRotator Head = FRotator::ZeroRotator;       // smoothed head offset
	double NextNod = 0;
	double NodStart = -1;
	float Phase[8] = {};
};
