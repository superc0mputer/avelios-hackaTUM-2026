using UnrealBuildTool;

public class VIPPatientEditorTarget : TargetRules
{
	public VIPPatientEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("VIPPatient");
	}
}
