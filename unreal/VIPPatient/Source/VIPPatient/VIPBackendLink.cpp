#include "VIPBackendLink.h"

#include "VIPCase.h"
#include "VIPSpeechSubsystem.h"

#include "Dom/JsonObject.h"
#include "IWebSocket.h"
#include "Misc/Base64.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "WebSocketsModule.h"

DEFINE_LOG_CATEGORY_STATIC(LogVIPLink, Log, All);

namespace
{
	constexpr double ReconnectSeconds = 3.0;

	// ElevenLabs agents send 16 kHz PCM unless configured otherwise
	constexpr int32 DefaultSampleRate = 16000;
}

bool UVIPBackendLink::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

TStatId UVIPBackendLink::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVIPBackendLink, STATGROUP_Tickables);
}

void UVIPBackendLink::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);

	if (!FParse::Value(FCommandLine::Get(), TEXT("VIPServer="), Url) || Url.IsEmpty())
	{
		UE_LOG(LogVIPLink, Display, TEXT("No -VIPServer= given, the patient is not connected to the voice server"));
		return;
	}
	Connect();
}

void UVIPBackendLink::Connect()
{
	FWebSocketsModule& WebSockets = FModuleManager::LoadModuleChecked<FWebSocketsModule>(TEXT("WebSockets"));
	Socket = WebSockets.CreateWebSocket(Url);
	ReconnectAt = 0;

	TWeakObjectPtr<UVIPBackendLink> WeakThis(this);
	Socket->OnConnected().AddLambda([WeakThis]()
	{
		if (WeakThis.IsValid())
		{
			UE_LOG(LogVIPLink, Display, TEXT("Connected to %s"), *WeakThis->Url);
		}
	});
	Socket->OnConnectionError().AddLambda([WeakThis](const FString& Error)
	{
		if (WeakThis.IsValid())
		{
			UE_LOG(LogVIPLink, Warning, TEXT("Cannot reach %s: %s"), *WeakThis->Url, *Error);
			WeakThis->ScheduleReconnect();
		}
	});
	Socket->OnClosed().AddLambda([WeakThis](int32 StatusCode, const FString& Reason, bool bWasClean)
	{
		if (WeakThis.IsValid())
		{
			UE_LOG(LogVIPLink, Warning, TEXT("Voice server closed the link (%d %s)"), StatusCode, *Reason);
			WeakThis->ScheduleReconnect();
		}
	});
	Socket->OnMessage().AddLambda([WeakThis](const FString& Message)
	{
		if (WeakThis.IsValid())
		{
			WeakThis->HandleMessage(Message);
		}
	});

	UE_LOG(LogVIPLink, Display, TEXT("Connecting to %s"), *Url);
	Socket->Connect();
}

void UVIPBackendLink::ScheduleReconnect()
{
	if (ReconnectAt == 0)
	{
		ReconnectAt = FPlatformTime::Seconds() + ReconnectSeconds;
	}
}

void UVIPBackendLink::Tick(float DeltaTime)
{
	if (ReconnectAt > 0 && FPlatformTime::Seconds() >= ReconnectAt)
	{
		Connect();
	}
}

void UVIPBackendLink::Deinitialize()
{
	if (Socket.IsValid())
	{
		Socket->OnConnected().Clear();
		Socket->OnConnectionError().Clear();
		Socket->OnClosed().Clear();
		Socket->OnMessage().Clear();
		Socket->Close();
		Socket.Reset();
	}
	Super::Deinitialize();
}

void UVIPBackendLink::HandleMessage(const FString& Message)
{
	// The WebSockets module calls back on the game thread; the speech subsystem expects that
	check(IsInGameThread());

	TSharedPtr<FJsonObject> Json;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Message);
	if (!FJsonSerializer::Deserialize(Reader, Json) || !Json.IsValid())
	{
		UE_LOG(LogVIPLink, Warning, TEXT("Ignoring a message that is not JSON"));
		return;
	}

	UWorld* World = GetWorld();
	UVIPSpeechSubsystem* Speech = World ? World->GetSubsystem<UVIPSpeechSubsystem>() : nullptr;
	if (!Speech)
	{
		return;
	}

	FString Type;
	Json->TryGetStringField(TEXT("type"), Type);

	if (Type == TEXT("audio"))
	{
		FString Base64;
		int32 SampleRate = DefaultSampleRate;
		Json->TryGetStringField(TEXT("pcm_b64"), Base64);
		Json->TryGetNumberField(TEXT("sample_rate"), SampleRate);

		TArray<uint8> Bytes;
		if (!FBase64::Decode(Base64, Bytes) || Bytes.Num() < static_cast<int32>(sizeof(int16)) || SampleRate <= 0)
		{
			return;
		}
		// Little-endian 16-bit PCM, as on every platform we build for
		TArray<int16> Samples;
		Samples.SetNumUninitialized(Bytes.Num() / sizeof(int16));
		FMemory::Memcpy(Samples.GetData(), Bytes.GetData(), Samples.Num() * sizeof(int16));
		Speech->Speak(Samples, SampleRate);
	}
	else if (Type == TEXT("emotion"))
	{
		FString Emotion = TEXT("neutral");
		double Intensity = 1.0;
		Json->TryGetStringField(TEXT("emotion"), Emotion);
		Json->TryGetNumberField(TEXT("intensity"), Intensity);
		Speech->SetEmotion(Emotion, static_cast<float>(FMath::Clamp(Intensity, 0.0, 2.0)));
		UE_LOG(LogVIPLink, Display, TEXT("Emotion %s %.2f"), *Emotion, Intensity);

		// Optional per turn (#35, #38): pain 0-10 and discomfort 0-1; the case's values are the floor
		double Value = 0;
		if (Json->TryGetNumberField(TEXT("pain"), Value))
		{
			Speech->SetPain(static_cast<float>(Value));
		}
		if (Json->TryGetNumberField(TEXT("discomfort"), Value))
		{
			Speech->SetDiscomfort(static_cast<float>(Value));
		}
	}
	else if (Type == TEXT("interrupt"))
	{
		Speech->StopSpeaking();
		UE_LOG(LogVIPLink, Display, TEXT("Student interrupted the patient"));
	}
	else if (Type == TEXT("state"))
	{
		// {"type":"state","state":"listening|thinking|idle"}: the student talks, or the answer is pending (#37)
		FString State;
		Json->TryGetStringField(TEXT("state"), State);
		Speech->SetAttention(State);
	}
	else if (Type == TEXT("case"))
	{
		// {"type":"case","case":{...teacher case JSON...}}: patient, mood, personality, presentation (#45)
		FVIPCase Case;
		if (FVIPCase::FromJson(Json, Case))
		{
			Speech->ApplyCase(Case);
		}
	}
}
