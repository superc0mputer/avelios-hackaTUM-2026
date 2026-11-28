"""Stage 3: the doctor's office level with the default patient seated, a camera, lights and the room (office.py).

Also writes the patient table the app picks from (DT_Patients, rows from patients.json).
"""
import json
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import office  # noqa: E402

LEVEL = "/Game/Patient/ConsultationRoom"
TABLE = "/Game/Patient/DT_Patients"
PATIENTS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "patients.json")))["patients"]
DEFAULT = next(p for p in PATIENTS if p.get("default"))


def blueprint_path(preset):
    return "/Game/MetaHumans/MHC_{0}/BP_MHC_{0}".format(preset)


def log(message):
    unreal.log_warning("VIP: " + str(message))


patient_class = unreal.EditorAssetLibrary.load_blueprint_class(blueprint_path(DEFAULT["preset"]))
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
patient.tags = ["VIPPatient"]  # the app swaps this one for the patient that fits the case
# the face follows the speech subject the game creates (Source/VIPPatient)
patient.set_editor_property("LiveLinkSubject", unreal.LiveLinkSubjectName(name="VIPSpeech"))
patient.set_editor_property("UseLiveLink", True)


def bone(actor, name):
    """World location of a bone of the patient's body (rest pose), or None."""
    for component in actor.get_components_by_class(unreal.SkeletalMeshComponent):
        if component.get_bone_index(name) != -1:
            return component.get_socket_location(name)
    return None


# Seated: lower the patient so the hips are at the chair's height; the game bends the legs
# (VIPBody.h) and lowers every other patient the same way (VIPPatients::SeatHipHeight)
SEAT_HIP_HEIGHT = 56.0
hip = bone(patient, "thigh_l")
if hip is None:
    raise RuntimeError("patient has no thigh_l bone")
patient.set_actor_location(unreal.Vector(0, 0, SEAT_HIP_HEIGHT - hip.z), False, False)
head = bone(patient, "head")
head_z = head.z + 10 if head else 125  # about eye height

# MetaHumans face +Y, so the camera sits on +Y looking back: the doctor's eyes behind the desk
camera_y = 230.0
# the face matters most (expressions, signs): head and shoulders, eyes in the upper third,
# the office softly blurred behind
camera = spawn(unreal.CineCameraActor, (0, camera_y, head_z + 2), "PatientCamera", yaw=-90, pitch=-3)
lens = camera.get_cine_camera_component()
lens.set_editor_property("current_focal_length", 65.0)
lens.set_editor_property("current_aperture", 4.0)  # background soft but recognisable
focus = lens.get_editor_property("focus_settings")
focus.focus_method = unreal.CameraFocusMethod.MANUAL
focus.manual_focus_distance = camera_y - (head.y if head else 0) + 2  # the eyes; desk and room fall softly out of focus
lens.set_editor_property("focus_settings", focus)
camera.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
camera.tags = ["VIPFollowHead"]  # moved with the head when a taller or shorter patient is chosen

import office_pack  # noqa: E402  (the Fab office pack, if this person downloaded it)
office.build(head_z, office_pack.ensure_imported() or None)


def light(label, location, yaw, pitch, intensity, size=80.0, follow_head=True, reach=230.0, shadows=True):
    actor = spawn(unreal.RectLight, location, label, pitch=pitch, yaw=yaw)
    if follow_head:
        actor.tags = ["VIPFollowHead"]
    component = actor.light_component
    component.set_intensity(intensity)
    component.set_editor_property("source_width", size)
    component.set_editor_property("source_height", size)
    # light the patient only: the room has its own window and ceiling light, and these would throw
    # big shadows of the furniture onto the back wall
    component.set_editor_property("attenuation_radius", reach)
    component.set_editor_property("cast_shadows", shadows)
    return component


# soft key from one side, little fill, so the face has shape; a rim light separates it from the wall
light("KeyLight", (90, 100, head_z + 35), -132, -15, 5.0, size=100.0, reach=185.0)
light("FillLight", (-100, 90, head_z), -42, 0, 1.0, reach=185.0)
light("RimLight", (-60, -90, head_z + 40), 56, -18, 4.0, reach=130.0, shadows=False)  # must not reach the wall

# a soft vignette, no film grain; exposure stays automatic
volume = spawn(unreal.PostProcessVolume, (0, 0, 0), "PostProcess")
volume.set_editor_property("unbound", True)
settings = volume.get_editor_property("settings")
for name, value in (("vignette_intensity", 0.4), ("film_grain_intensity", 0.0), ("bloom_intensity", 0.2),
                    ("auto_exposure_bias", -0.2),  # the room read too bright
                    # skin rendered too orange: white balance slightly cooler, a little less saturation (#44)
                    ("white_temp", 7000.0), ("color_saturation", unreal.Vector4(1.0, 1.0, 1.0, 0.9))):
    settings.set_editor_property("override_" + name, True)
    settings.set_editor_property(name, value)
volume.set_editor_property("settings", settings)

# the table the app chooses from; rows reference each patient's Blueprint
lib = unreal.EditorAssetLibrary
if lib.does_asset_exist(TABLE):
    table = lib.load_asset(TABLE)  # refilled below; deleting and recreating it fails while it is referenced
else:
    factory = unreal.DataTableFactory()
    factory.set_editor_property("struct", unreal.VIPPatientRow.static_struct())
    table = unreal.AssetToolsHelpers.get_asset_tools().create_asset("DT_Patients", "/Game/Patient", unreal.DataTable, factory)
rows = [{"Name": p["preset"], "Preset": p["preset"], "Gender": p["gender"], "Age": p["age"],
         "Character": p.get("character", ""),
         "Blueprint": "%s.BP_MHC_%s_C" % (blueprint_path(p["preset"]), p["preset"])}
        for p in sorted(PATIENTS, key=lambda p: not p.get("default"))  # the app falls back to the first row
        if lib.does_asset_exist(blueprint_path(p["preset"]))]
if not unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(table, json.dumps(rows)):
    raise RuntimeError("could not fill the patient table")
lib.save_loaded_asset(table)
log("patients: " + ", ".join(r["Name"] for r in rows))

if not levels.save_current_level():
    raise RuntimeError("could not save the level")
log("STAGE OK")
