#include "VIPPatients.h"

#include "VIPBody.h"

#include "Components/SkeletalMeshComponent.h"
#include "EngineUtils.h"

DEFINE_LOG_CATEGORY_STATIC(LogVIPPatients, Log, All);

namespace
{
	const TCHAR* TablePath = TEXT("/Game/Patient/DT_Patients.DT_Patients");
	const FName PatientTag = TEXT("VIPPatient");
	const FName FollowHeadTag = TEXT("VIPFollowHead");
	const FName HeadBone = TEXT("head");

	constexpr int32 CharacterAgeTolerance = 15;

	/** Lower is better. A wrong gender always loses to a wrong age; a fitting character wins. */
	int32 Score(const FVIPPatientRow& Row, const FString& Gender, int32 Age, const FString& Character)
	{
		if (!Character.IsEmpty() && Row.Character.Equals(Character, ESearchCase::IgnoreCase)
			&& (Age < 0 || FMath::Abs(Row.Age - Age) <= CharacterAgeTolerance))
		{
			return -1;
		}
		int32 Result = 0;
		if (!Gender.IsEmpty() && !Row.Gender.Equals(Gender, ESearchCase::IgnoreCase))
		{
			Result += 1000;
		}
		if (Age >= 0)
		{
			Result += FMath::Abs(Row.Age - Age);
		}
		return Result;
	}

	bool BoneLocation(const AActor& Patient, const FName& Bone, FVector& Out)
	{
		TInlineComponentArray<USkeletalMeshComponent*> Meshes(&Patient);
		for (const USkeletalMeshComponent* Mesh : Meshes)
		{
			if (Mesh->GetBoneIndex(Bone) != INDEX_NONE)
			{
				Out = Mesh->GetBoneLocation(Bone);
				return true;
			}
		}
		return false;
	}

	bool HeadLocation(const AActor& Patient, FVector& Out)
	{
		return BoneLocation(Patient, HeadBone, Out);
	}

	/** Seated: lower the whole patient so the hip joints sit at the chair's height (legs bend in VIPBody). */
	void Seat(AActor& Patient)
	{
		FVector Hip;
		if (!VIPBody::IsSeated() || !BoneLocation(Patient, TEXT("thigh_l"), Hip))
		{
			return;
		}
		const float Drop = VIPPatients::SeatHipHeight - Hip.Z;
		if (FMath::Abs(Drop) > 0.5f)
		{
			Patient.AddActorWorldOffset(FVector(0, 0, Drop));
			UE_LOG(LogVIPPatients, Display, TEXT("Seated: patient moved %.1f cm"), Drop);
		}
	}
}

AActor* VIPPatients::Choose(UWorld& World, const FString& Gender, int32 Age, int32* OutAge, const FString& Character)
{
	AActor* Placed = nullptr;
	for (TActorIterator<AActor> It(&World); It; ++It)
	{
		if (It->ActorHasTag(PatientTag))
		{
			Placed = *It;
			break;
		}
	}

	const UDataTable* Table = LoadObject<UDataTable>(nullptr, TablePath);
	if (!Table)
	{
		UE_LOG(LogVIPPatients, Warning, TEXT("No patient table, keeping the placed patient"));
		return Placed;
	}

	const FVIPPatientRow* Best = nullptr;
	FName BestName;
	int32 BestScore = TNumericLimits<int32>::Max();
	Table->ForeachRow<FVIPPatientRow>(TEXT("VIPPatients"), [&](const FName& Name, const FVIPPatientRow& Row)
	{
		const int32 RowScore = Score(Row, Gender, Age, Character);
		if (RowScore < BestScore)
		{
			Best = &Row;
			BestName = Name;
			BestScore = RowScore;
		}
	});
	UClass* Class = Best ? Best->Blueprint.LoadSynchronous() : nullptr;
	if (!Class)
	{
		UE_LOG(LogVIPPatients, Warning, TEXT("No usable patient in the table, keeping the placed one"));
		return Placed;
	}

	FVector OldHead = FVector::ZeroVector;
	const bool bHadHead = Placed && HeadLocation(*Placed, OldHead);

	AActor* Patient = Placed;
	if (!Placed || Placed->GetClass() != Class)
	{
		const FTransform Where = Placed ? Placed->GetActorTransform() : FTransform::Identity;
		if (Placed)
		{
			Placed->Destroy();
		}
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		Patient = World.SpawnActor<AActor>(Class, Where, Params);
		Patient->Tags.Add(PatientTag);
	}
	if (Patient)
	{
		Seat(*Patient);
	}
	UE_LOG(LogVIPPatients, Display, TEXT("Patient %s (%s, %s, %d, %s) for gender '%s' age %d character '%s'"),
		*BestName.ToString(), *Best->Preset, *Best->Gender, Best->Age, *Best->Character, *Gender, Age, *Character);
	if (OutAge)
	{
		*OutAge = Best->Age;
	}

	// Patients differ in height and build: keep the camera and face lights at the same place relative
	// to the head (a heavier patient's head also sits further forward, which framed him too close)
	FVector NewHead = FVector::ZeroVector;
	if (bHadHead && HeadLocation(*Patient, NewHead) && !NewHead.Equals(OldHead, 0.5))
	{
		const FVector Delta = NewHead - OldHead;
		for (TActorIterator<AActor> It(&World); It; ++It)
		{
			if (It->ActorHasTag(FollowHeadTag))
			{
				It->AddActorWorldOffset(Delta);
			}
		}
		UE_LOG(LogVIPPatients, Display, TEXT("Camera and face lights follow the head by %s"), *Delta.ToString());
	}
	return Patient;
}
