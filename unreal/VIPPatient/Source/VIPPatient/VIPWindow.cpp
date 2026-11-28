#include "VIPWindow.h"

#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"

bool UVIPWindow::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	return WorldType == EWorldType::Game;
}

void UVIPWindow::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);

	if (APlayerController* Player = InWorld.GetFirstPlayerController())
	{
		Player->bShowMouseCursor = true;
		FInputModeGameAndUI Mode;
		Mode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
		Mode.SetHideCursorDuringCapture(false);
		Player->SetInputMode(Mode);
	}
	// After SetInputMode, which would otherwise capture the mouse while a button is held
	if (UGameViewportClient* Viewport = InWorld.GetGameViewport())
	{
		Viewport->SetMouseCaptureMode(EMouseCaptureMode::NoCapture);
		Viewport->SetMouseLockMode(EMouseLockMode::DoNotLock);
		Viewport->SetHideCursorDuringCapture(false);
	}
	if (FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().ReleaseAllPointerCapture();
	}
}
