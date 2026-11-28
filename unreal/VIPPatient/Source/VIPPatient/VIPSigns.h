#pragma once

#include "CoreMinimal.h"

class AActor;

/**
 * Visible signs of illness on skin and eyes (#34), from the case's presentation.visible_signs:
 *
 *   pale       less colour, slightly lighter skin
 *   jaundice   yellow skin and yellow sclera
 *   cyanosis   dusky, bluish-grey skin (the skin material has no separate lip colour)
 *   flushed    redder, more saturated skin
 *   sweaty     glossy skin (lower roughness, more specular)
 *   red_eyes   bloodshot sclera
 *   tired      slightly bloodshot eyes, greyer skin
 *
 * Works on the MetaHuman's own material parameters ("... Post-Bake" on skin, "Sclera Color Multiply"
 * on the eyes) through dynamic material instances, so nothing needs rebuilding. Each call starts
 * from the original material values, so signs can be changed or removed at any time.
 */
namespace VIPSigns
{
	void Apply(AActor& Patient, const TArray<FString>& Signs, float Strength = 1.0f);

	/** True for the names above. */
	bool IsKnown(const FString& Sign);
}
