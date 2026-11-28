#include "VIPCase.h"

#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

bool FVIPCase::FromJson(const TSharedPtr<FJsonObject>& Json, FVIPCase& Out)
{
	if (!Json.IsValid())
	{
		return false;
	}
	const TSharedPtr<FJsonObject>* Wrapped = nullptr;
	const TSharedPtr<FJsonObject> Case = Json->TryGetObjectField(TEXT("case"), Wrapped) ? *Wrapped : Json;

	Case->TryGetStringField(TEXT("character_id"), Out.Character);
	const TSharedPtr<FJsonObject>* Patient = nullptr;
	if (Case->TryGetObjectField(TEXT("patient"), Patient))
	{
		(*Patient)->TryGetStringField(TEXT("gender"), Out.Gender);
		(*Patient)->TryGetNumberField(TEXT("age"), Out.Age);
	}
	const TSharedPtr<FJsonObject>* Personality = nullptr;
	if (Case->TryGetObjectField(TEXT("personality"), Personality))
	{
		(*Personality)->TryGetStringField(TEXT("mood"), Out.Mood);
		(*Personality)->TryGetStringField(TEXT("type"), Out.Personality);
	}
	const TSharedPtr<FJsonObject>* Presentation = nullptr;
	if (Case->TryGetObjectField(TEXT("presentation"), Presentation))
	{
		double Number = 0;
		if ((*Presentation)->TryGetNumberField(TEXT("pain"), Number))
		{
			Out.Pain = static_cast<float>(Number);
		}
		if ((*Presentation)->TryGetNumberField(TEXT("discomfort"), Number))
		{
			Out.Discomfort = static_cast<float>(Number);
		}
		if (!(*Presentation)->TryGetStringField(TEXT("breathing"), Out.Breathing)
			&& (*Presentation)->TryGetNumberField(TEXT("breathing"), Number))
		{
			Out.Breathing = FString::SanitizeFloat(Number);
		}
		(*Presentation)->TryGetStringArrayField(TEXT("visible_signs"), Out.VisibleSigns);
	}
	return true;
}

bool FVIPCase::FromFile(const FString& Path, FVIPCase& Out)
{
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		return false;
	}
	TSharedPtr<FJsonObject> Json;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	return FJsonSerializer::Deserialize(Reader, Json) && FromJson(Json, Out);
}

FVIPPersonalityStyle FVIPPersonalityStyle::For(const FString& Personality)
{
	FVIPPersonalityStyle Style;
	const FString Name = Personality.ToLower();
	if (Name == TEXT("anxious_talkative"))
	{
		// restless: blinks and looks around more, moves more
		Style.BlinkRate = 1.5f;
		Style.GlanceRate = 0.25f;
		Style.Movement = 1.25f;
	}
	else if (Name == TEXT("shy_reserved"))
	{
		// keeps eye contact short, never quite looks at you, nods little
		Style.Discomfort = 0.3f;
		Style.BlinkRate = 1.2f;
		Style.Nods = 0.5f;
	}
	else if (Name == TEXT("assertive"))
	{
		// steady gaze, few blinks
		Style.BlinkRate = 0.75f;
		Style.GlanceRate = -0.1f;
	}
	else if (Name == TEXT("distrustful"))
	{
		// watches you, glances away, a slightly narrowed look, no nodding
		Style.Squint = 0.18f;
		Style.GlanceRate = 0.15f;
		Style.Nods = 0;
	}
	else if (Name == TEXT("downplays_everything"))
	{
		Style.Nods = 0.7f;
	}
	return Style;
}
