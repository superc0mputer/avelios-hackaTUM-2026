"""Stage 2: assemble the character into a Blueprint."""
import unreal

CHAR = "/Game/Patient/MHC_Patient"
BLUEPRINT = "/Game/MetaHumans/MHC_Patient/BP_MHC_Patient"


def log(message):
    unreal.log_warning("VIP: " + str(message))


lib = unreal.EditorAssetLibrary
character = unreal.load_asset(CHAR)
sub = unreal.get_editor_subsystem(unreal.MetaHumanCharacterEditorSubsystem)
if not sub.try_add_object_to_edit(character):
    raise RuntimeError("cannot edit character")
try:
    params = unreal.MetaHumanCharacterEditorBuildParameters()
    params.pipeline_type = unreal.MetaHumanDefaultPipelineType.OPTIMIZED
    params.pipeline_quality = unreal.MetaHumanQualityLevel.MEDIUM
    params.absolute_build_path = "/Game/MetaHumans"
    params.common_folder_path = "/Game/MetaHumans/Common"
    params.enable_wardrobe_item_validation = False
    log("assembling")
    try:
        sub.build_meta_human(character=character, params=params)
    except Exception as error:
        # Known on UE 5.8: Control Rig "Cannot break link" errors are raised
        # although the Blueprint is still produced. Checked below.
        log("assembly reported errors: " + str(error)[:200])
finally:
    if sub.is_object_added_for_editing(character):
        sub.remove_object_to_edit(character)

lib.save_directory("/Game", only_if_is_dirty=True, recursive=True)
# A failed assembly can still leave an empty Blueprint, so check the meshes too
for asset in (BLUEPRINT,
              "/Game/MetaHumans/MHC_Patient/Face/SKM_MHC_Patient_FaceMesh",
              "/Game/MetaHumans/MHC_Patient/Body/SKM_MHC_Patient_BodyMesh"):
    if not lib.does_asset_exist(asset):
        raise RuntimeError("assembly is incomplete, missing " + asset)
log("STAGE OK")
