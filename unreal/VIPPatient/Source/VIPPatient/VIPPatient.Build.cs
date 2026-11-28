using UnrealBuildTool;

public class VIPPatient : ModuleRules
{
	public VIPPatient(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PrivateDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"LiveLinkInterface",
			"LiveLink",
			"MetaHumanCoreTech",
			"MetaHumanLiveLinkSource",
			"MetaHumanLocalLiveLinkSource",
			"MetaHumanPipelineCore",
			"SpeechAnimationSolver",
			// Link to the voice server (VIPBackendLink)
			"WebSockets",
			"Json",
		});
	}
}
