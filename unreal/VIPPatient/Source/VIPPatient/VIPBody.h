#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimInstance.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "VIPBody.generated.h"

class UAnimSequence;

namespace VIPBody
{
	/**
	 * The seated pose on top of the idle: "bone:axis:degrees" in each bone's local space (axes found
	 * with -VIPPose and side views, -VIPTurn=90): local Z bends hip and knee on both sides.
	 */
	inline const TCHAR* SeatPose = TEXT("thigh_l:z:90,thigh_r:z:90,calf_l:z:-90,calf_r:z:-90");

	/** -VIPStand keeps the old standing patient. */
	inline bool IsSeated() { return !FParse::Param(FCommandLine::Get(), TEXT("VIPStand")); }
}

/**
 * Body animation without an Animation Blueprint: plays an idle loop and adds breathing on top, at
 * the rate and depth the case asks for (#36). Fast, shallow breathing or laboured breathing with
 * the shoulders is a sign students should notice.
 */
UCLASS(Transient, NotBlueprintable)
class UVIPBodyAnimInstance : public UAnimInstance
{
	GENERATED_BODY()

public:

	/** The loop to play; none keeps the rest pose. */
	UPROPERTY(Transient)
	TObjectPtr<UAnimSequence> Idle;

	/** Breaths per minute (adults at rest about 12 to 16). */
	float BreathsPerMinute = 14;

	/** 1 = normal; below 1 shallow, above 1 deep. */
	float Depth = 1;

	/** 0 to 1: how much the shoulders lift with each breath (laboured breathing uses them). */
	float ShoulderUse = 0.2f;

protected:

	virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override;
	virtual void DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy) override;
};
