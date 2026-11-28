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

	TSharedPtr<FFrameGrabber> Grabber;

	// On Retina screens the grabber fills only the top-left 1/Scale of its buffer (the rest stays
	// magenta). Measured from the frames; the grabber then gets a buffer Scale times larger and we
	// keep the filled part
	int32 CaptureScale = 1;
	int32 Viewers = 0;
	double NextFrameAt = 0;

	// One JPEG in flight at a time; frames that arrive meanwhile are skipped
	TSharedRef<std::atomic<bool>> bEncoding = MakeShared<std::atomic<bool>>(false);
};
