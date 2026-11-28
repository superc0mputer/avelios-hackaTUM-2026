#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "VIPBackendLink.generated.h"

class IWebSocket;

/**
 * Connects the patient to the voice server (engine/voice_server.py, /ws/unreal) and passes what
 * arrives to UVIPSpeechSubsystem: the patient's voice as 16-bit PCM and the emotion for the face.
 *
 * Start with -VIPServer=ws://<host>:8787/ws/unreal. Without it the link stays off. If the server is
 * not there or goes away, it tries again every few seconds.
 *
 * Messages (JSON text):
 *   {"type":"audio","sample_rate":16000,"pcm_b64":"..."}   mono 16-bit little-endian PCM
 *   {"type":"emotion","emotion":"sad","intensity":0.6}     unknown emotions fall back to neutral
 *   {"type":"interrupt"}                                   student talked over the patient: stop speaking
 *
 * Optional, proposed for the voice server (#37, #45, #35, #38):
 *   {"type":"state","state":"thinking"}                    listening | thinking | idle
 *   {"type":"case","case":{...}}                           the teacher case JSON: patient, mood, personality
 *   "pain": 0-10, "discomfort": 0-1                        extra fields on an emotion message
 */
UCLASS()
class UVIPBackendLink : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:

	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

	/** Binary message to the voice server (JPEG frames from UVIPVideoStream); dropped while offline. */
	void SendBinary(const uint8* Data, int64 Size);

protected:

	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:

	void Connect();
	void ScheduleReconnect();
	void HandleMessage(const FString& Message);
	void StopVideo();

	FString Url;
	TSharedPtr<IWebSocket> Socket;

	// 0 while connected or connecting
	double ReconnectAt = 0;
};
