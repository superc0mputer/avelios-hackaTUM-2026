"""Stage 3: consultation room level with the patient, a camera and three lights."""
import unreal

LEVEL = "/Game/Patient/ConsultationRoom"
BLUEPRINT = "/Game/MetaHumans/MHC_Patient/BP_MHC_Patient"


def log(message):
    unreal.log_warning("VIP: " + str(message))


patient_class = unreal.EditorAssetLibrary.load_blueprint_class(BLUEPRINT)
levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
if not levels.new_level(LEVEL):
    raise RuntimeError("could not create the level")


def spawn(cls, location, label, pitch=0.0, yaw=0.0):
    actor = actors.spawn_actor_from_class(
        cls, unreal.Vector(*location), unreal.Rotator(roll=0.0, pitch=pitch, yaw=yaw))
    actor.set_actor_label(label)
    return actor


patient = spawn(patient_class, (0, 0, 0), "Patient")
_, extent = patient.get_actor_bounds(False)
head_z = extent.z * 2 - 15 if extent.z > 50 else 160

# MetaHumans face +Y, so the camera sits on +Y looking back
camera = spawn(unreal.CineCameraActor, (0, 165, head_z - 7), "PatientCamera", yaw=-90)
lens = camera.get_cine_camera_component()
lens.set_editor_property("current_focal_length", 50.0)
focus = lens.get_editor_property("focus_settings")
focus.focus_method = unreal.CameraFocusMethod.DISABLE
lens.set_editor_property("focus_settings", focus)
camera.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)


def light(label, location, yaw, pitch, intensity):
    component = spawn(unreal.RectLight, location, label, pitch=pitch, yaw=yaw).light_component
    component.set_intensity(intensity)
    component.set_editor_property("source_width", 80.0)
    component.set_editor_property("source_height", 80.0)


light("KeyLight", (80, 100, head_z + 30), -128, -12, 8.0)
light("FillLight", (-100, 90, head_z), -42, 0, 3.0)
light("RimLight", (-60, -90, head_z + 40), 56, -18, 6.0)

if not levels.save_current_level():
    raise RuntimeError("could not save the level")
log("STAGE OK")
