#include "VIPSigns.h"

#include "Components/SkeletalMeshComponent.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"

DEFINE_LOG_CATEGORY_STATIC(LogVIPSigns, Log, All);

namespace
{
	const FName SkinHue = TEXT("Basecolor Global Hue Post-Bake");
	const FName SkinValue = TEXT("Basecolor Global Value Post-Bake");
	const FName SkinSaturation = TEXT("Basecolor Global Saturation Post-Bake");
	const FName SkinTint = TEXT("Basecolor Global Multiply Post-Bake");
	const FName SkinRoughness = TEXT("Roughness Global Multiply Post-Bake");
	const FName SkinSpecular = TEXT("Specular Global Multiply Post-Bake");
	const FName ScleraTint = TEXT("Sclera Color Multiply");
	const FName ScleraVeins = TEXT("Sclera Irritation Veins Opacity");

	/** What all signs together do, as multipliers and additions on the original values. */
	struct FLook
	{
		float Saturation = 1;
		float Value = 1;
		FLinearColor Tint = FLinearColor::White;
		float Roughness = 1;
		float Specular = 1;
		FLinearColor Sclera = FLinearColor::White;
		float Veins = 0; // added, 0 to 1
	};

	void Add(FLook& Look, const FString& Sign, float S)
	{
		auto Mix = [S](const FLinearColor& Full) { return FMath::Lerp(FLinearColor::White, Full, S); };
		if (Sign == TEXT("pale"))
		{
			Look.Saturation *= FMath::Lerp(1.0f, 0.55f, S);
			Look.Value *= FMath::Lerp(1.0f, 1.08f, S);
		}
		else if (Sign == TEXT("jaundice"))
		{
			Look.Tint *= Mix(FLinearColor(1.02f, 0.98f, 0.74f));
			Look.Sclera *= Mix(FLinearColor(1.0f, 0.82f, 0.25f)); // the sclera is small on screen: strong
		}
		else if (Sign == TEXT("cyanosis"))
		{
			Look.Tint *= Mix(FLinearColor(0.82f, 0.88f, 1.06f));
			Look.Saturation *= FMath::Lerp(1.0f, 0.7f, S);
		}
		else if (Sign == TEXT("flushed"))
		{
			Look.Tint *= Mix(FLinearColor(1.1f, 0.88f, 0.86f));
			Look.Saturation *= FMath::Lerp(1.0f, 1.15f, S);
		}
		else if (Sign == TEXT("sweaty"))
		{
			Look.Roughness *= FMath::Lerp(1.0f, 0.3f, S);
			Look.Specular *= FMath::Lerp(1.0f, 2.2f, S);
		}
		else if (Sign == TEXT("red_eyes"))
		{
			Look.Veins += 1.0f * S;
			Look.Sclera *= Mix(FLinearColor(1.0f, 0.68f, 0.64f));
		}
		else if (Sign == TEXT("tired"))
		{
			Look.Veins += 0.6f * S;
			Look.Sclera *= Mix(FLinearColor(1.0f, 0.88f, 0.86f));
			Look.Saturation *= FMath::Lerp(1.0f, 0.85f, S);
		}
	}

	bool HasScalar(UMaterialInterface* Material, const FName& Name, float& Out)
	{
		return Material && Material->GetScalarParameterValue(FHashedMaterialParameterInfo(Name), Out);
	}

	bool HasVector(UMaterialInterface* Material, const FName& Name, FLinearColor& Out)
	{
		return Material && Material->GetVectorParameterValue(FHashedMaterialParameterInfo(Name), Out);
	}
}

bool VIPSigns::IsKnown(const FString& Sign)
{
	static const TSet<FString> Known = {TEXT("pale"), TEXT("jaundice"), TEXT("cyanosis"), TEXT("flushed"),
		TEXT("sweaty"), TEXT("red_eyes"), TEXT("tired")};
	return Known.Contains(Sign.ToLower());
}

void VIPSigns::Apply(AActor& Patient, const TArray<FString>& Signs, float Strength)
{
	FLook Look;
	for (const FString& Sign : Signs)
	{
		const FString Name = Sign.TrimStartAndEnd().ToLower();
		if (!IsKnown(Name))
		{
			UE_LOG(LogVIPSigns, Warning, TEXT("Unknown visible sign '%s', ignored"), *Sign);
			continue;
		}
		Add(Look, Name, FMath::Clamp(Strength, 0.0f, 1.5f));
	}

	int32 Changed = 0;
	TInlineComponentArray<USkeletalMeshComponent*> Meshes(&Patient);
	for (USkeletalMeshComponent* Mesh : Meshes)
	{
		for (int32 Slot = 0; Slot < Mesh->GetNumMaterials(); ++Slot)
		{
			UMaterialInterface* Current = Mesh->GetMaterial(Slot);
			UMaterialInstanceDynamic* Dynamic = Cast<UMaterialInstanceDynamic>(Current);
			UMaterialInterface* Original = Dynamic ? Dynamic->Parent.Get() : Current;
			float Scalar = 0;
			FLinearColor Color;
			const bool bSkin = HasScalar(Original, SkinSaturation, Scalar);
			const bool bEye = HasVector(Original, ScleraTint, Color);
			if (!bSkin && !bEye)
			{
				continue;
			}
			if (!Dynamic)
			{
				Dynamic = Mesh->CreateAndSetMaterialInstanceDynamic(Slot);
			}
			if (!Dynamic)
			{
				continue;
			}
			if (bSkin)
			{
				if (HasScalar(Original, SkinSaturation, Scalar)) { Dynamic->SetScalarParameterValue(SkinSaturation, Scalar * Look.Saturation); }
				if (HasScalar(Original, SkinValue, Scalar))      { Dynamic->SetScalarParameterValue(SkinValue, Scalar * Look.Value); }
				if (HasScalar(Original, SkinRoughness, Scalar))  { Dynamic->SetScalarParameterValue(SkinRoughness, Scalar * Look.Roughness); }
				if (HasScalar(Original, SkinSpecular, Scalar))   { Dynamic->SetScalarParameterValue(SkinSpecular, Scalar * Look.Specular); }
				if (HasVector(Original, SkinTint, Color))        { Dynamic->SetVectorParameterValue(SkinTint, Color * Look.Tint); }
			}
			if (bEye)
			{
				Dynamic->SetVectorParameterValue(ScleraTint, Color * Look.Sclera);
				if (HasScalar(Original, ScleraVeins, Scalar))
				{
					Dynamic->SetScalarParameterValue(ScleraVeins, FMath::Clamp(Scalar + Look.Veins, 0.0f, 1.0f));
				}
			}
			++Changed;
		}
	}
	UE_LOG(LogVIPSigns, Display, TEXT("Visible signs [%s] at %.1f on %d materials of %s"),
		*FString::Join(Signs, TEXT(", ")), Strength, Changed, *Patient.GetName());
}
