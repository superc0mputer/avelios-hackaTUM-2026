using UnrealBuildTool;

public class VIPPatientTarget : TargetRules
{
	public VIPPatientTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("VIPPatient");
	}
}
