#include "VIPLife.h"

namespace
{
	// Blinks: 12 to 20 a minute at rest
	constexpr double BlinkSeconds = 0.2;
	constexpr double MinBlinkGap = 2.0;
	constexpr double MaxBlinkGap = 6.0;
	constexpr float DoubleBlinkChance = 0.15f;

	// Eyes: tiny fixation jumps, and now and then a glance aside
	constexpr float FixationJitter = 0.035f;
	constexpr float GlanceSize = 0.28f;
	constexpr float EyeSeconds = 0.025f; // saccades are fast
	constexpr float GlanceHeadFollow = 6.0f; // degrees of head turn per unit of glance

	constexpr double HeadDegrees = 2.0;
	constexpr float HeadOffsetSeconds = 0.6f;

	/** 0 to 1 and back: shuts quickly, opens a little slower, like a real blink. */
	float BlinkShape(double Phase)
	{
		constexpr double Closed = 0.35;
		return static_cast<float>(Phase < Closed ? Phase / Closed : 1.0 - (Phase - Closed) / (1.0 - Closed));
	}

	float Approach(float Current, float Target, float DeltaTime, float TimeConstant)
	{
		return Target + (Current - Target) * FMath::Exp(-DeltaTime / TimeConstant);
	}

	void Add(TMap<FString, float>& Controls, const TCHAR* Name, float Value)
	{
		if (float* Current = Controls.Find(Name))
		{
			*Current = FMath::Clamp(*Current + Value, 0.0f, 1.0f);
		}
	}

	void AddSided(TMap<FString, float>& Controls, const FString& Base, float Left, float Right)
	{
		Add(Controls, *(Base + TEXT("L")), Left);
		Add(Controls, *(Base + TEXT("R")), Right);
	}
}

void FVIPLife::Set(const FVIPLifeParams& InParams)
{
	FScopeLock Lock(&Mutex);
	Params = InParams;
}

FRotator FVIPLife::Apply(TMap<FString, float>& Controls, double Now)
{
	FVIPLifeParams P;
	{
		FScopeLock Lock(&Mutex);
		P = Params;
	}
	if (LastTime == 0)
	{
		LastTime = Now;
		for (float& Value : Phase)
		{
			Value = Random.FRandRange(0.0f, 2 * PI);
		}
	}
	const float Delta = static_cast<float>(FMath::Clamp(Now - LastTime, 0.0, 0.1));
	LastTime = Now;
	const float T = static_cast<float>(Now - StartTime);
	const float Move = FMath::Max(P.Movement, 0.1f);

	// Eyes
	UpdateEyes(Now, P);
	const FVector2f Wanted = P.Gaze + EyeTarget;
	Eye.X = Approach(Eye.X, Wanted.X, Delta, EyeSeconds);
	Eye.Y = Approach(Eye.Y, Wanted.Y, Delta, EyeSeconds);
	const FString Look = TEXT("CTRL_expressions_eyeLook");
	AddSided(Controls, Look + TEXT("Left"), FMath::Max(Eye.X, 0.0f), FMath::Max(Eye.X, 0.0f));
	AddSided(Controls, Look + TEXT("Right"), FMath::Max(-Eye.X, 0.0f), FMath::Max(-Eye.X, 0.0f));
	AddSided(Controls, Look + TEXT("Up"), FMath::Max(Eye.Y, 0.0f), FMath::Max(Eye.Y, 0.0f));
	AddSided(Controls, Look + TEXT("Down"), FMath::Max(-Eye.Y, 0.0f), FMath::Max(-Eye.Y, 0.0f));

	UpdateBlink(Now, P, Controls);

	// The face is never perfectly still: slow, slightly uneven brow, lid and mouth-corner movement
	auto Wave = [&](int32 i, float Speed) { return 0.5f + 0.3f * FMath::Sin(T * Speed + Phase[i]) + 0.2f * FMath::Sin(T * Speed * 2.3f + Phase[i + 1]); };
	const float Brow = Wave(0, 0.21f * Move);
	const float Corner = Wave(2, 0.17f * Move);
	const float Lid = Wave(4, 0.27f * Move);
	AddSided(Controls, TEXT("CTRL_expressions_browRaiseIn"), 0.05f * Brow * Move, 0.045f * Brow * Move);
	AddSided(Controls, TEXT("CTRL_expressions_browRaiseOuter"), 0.02f * Wave(6, 0.13f) * Move, 0.025f * Brow * Move);
	AddSided(Controls, TEXT("CTRL_expressions_mouthCornerPull"), 0.03f * Corner, 0.025f * Corner);
	AddSided(Controls, TEXT("CTRL_expressions_eyeSquintInner"), 0.04f * Lid, 0.04f * Lid);

	// Head: slow overlapping sines, plus following big glances, plus what the game thread asks for
	const FRotator Sway(
		HeadDegrees * Move * (0.6 * FMath::Sin(T * 0.31 * Move + 2.0) + 0.3 * FMath::Sin(T * 0.87 * Move)),
		HeadDegrees * Move * (1.0 * FMath::Sin(T * 0.23 * Move) + 0.4 * FMath::Sin(T * 0.61 * Move + 1.0)),
		HeadDegrees * Move * 0.4 * FMath::Sin(T * 0.17 + 4.0));
	const FRotator Wanted3(P.HeadPitch + Eye.Y * GlanceHeadFollow * 0.5f, P.HeadYaw + Eye.X * GlanceHeadFollow, 0);
	Head.Pitch = Approach(Head.Pitch, Wanted3.Pitch, Delta, HeadOffsetSeconds / Move);
	Head.Yaw = Approach(Head.Yaw, Wanted3.Yaw, Delta, HeadOffsetSeconds / Move);
	return Sway + Head;
}

void FVIPLife::UpdateEyes(double Now, const FVIPLifeParams& P)
{
	if (Now < NextSaccade)
	{
		return;
	}
	if (Now < GlanceUntil)
	{
		return; // hold the glance
	}
	if (GlanceUntil > 0)
	{
		// back from a glance to the student
		GlanceUntil = 0;
		EyeTarget = FVector2f(Random.FRandRange(-FixationJitter, FixationJitter), Random.FRandRange(-FixationJitter, FixationJitter));
		NextSaccade = Now + Random.FRandRange(0.6f, 2.0f);
		return;
	}
	if (Random.FRand() < P.GlanceRate * 0.15f)
	{
		// a short look aside, mostly sideways and down, as people do while talking or thinking
		const float Side = Random.FRand() < 0.5f ? -1.0f : 1.0f;
		EyeTarget = FVector2f(Side * Random.FRandRange(0.5f, 1.0f) * GlanceSize, Random.FRandRange(-0.8f, 0.3f) * GlanceSize);
		GlanceUntil = Now + Random.FRandRange(0.5f, 1.4f);
		NextSaccade = GlanceUntil;
		if (Random.FRand() < 0.4f && BlinkStart < 0)
		{
			BlinkStart = Now; // people often blink with a big eye movement
		}
		return;
	}
	// small fixation jumps between the student's eyes and face
	EyeTarget = FVector2f(Random.FRandRange(-FixationJitter, FixationJitter), Random.FRandRange(-FixationJitter, FixationJitter));
	NextSaccade = Now + Random.FRandRange(0.4f, 2.2f) / FMath::Max(P.Movement, 0.3f);
}

void FVIPLife::UpdateBlink(double Now, const FVIPLifeParams& P, TMap<FString, float>& Controls)
{
	if (NextBlink == 0)
	{
		NextBlink = Now + Random.FRandRange(1.0, MaxBlinkGap);
	}
	if (Now >= NextBlink && BlinkStart < 0)
	{
		BlinkStart = Now;
	}
	if (BlinkStart < 0)
	{
		return;
	}
	const double Phase01 = (Now - BlinkStart) / BlinkSeconds;
	const float Blink = Phase01 >= 1.0 ? 0.0f : BlinkShape(Phase01);
	for (const TCHAR* Name : {TEXT("CTRL_expressions_eyeBlinkL"), TEXT("CTRL_expressions_eyeBlinkR")})
	{
		if (float* Value = Controls.Find(Name))
		{
			*Value = FMath::Max(*Value, Blink);
		}
	}
	if (Phase01 >= 1.0)
	{
		const float Rate = FMath::Max(P.BlinkRate, 0.2f);
		if (!bDoubleBlink && Random.FRand() < DoubleBlinkChance)
		{
			bDoubleBlink = true;
			BlinkStart = Now + 0.08; // a second blink right after
			NextBlink = Now + 0.08;
			return;
		}
		bDoubleBlink = false;
		BlinkStart = -1;
		NextBlink = Now + Random.FRandRange(MinBlinkGap, MaxBlinkGap) / Rate;
	}
}
