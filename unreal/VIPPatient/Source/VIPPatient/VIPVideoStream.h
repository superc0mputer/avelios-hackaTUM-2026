#pragma once

#include "CoreMinimal.h"
#include <atomic>
#include "Subsystems/WorldSubsystem.h"
#include "VIPVideoStream.generated.h"

class FFrameGrabber;

/**
 * Live picture of the patient for testers who are not at the demo computer: grabs the game
 * window (scaled down), encodes JPEGs in the background and sends them over the voice-server
 * link (UVIPBackendLink), which passes them on to every browser on /ws/video.
 *
 * Only runs while somebody watches: the voice server sends {"type":"viewers","count":n}.
 */
UCLASS()
class UVIPVideoStream : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:

	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

	/** Number of browsers watching; 0 stops the capture. */
	void SetViewers(int32 Count);

protected:

	// The standalone patient window only; the editor has no single game window to grab
	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:

	void StartCapture();
	void StopCapture();
	void EncodeAndSend(TArray<FColor>&& Pixels, FIntPoint Size);

	static constexpr int32 MaxInFlight = 3;

	TSharedPtr<FFrameGrabber> Grabber;

	// Set when the capture starts (window size and -VIPVideo* options)
	FIntPoint FrameSize = FIntPoint(1280, 720);
	int32 JpegQuality = 80;
	int32 FramesPerSecond = 15;

	int32 Viewers = 0;
	double NextFrameAt = 0;

	// Up to MaxInFlight JPEGs are encoded in parallel; one that finishes after a newer frame was
	// sent is dropped, so the picture never jumps back
	TSharedRef<std::atomic<int32>> InFlight = MakeShared<std::atomic<int32>>(0);
	int64 NextSequence = 0;
	TSharedRef<std::atomic<int64>> LastSent = MakeShared<std::atomic<int64>>(-1);
};
