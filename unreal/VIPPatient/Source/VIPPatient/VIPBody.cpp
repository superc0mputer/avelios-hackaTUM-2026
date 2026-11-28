#include "VIPBody.h"

#include "Animation/AnimInstanceProxy.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimNodeBase.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

namespace
{
	// Shoulder lift in degrees at depth 1 (laboured breathing reaches about 4)
	constexpr float ShoulderDegrees = 1.5f;

	/** Breathing is not a sine: a quicker breath in, a pause, a slower breath out. 0 to 1. */
	float BreathShape(float Phase)
	{
		constexpr float In = 0.4f;
		constexpr float Hold = 0.08f;
		if (Phase < In)
		{
			return 0.5f - 0.5f * FMath::Cos(PI * Phase / In);
		}
		if (Phase < In + Hold)
		{
			return 1.0f;
		}
		return 0.5f + 0.5f * FMath::Cos(PI * (Phase - In - Hold) / (1.0f - In - Hold));
	}

	struct FVIPBodyProxy : public FAnimInstanceProxy
	{
		explicit FVIPBodyProxy(UAnimInstance* InInstance) : FAnimInstanceProxy(InInstance) {}

		TObjectPtr<UAnimSequence> Idle;
		float Time = 0;
		float Phase = 0;
		float Rate = 14;
		float Depth = 1;
		float Shoulders = 0.2f;
		float Smoothed[3] = {14, 1, 0.2f};

		// Seated (doctor's office): legs bent at hip and knee, the rest of the body as before
		bool bSeated = true;
		struct FBoneTurn { FName Bone; FVector Axis; float Degrees; };
		TArray<FBoneTurn> SeatPose;
		// Testing: -VIPPose=thigh_l:z:70,calf_l:z:-80 adds rotations (to find axes and angles)
		TArray<FBoneTurn> TestPose;

		static TArray<FBoneTurn> ParsePose(const FString& Text)
		{
			TArray<FBoneTurn> Result;
			TArray<FString> Items;
			Text.ParseIntoArray(Items, TEXT(","));
			for (const FString& Item : Items)
			{
				TArray<FString> Parts;
				Item.ParseIntoArray(Parts, TEXT(":"));
				if (Parts.Num() != 3)
				{
					continue;
				}
				const FString AxisName = Parts[1].ToLower();
				const FVector Axis = AxisName == TEXT("x") ? FVector::XAxisVector : AxisName == TEXT("y") ? FVector::YAxisVector : FVector::ZAxisVector;
				Result.Add({FName(*Parts[0]), Axis, FCString::Atof(*Parts[2])});
			}
			return Result;
		}

		// Testing: exaggerated rotation about one axis, to find each bone's axes
		int32 TestAxis = -1;
		float TestHold = -1; // 0 = breathed out, 1 = breathed in, for comparing screenshots

		virtual void PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds) override
		{
			FAnimInstanceProxy::PreUpdate(InAnimInstance, DeltaSeconds);
			const UVIPBodyAnimInstance* Body = CastChecked<UVIPBodyAnimInstance>(InAnimInstance);
			Idle = Body->Idle;
			Rate = Body->BreathsPerMinute;
			Depth = Body->Depth;
			Shoulders = Body->ShoulderUse;
		}

		virtual void Update(float DeltaSeconds) override
		{
			if (Idle)
			{
				Time = FMath::Fmod(Time + DeltaSeconds, FMath::Max(Idle->GetPlayLength(), 0.01f));
			}
			// Changes in rate and depth ease in over a few seconds, like a real patient's
			const float Ease = 1.0f - FMath::Exp(-DeltaSeconds / 3.0f);
			Smoothed[0] += (Rate - Smoothed[0]) * Ease;
			Smoothed[1] += (Depth - Smoothed[1]) * Ease;
			Smoothed[2] += (Shoulders - Smoothed[2]) * Ease;
			Phase = FMath::Fmod(Phase + DeltaSeconds * Smoothed[0] / 60.0f, 1.0f);
		}

		void Rotate(FPoseContext& Output, const TCHAR* Bone, const FVector& Axis, float Degrees) const
		{
			const FBoneContainer& Bones = Output.Pose.GetBoneContainer();
			const int32 MeshIndex = Bones.GetPoseBoneIndexForBoneName(FName(Bone));
			if (MeshIndex == INDEX_NONE)
			{
				return;
			}
			const FCompactPoseBoneIndex Index = Bones.MakeCompactPoseIndex(FMeshPoseBoneIndex(MeshIndex));
			if (Index.IsValid())
			{
				FTransform& Local = Output.Pose[Index];
				Local.SetRotation(Local.GetRotation() * FQuat(Axis, FMath::DegreesToRadians(Degrees)));
			}
		}

		virtual bool Evaluate(FPoseContext& Output) override
		{
			if (Idle)
			{
				FAnimationPoseData Pose(Output);
				Idle->GetAnimationPose(Pose, FAnimExtractContext(static_cast<double>(Time), false, {}, true));

				// The face mesh does not follow the body's pelvis, spine or neck here, and its neck is
				// modelled for the rest pose. Any other pose of those bones (even a still frame of the
				// idle) moves the collar against the neck, so they stay at the rest pose; the arms and
				// shoulders keep the idle's movement
				const FBoneContainer& Bones = Output.Pose.GetBoneContainer();
				for (const TCHAR* Bone : {TEXT("root"), TEXT("pelvis"), TEXT("spine_01"), TEXT("spine_02"), TEXT("spine_03"),
					TEXT("spine_04"), TEXT("spine_05"), TEXT("neck_01"), TEXT("neck_02"), TEXT("head")})
				{
					const int32 MeshIndex = Bones.GetPoseBoneIndexForBoneName(FName(Bone));
					if (MeshIndex == INDEX_NONE)
					{
						continue;
					}
					const FCompactPoseBoneIndex Index = Bones.MakeCompactPoseIndex(FMeshPoseBoneIndex(MeshIndex));
					if (Index.IsValid())
					{
						Output.Pose[Index] = Output.Pose.GetRefPose(Index);
					}
				}
			}
			else
			{
				Output.ResetToRefPose();
			}

			if (TestAxis >= 0)
			{
				const FVector Axis = TestAxis == 0 ? FVector::XAxisVector : TestAxis == 1 ? FVector::YAxisVector : FVector::ZAxisVector;
				Rotate(Output, TEXT("spine_04"), Axis, 15);
				Rotate(Output, TEXT("clavicle_l"), Axis, 15);
				Rotate(Output, TEXT("clavicle_r"), Axis, 15);
				return true;
			}

			if (bSeated)
			{
				for (const FBoneTurn& Turn : SeatPose)
				{
					Rotate(Output, *Turn.Bone.ToString(), Turn.Axis, Turn.Degrees);
				}
			}
			for (const FBoneTurn& Turn : TestPose)
			{
				Rotate(Output, *Turn.Bone.ToString(), Turn.Axis, Turn.Degrees);
			}

			const float Breath = (TestHold >= 0 ? TestHold : BreathShape(Phase)) * Smoothed[1];
			// Only the shoulders move: bending the spine opens a gap between collar and neck, because
			// the face mesh's neck does not follow changes to the body's spine
			const float Shoulder = ShoulderDegrees * Breath * (0.6f + Smoothed[2]);
			// Local Z lifts both clavicles alike (found with -VIPBoneTest; X twists, Y swings them back)
			Rotate(Output, TEXT("clavicle_l"), FVector::ZAxisVector, Shoulder);
			Rotate(Output, TEXT("clavicle_r"), FVector::ZAxisVector, Shoulder);
			return true;
		}
	};
}

FAnimInstanceProxy* UVIPBodyAnimInstance::CreateAnimInstanceProxy()
{
	FVIPBodyProxy* Proxy = new FVIPBodyProxy(this);
	FParse::Value(FCommandLine::Get(), TEXT("VIPBoneTest="), Proxy->TestAxis);
	FParse::Value(FCommandLine::Get(), TEXT("VIPBreathHold="), Proxy->TestHold);
	Proxy->bSeated = !FParse::Param(FCommandLine::Get(), TEXT("VIPStand"));
	Proxy->SeatPose = FVIPBodyProxy::ParsePose(VIPBody::SeatPose);
	FString Pose;
	if (FParse::Value(FCommandLine::Get(), TEXT("VIPPose="), Pose, false))
	{
		Proxy->TestPose = FVIPBodyProxy::ParsePose(Pose);
	}
	return Proxy;
}

void UVIPBodyAnimInstance::DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy)
{
	delete static_cast<FVIPBodyProxy*>(InProxy);
}
