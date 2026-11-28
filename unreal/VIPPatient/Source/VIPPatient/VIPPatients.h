#pragma once

#include "CoreMinimal.h"
#include "Engine/DataTable.h"
#include "VIPPatients.generated.h"

/** One patient the app can show. Rows come from Scripts/patients.json via build_scene.py. */
USTRUCT(BlueprintType)
struct FVIPPatientRow : public FTableRowBase
{
	GENERATED_BODY()

	/** Epic preset the MetaHuman was built from. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "VIP")
	FString Preset;

	/** "female" or "male", as in the case JSON. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "VIP")
	FString Gender;

	/** Age the face looks; used to find the closest patient for a case. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "VIP")
	int32 Age = 0;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "VIP")
	TSoftClassPtr<AActor> Blueprint;
};

namespace VIPPatients
{
	/**
	 * Puts the patient that best fits age and gender in the level, replacing the one placed there,
	 * and lifts the camera and face lights to its head. Empty gender or Age < 0 means "any".
	 * Returns the patient actor, or the placed one if nothing better is found.
	 */
	AActor* Choose(UWorld& World, const FString& Gender, int32 Age);
}
