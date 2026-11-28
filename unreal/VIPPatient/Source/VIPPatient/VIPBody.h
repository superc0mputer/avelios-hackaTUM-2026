#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimInstance.h"
#include "VIPBody.generated.h"

class UAnimSequence;

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
