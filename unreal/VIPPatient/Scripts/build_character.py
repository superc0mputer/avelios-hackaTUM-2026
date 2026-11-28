"""Stage 1: copy an Epic preset, download textures and create the full face rig."""
import os
import unreal

# build.sh runs this once per patient in patients.json
PRESET_NAME = os.environ.get("VIP_PRESET", "Walter")
PRESET = "/MetaHumanCharacter/Optional/Presets/" + PRESET_NAME
CHAR = "/Game/Patient/Characters/MHC_" + PRESET_NAME


def log(message):
    unreal.log_warning("VIP: " + str(message))


lib = unreal.EditorAssetLibrary
if not lib.does_asset_exist(CHAR):
    if not lib.duplicate_asset(PRESET, CHAR):
        raise RuntimeError("could not copy preset " + PRESET_NAME)
character = unreal.load_asset(CHAR)

sub = unreal.get_editor_subsystem(unreal.MetaHumanCharacterEditorSubsystem)
if not sub.try_add_object_to_edit(character):
    raise RuntimeError("cannot edit character")
try:
    rig = unreal.MetaHumanCharacterAutoRiggingRequestParams()
    rig.blocking = True
    rig.report_progress = False
    rig.rig_type = unreal.MetaHumanRigType.JOINTS_AND_BLEND_SHAPES
    log("creating full rig")
    sub.request_auto_rigging(character, rig)

    # textures need a signed-in user; the rig request above waits for the sign-in
    textures = unreal.MetaHumanCharacterTextureRequestParams()
    textures.blocking = True
    textures.report_progress = False
    log("downloading textures")
    sub.request_texture_sources(character, textures)

    # only save a character that can really be assembled
    if not sub.can_build_meta_human(character):
        raise RuntimeError("textures or rig missing: check the Epic sign-in and your connection")
    lib.save_loaded_asset(character, False)
finally:
    if sub.is_object_added_for_editing(character):
        sub.remove_object_to_edit(character)
log("STAGE OK")
