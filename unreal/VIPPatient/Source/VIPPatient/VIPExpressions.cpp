#include "VIPExpressions.h"

namespace
{
	// The recipes were tuned on top of the solver's idle face; at rest that face is faded out (closed
	// mouth), so the recipes alone need a little more to read at demo distance
	constexpr float RecipeGain = 1.3f;
	struct FControl
	{
		const TCHAR* Name; // without CTRL_expressions_; "L"/"R" are added unless Sided
		float Value;
		bool bSided = false;
	};

	// Values are at weight 1. Action units (AU) from the Facial Action Coding System.
	const TMap<FString, TArray<FControl>>& Recipes()
	{
		static const TMap<FString, TArray<FControl>> Table = {
			{TEXT("neutral"), {}},
			// AU6 cheek raise + AU12 lip corner pull: a real (Duchenne) smile reaches the eyes
			{TEXT("happy"), {{TEXT("eyeCheekRaise"), 0.3f}, {TEXT("mouthCornerPull"), 0.55f}, {TEXT("eyeSquintInner"), 0.1f}}},
			// AU1 inner brow raise + AU4 slight brow lowering + AU15 lip corner depress, heavy lids
			{TEXT("sad"), {{TEXT("browRaiseIn"), 0.7f}, {TEXT("browDown"), 0.15f}, {TEXT("browLateral"), 0.2f},
				{TEXT("mouthCornerDepress"), 0.45f}, {TEXT("eyeRelax"), 0.3f}}},
			// AU1+2+4 raised and drawn-together brows + AU5 upper lid raise + AU20 lip stretch
			{TEXT("fear"), {{TEXT("browRaiseIn"), 0.6f}, {TEXT("browRaiseOuter"), 0.45f}, {TEXT("browLateral"), 0.45f},
				{TEXT("eyeWiden"), 0.5f}, {TEXT("mouthStretch"), 0.25f}}},
			// AU9 nose wrinkle + AU10 upper lip raise + AU4
			{TEXT("disgust"), {{TEXT("noseWrinkle"), 0.55f}, {TEXT("mouthUpperLipRaise"), 0.3f}, {TEXT("browDown"), 0.3f},
				{TEXT("eyeSquintInner"), 0.2f}}},
			// AU4 lowered, drawn-together brows + AU7 lid tightener
			{TEXT("anger"), {{TEXT("browDown"), 0.65f}, {TEXT("browLateral"), 0.45f}, {TEXT("eyeSquintInner"), 0.3f},
				{TEXT("eyeLidPress"), 0.25f}, {TEXT("noseWrinkle"), 0.15f}}},
			// AU1+2 raised brows + AU5 wide eyes
			{TEXT("surprise"), {{TEXT("browRaiseIn"), 0.6f}, {TEXT("browRaiseOuter"), 0.6f}, {TEXT("eyeWiden"), 0.5f},
				{TEXT("eyeUpperLidUp"), 0.3f}}},
			// Heavy lids, slack corners
			{TEXT("boredom"), {{TEXT("eyeRelax"), 0.45f}, {TEXT("mouthCornerDepress"), 0.12f}}},
			// Slight smile, steady eyes
			{TEXT("confidence"), {{TEXT("mouthCornerPull"), 0.15f}, {TEXT("eyeSquintInner"), 0.12f}}},
			// One brow down, the other up
			{TEXT("confusion"), {{TEXT("browDownL"), 0.45f, true}, {TEXT("browRaiseOuterR"), 0.45f, true},
				{TEXT("browLateral"), 0.2f}, {TEXT("eyeSquintInner"), 0.15f}}},
			// Wide eyes and a smile
			{TEXT("excitement"), {{TEXT("eyeWiden"), 0.3f}, {TEXT("browRaiseIn"), 0.3f}, {TEXT("browRaiseOuter"), 0.3f},
				{TEXT("eyeCheekRaise"), 0.4f}, {TEXT("mouthCornerPull"), 0.4f}}},
			// One-sided smile
			{TEXT("playfulness"), {{TEXT("mouthCornerPullL"), 0.4f, true}, {TEXT("mouthCornerPullR"), 0.15f, true},
				{TEXT("eyeCheekRaise"), 0.3f}, {TEXT("browRaiseOuterL"), 0.2f, true}}},
		};
		return Table;
	}
}

bool VIPExpressions::IsKnown(const FString& Emotion)
{
	return Recipes().Contains(Emotion.ToLower());
}

const TArray<FString>& VIPExpressions::Names()
{
	static const TArray<FString> All = [] {
		TArray<FString> Keys;
		Recipes().GetKeys(Keys);
		return Keys;
	}();
	return All;
}

void VIPExpressions::Add(const FString& Emotion, float Weight, TMap<FString, float>& Out)
{
	const TArray<FControl>* Recipe = Recipes().Find(Emotion.ToLower());
	if (!Recipe || Weight <= 0)
	{
		return;
	}
	for (const FControl& Control : *Recipe)
	{
		const FString Base = FString(TEXT("CTRL_expressions_")) + Control.Name;
		if (Control.bSided)
		{
			Out.FindOrAdd(Base) += Control.Value * Weight * RecipeGain;
			continue;
		}
		Out.FindOrAdd(Base + TEXT("L")) += Control.Value * Weight * RecipeGain;
		Out.FindOrAdd(Base + TEXT("R")) += Control.Value * Weight * RecipeGain;
	}
}

void FVIPExpressionLayer::Set(TMap<FString, float>&& InOffsets)
{
	FScopeLock Lock(&Mutex);
	Offsets = MoveTemp(InOffsets);
}

void FVIPExpressionLayer::SetRest(float InRest)
{
	FScopeLock Lock(&Mutex);
	Rest = FMath::Clamp(InRest, 0.0f, 1.0f);
}

void FVIPExpressionLayer::ApplyTo(TMap<FString, float>& AnimationData)
{
	FScopeLock Lock(&Mutex);
	if (Rest > 0)
	{
		const float Keep = 1.0f - Rest;
		for (TPair<FString, float>& Control : AnimationData)
		{
			Control.Value *= Keep;
		}
	}
	for (const TPair<FString, float>& Offset : Offsets)
	{
		if (float* Value = AnimationData.Find(Offset.Key))
		{
			*Value = FMath::Clamp(*Value + Offset.Value, 0.0f, 1.0f);
		}
	}
}
