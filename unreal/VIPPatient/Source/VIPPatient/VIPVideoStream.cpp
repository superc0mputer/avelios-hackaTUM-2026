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

	/** The drawn part of a grabbed frame, scaled to FrameSize (each output pixel averages 4 samples). */
	TArray<FColor> ScaleDown(const TArray<FColor>& Pixels, FIntPoint Size)
	{
		const int32 SrcW = FMath::Max(1, FilledWidth(Pixels, Size));
		const int32 SrcH = FMath::Clamp(SrcW * Size.Y / Size.X, 1, Size.Y);
		TArray<FColor> Out;
		Out.SetNumUninitialized(FrameSize.X * FrameSize.Y);
		for (int32 Y = 0; Y < FrameSize.Y; ++Y)
		{
			const int32 Y0 = Y * SrcH / FrameSize.Y;
			const int32 Y1 = FMath::Max(Y0, (Y + 1) * SrcH / FrameSize.Y - 1);
			for (int32 X = 0; X < FrameSize.X; ++X)
			{
				const int32 X0 = X * SrcW / FrameSize.X;
				const int32 X1 = FMath::Max(X0, (X + 1) * SrcW / FrameSize.X - 1);
				const FColor& A = Pixels[Y0 * Size.X + X0];
				const FColor& B = Pixels[Y0 * Size.X + X1];
				const FColor& C = Pixels[Y1 * Size.X + X0];
				const FColor& D = Pixels[Y1 * Size.X + X1];
				Out[Y * FrameSize.X + X] = FColor(
					(A.R + B.R + C.R + D.R) / 4, (A.G + B.G + C.G + D.G) / 4, (A.B + B.B + C.B + D.B) / 4, 255);
			}
		}
		return Out;
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
	// Grab at the window's own size: smaller buffers come back only partly drawn on Retina
	// screens. EncodeAndSend scales the picture down to FrameSize.
	const FIntPoint WindowSize = GameEngine->SceneViewport->GetSizeXY();
	const FIntPoint GrabSize(FMath::Max(WindowSize.X, FrameSize.X), FMath::Max(WindowSize.Y, FrameSize.Y));
	Grabber = MakeShared<FFrameGrabber>(GameEngine->SceneViewport.ToSharedRef(), GrabSize);
	Grabber->StartCapturingFrames();
	NextFrameAt = 0;
	UE_LOG(LogVIPVideo, Display, TEXT("Streaming the patient: grabbing %dx%d, sending %dx%d at %.0f fps"),
		GrabSize.X, GrabSize.Y, FrameSize.X, FrameSize.Y, FramesPerSecond);
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
		EncodeAndSend(MoveTemp(Newest.ColorBuffer), Newest.BufferSize);
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
		const TArray<FColor> Small = ScaleDown(Pixels, Size);
		IImageWrapperModule& Images = FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
		const TSharedPtr<IImageWrapper> Jpeg = Images.CreateImageWrapper(EImageFormat::JPEG);
		TArray64<uint8> Compressed;
		// FColor is stored as B, G, R, A
		if (Jpeg.IsValid() && Jpeg->SetRaw(Small.GetData(), Small.Num() * sizeof(FColor), FrameSize.X, FrameSize.Y, ERGBFormat::BGRA, 8))
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
