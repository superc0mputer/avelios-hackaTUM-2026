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
	Grabber = MakeShared<FFrameGrabber>(GameEngine->SceneViewport.ToSharedRef(), FrameSize);
	Grabber->StartCapturingFrames();
	NextFrameAt = 0;
	UE_LOG(LogVIPVideo, Display, TEXT("Streaming the patient at %dx%d, %.0f fps"), FrameSize.X, FrameSize.Y, FramesPerSecond);
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
