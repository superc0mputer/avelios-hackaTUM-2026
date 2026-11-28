#include "VIPPatients.h"

#include "Components/SkeletalMeshComponent.h"
#include "EngineUtils.h"

DEFINE_LOG_CATEGORY_STATIC(LogVIPPatients, Log, All);

namespace
{
	const TCHAR* TablePath = TEXT("/Game/Patient/DT_Patients.DT_Patients");
	const FName PatientTag = TEXT("VIPPatient");
	const FName FollowHeadTag = TEXT("VIPFollowHead");
	const FName HeadBone = TEXT("head");

	/** Lower is better. A wrong gender always loses to a wrong age. */
	int32 Score(const FVIPPatientRow& Row, const FString& Gender, int32 Age)
	{
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

	bool HeadHeight(const AActor& Patient, float& OutZ)
	{
		TInlineComponentArray<USkeletalMeshComponent*> Meshes(&Patient);
		for (const USkeletalMeshComponent* Mesh : Meshes)
		{
			if (Mesh->GetBoneIndex(HeadBone) != INDEX_NONE)
			{
				OutZ = Mesh->GetBoneLocation(HeadBone).Z;
				return true;
			}
		}
		return false;
	}
}

AActor* VIPPatients::Choose(UWorld& World, const FString& Gender, int32 Age)
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
		const int32 RowScore = Score(Row, Gender, Age);
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

	float OldHead = 0;
	const bool bHadHead = Placed && HeadHeight(*Placed, OldHead);

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
	UE_LOG(LogVIPPatients, Display, TEXT("Patient %s (%s, %s, %d) for gender '%s' age %d"),
		*BestName.ToString(), *Best->Preset, *Best->Gender, Best->Age, *Gender, Age);

	// Patients differ in height: keep the camera and face lights at the same place relative to the head
	float NewHead = 0;
	if (bHadHead && HeadHeight(*Patient, NewHead) && !FMath::IsNearlyEqual(NewHead, OldHead, 0.5f))
	{
		for (TActorIterator<AActor> It(&World); It; ++It)
		{
			if (It->ActorHasTag(FollowHeadTag))
			{
				It->AddActorWorldOffset(FVector(0, 0, NewHead - OldHead));
			}
		}
	}
	return Patient;
}
