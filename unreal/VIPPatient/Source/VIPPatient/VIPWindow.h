#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "VIPWindow.generated.h"

/**
 * The patient window is only watched, never played: keep the mouse cursor visible and free,
 * so the teacher page next to it stays usable. Without this, a click into the window captures
 * the mouse like a game does.
 */
UCLASS()
class UVIPWindow : public UWorldSubsystem
{
	GENERATED_BODY()

public:

	virtual void OnWorldBeginPlay(UWorld& InWorld) override;

protected:

	// Standalone game only; inside the editor, Play-In-Editor keeps its own mouse handling
	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;
};
