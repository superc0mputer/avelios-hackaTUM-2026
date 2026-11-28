#include "VIPVideoStream.h"

#include "VIPBackendLink.h"

#include "Async/Async.h"
#include "Engine/Engine.h"
#include "Engine/GameEngine.h"
#include "Engine/World.h"
#include "FrameGrabber.h"
#include "IImageWrapper.h"
#include "IImageWrapperModule.h"
#include "Modules/ModuleManager.h"
#include "Slate/SceneViewport.h"

DEFINE_LOG_CATEGORY_STATIC(LogVIPVideo, Log, All);

namespace
{
	// Small enough for a few testers over the internet: about 25-40 KB per frame
	const FIntPoint FrameSize(640, 360);
	constexpr double FramesPerSecond = 15.0;
	constexpr int32 JpegQuality = 70;

	struct FVIPFramePayload : IFramePayload
	{
	};

	bool IsUnfilled(const FColor& Pixel)
	{
		return Pixel.R == 255 && Pixel.G == 0 && Pixel.B == 255; // the grabber's clear colour
	}

	/** Width of the filled (non-magenta) part, measured along the top row. */
	int32 FilledWidth(const TArray<FColor>& Pixels, FIntPoint Size)
	{
		if (Pixels.Num() != Size.X * Size.Y || !IsUnfilled(Pixels.Last()))
		{
			return Size.X; // bottom-right is drawn: the whole buffer is filled
		}
		for (int32 X = Size.X - 1; X >= 0; --X)
		{
			if (!IsUnfilled(Pixels[X]))
			{
				return X + 1;
			}
		}
		return 0;
	}
}

bool UVIPVideoStream::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	return WorldType == EWorldType::Game;
}

TStatId UVIPVideoStream::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVIPVideoStream, STATGROUP_Tickables);
}

void UVIPVideoStream::SetViewers(int32 Count)
{
	Viewers = FMath::Max(0, Count);
	UE_LOG(LogVIPVideo, Display, TEXT("%d watching the patient video"), Viewers);
	if (Viewers == 0)
	{
		StopCapture();
	}
}

void UVIPVideoStream::StartCapture()
{
	UGameEngine* GameEngine = Cast<UGameEngine>(GEngine);
	if (!GameEngine || !GameEngine->SceneViewport.IsValid())
	{
		return; // no game window yet; try again next tick
	}
	Grabber = MakeShared<FFrameGrabber>(GameEngine->SceneViewport.ToSharedRef(), FrameSize * CaptureScale);
	Grabber->StartCapturingFrames();
	NextFrameAt = 0;
	UE_LOG(LogVIPVideo, Display, TEXT("Streaming the patient at %dx%d, %.0f fps (screen scale %d)"),
		FrameSize.X, FrameSize.Y, FramesPerSecond, CaptureScale);
}

void UVIPVideoStream::StopCapture()
{
	if (Grabber)
	{
		Grabber->StopCapturingFrames();
		Grabber->Shutdown();
		Grabber.Reset();
		UE_LOG(LogVIPVideo, Display, TEXT("Patient video stopped"));
	}
}

void UVIPVideoStream::Deinitialize()
{
	StopCapture();
	Super::Deinitialize();
}

void UVIPVideoStream::Tick(float DeltaTime)
{
	if (Viewers == 0)
	{
		return;
	}
	if (!Grabber)
	{
		StartCapture();
		if (!Grabber)
		{
			return;
		}
	}

	const double Now = FPlatformTime::Seconds();
	if (Now >= NextFrameAt)
	{
		Grabber->CaptureThisFrame(MakeShared<FVIPFramePayload>());
		NextFrameAt = Now + 1.0 / FramesPerSecond;
	}

	// Frames arrive a few render frames later; send the newest one
	TArray<FCapturedFrameData> Frames = Grabber->GetCapturedFrames();
	if (Frames.Num() > 0 && !bEncoding->load())
	{
		FCapturedFrameData& Newest = Frames.Last();
		const int32 Filled = FilledWidth(Newest.ColorBuffer, Newest.BufferSize);
		if (Filled > 0 && Filled < FrameSize.X * 9 / 10 && CaptureScale < 4)
		{
			// High-DPI screen: grab larger so the filled part is the frame size
			CaptureScale = FMath::Clamp(CaptureScale * FMath::RoundToInt(float(FrameSize.X) / Filled), CaptureScale + 1, 4);
			UE_LOG(LogVIPVideo, Display, TEXT("Picture filled %d of %d pixels; grabbing at scale %d"), Filled, Newest.BufferSize.X, CaptureScale);
			StopCapture(); // the next tick starts again with the larger buffer
			return;
		}
		if (Filled >= Newest.BufferSize.X && CaptureScale > 1)
		{
			// Fully drawn after all: cropping would zoom in, so grab at the plain size again
			CaptureScale = 1;
			StopCapture();
			return;
		}
		if (Newest.BufferSize == FrameSize)
		{
			EncodeAndSend(MoveTemp(Newest.ColorBuffer), FrameSize);
		}
		else if (Newest.BufferSize.X >= FrameSize.X && Newest.BufferSize.Y >= FrameSize.Y
			&& Newest.ColorBuffer.Num() == Newest.BufferSize.X * Newest.BufferSize.Y)
		{
			// Keep the top-left FrameSize, where the picture is
			TArray<FColor> Cropped;
			Cropped.SetNumUninitialized(FrameSize.X * FrameSize.Y);
			for (int32 Row = 0; Row < FrameSize.Y; ++Row)
			{
				FMemory::Memcpy(&Cropped[Row * FrameSize.X], &Newest.ColorBuffer[Row * Newest.BufferSize.X], FrameSize.X * sizeof(FColor));
			}
			EncodeAndSend(MoveTemp(Cropped), FrameSize);
		}
	}
}

void UVIPVideoStream::EncodeAndSend(TArray<FColor>&& Pixels, FIntPoint Size)
{
	if (Pixels.Num() != Size.X * Size.Y)
	{
		return;
	}
	bEncoding->store(true);
	TSharedRef<std::atomic<bool>> Busy = bEncoding;
	TWeakObjectPtr<UWorld> WeakWorld(GetWorld());

	Async(EAsyncExecution::ThreadPool, [Pixels = MoveTemp(Pixels), Size, Busy, WeakWorld]() mutable
	{
		IImageWrapperModule& Images = FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
		const TSharedPtr<IImageWrapper> Jpeg = Images.CreateImageWrapper(EImageFormat::JPEG);
		TArray64<uint8> Compressed;
		// FColor is stored as B, G, R, A
		if (Jpeg.IsValid() && Jpeg->SetRaw(Pixels.GetData(), Pixels.Num() * sizeof(FColor), Size.X, Size.Y, ERGBFormat::BGRA, 8))
		{
			Compressed = Jpeg->GetCompressed(JpegQuality);
		}
		AsyncTask(ENamedThreads::GameThread, [Compressed = MoveTemp(Compressed), Busy, WeakWorld]()
		{
			Busy->store(false);
			UWorld* World = WeakWorld.Get();
			UVIPBackendLink* Link = World ? World->GetSubsystem<UVIPBackendLink>() : nullptr;
			if (Link && Compressed.Num() > 0)
			{
				Link->SendBinary(Compressed.GetData(), Compressed.Num());
			}
		});
	});
}
