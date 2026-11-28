#pragma once

#include "CoreMinimal.h"

class FJsonObject;

/**
 * What Unreal needs from a patient case to show the right patient (#45): who it is, the starting
 * mood, how the personality shows in body language, and what the illness looks like.
 *
 * Reads the teacher UI's case JSON (cases/patient-case.schema.json): character_id, patient.age,
 * patient.gender, personality.mood, personality.type. Optional, proposed for the schema:
 *
 *   "presentation": {"pain": 0-10, "breathing": "normal|fast_shallow|laboured|slow_deep|<rate>",
 *                    "discomfort": 0-1, "visible_signs": ["pale", "sweaty", ...]}
 *
 * Missing fields keep their defaults, so any case works.
 */
struct FVIPCase
{
	FString Character;
	FString Gender;
	int32 Age = -1;
	FString Mood = TEXT("neutral");
	FString Personality;
	float Pain = 0;
	FString Breathing = TEXT("normal");
	float Discomfort = 0;
	TArray<FString> VisibleSigns;

	/** Accepts the case itself or a message wrapping it in "case". */
	static bool FromJson(const TSharedPtr<FJsonObject>& Json, FVIPCase& Out);
	static bool FromFile(const FString& Path, FVIPCase& Out);
};

/** How a personality shows in the face and body, on top of the idle behaviour. */
struct FVIPPersonalityStyle
{
	float BlinkRate = 1;      // multiplier
	float GlanceRate = 0;     // added
	float Nods = 1;           // multiplier
	float Movement = 1;       // multiplier
	float Discomfort = 0;     // lowest discomfort, e.g. a shy patient never quite looks at you
	float Squint = 0;         // a wary, narrowed look

	static FVIPPersonalityStyle For(const FString& Personality);
};
