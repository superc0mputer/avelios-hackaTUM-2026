#include "VIPVideoStream.h"

#include "VIPBackendLink.h"

#include "Async/Async.h"
#include "Engine/Engine.h"
#include "Engine/GameEngine.h"
#include "Engine/World.h"
#include "FrameGrabber.h"
#include "IImageWrapper.h"
#include "IImageWrapperModule.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Modules/ModuleManager.h"
#include "Slate/SceneViewport.h"

DEFINE_LOG_CATEGORY_STATIC(LogVIPVideo, Log, All);

namespace
{
	// Defaults: the window's own size (1280x720 from build.sh), JPEG quality 80, 15 fps: about
	// 60-90 KB per frame, ~1 MB/s per viewer. Change with -VIPVideoWidth=, -VIPVideoQuality=,
	// -VIPVideoFps= (height follows the window's aspect ratio).
	int32 OptionOr(const TCHAR* Name, int32 Default)
	{
		int32 Value = Default;
		FParse::Value(FCommandLine::Get(), Name, Value);
		return Value;
	}

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

	/** The drawn part of a grabbed frame at FrameSize (each output pixel averages 4 samples). */
	TArray<FColor> ScaleDown(TArray<FColor>&& Pixels, FIntPoint Size, FIntPoint FrameSize)
	{
		const int32 SrcW = FMath::Max(1, FilledWidth(Pixels, Size));
		const int32 SrcH = FMath::Clamp(SrcW * Size.Y / Size.X, 1, Size.Y);
		if (SrcW == Size.X && Size == FrameSize)
		{
			return MoveTemp(Pixels); // already the right size: no resampling, full sharpness
		}
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
	if (WindowSize.X <= 0 || WindowSize.Y <= 0)
	{
		return;
	}
	const FIntPoint GrabSize = WindowSize;
	const int32 Width = FMath::Clamp(OptionOr(TEXT("VIPVideoWidth="), WindowSize.X), 160, WindowSize.X);
	FrameSize = FIntPoint(Width, FMath::Max(90, Width * WindowSize.Y / WindowSize.X) & ~1);
	JpegQuality = FMath::Clamp(OptionOr(TEXT("VIPVideoQuality="), 80), 30, 95);
	FramesPerSecond = FMath::Clamp(OptionOr(TEXT("VIPVideoFps="), 15), 2, 30);
	Grabber = MakeShared<FFrameGrabber>(GameEngine->SceneViewport.ToSharedRef(), GrabSize);
	Grabber->StartCapturingFrames();
	NextFrameAt = 0;
	UE_LOG(LogVIPVideo, Display, TEXT("Streaming the patient: grabbing %dx%d, sending %dx%d, JPEG %d, %d fps"),
		GrabSize.X, GrabSize.Y, FrameSize.X, FrameSize.Y, JpegQuality, FramesPerSecond);
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

	const FIntPoint OutSize = FrameSize;
	const int32 Quality = JpegQuality;
	Async(EAsyncExecution::ThreadPool, [Pixels = MoveTemp(Pixels), Size, OutSize, Quality, Busy, WeakWorld]() mutable
	{
		const TArray<FColor> Small = ScaleDown(MoveTemp(Pixels), Size, OutSize);
		IImageWrapperModule& Images = FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
		const TSharedPtr<IImageWrapper> Jpeg = Images.CreateImageWrapper(EImageFormat::JPEG);
		TArray64<uint8> Compressed;
		// FColor is stored as B, G, R, A
		if (Jpeg.IsValid() && Jpeg->SetRaw(Small.GetData(), Small.Num() * sizeof(FColor), OutSize.X, OutSize.Y, ERGBFormat::BGRA, 8))
		{
			Compressed = Jpeg->GetCompressed(Quality);
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
