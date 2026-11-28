#pragma once

#include "CoreMinimal.h"

/**
 * Face controls for each emotion, added on top of the audio solver. The solver's moods are subtle
 * (#22), only work up to intensity 1 and switch hard; this layer blends and can go stronger.
 *
 * Recipes use the brows, eyes, cheeks, nose and mouth corners (FACS action units in the .cpp) and
 * leave the lips and jaw to lip sync.
 */
namespace VIPExpressions
{
	/** True for the emotion names in the README. */
	bool IsKnown(const FString& Emotion);

	/** All known emotion names, lower case. */
	const TArray<FString>& Names();

	/** Adds the controls for Emotion, scaled by Weight, to Out (control name to value). */
	void Add(const FString& Emotion, float Weight, TMap<FString, float>& Out);
}

/** Expression offsets handed from the game thread to the pipeline thread. */
class FVIPExpressionLayer
{
public:

	void Set(TMap<FString, float>&& InOffsets);

	/**
	 * 0 while speaking, 1 when silent. In silence the solver settles into a pose with the mouth
	 * open and the lips pulled; at rest the solver's face is faded out to the rig's closed neutral.
	 */
	void SetRest(float InRest);

	/** Adds the current offsets to the solver's controls, clamped to the rig's 0 to 1. */
	void ApplyTo(TMap<FString, float>& AnimationData);

private:

	FCriticalSection Mutex;
	TMap<FString, float> Offsets;
	float Rest = 0;
};
