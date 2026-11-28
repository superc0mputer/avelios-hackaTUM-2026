"""Stage 3: consultation room level with the default patient, a camera, lights and a simple room.

Also writes the patient table the app picks from (DT_Patients, rows from patients.json).
"""
import json
import os

import unreal

LEVEL = "/Game/Patient/ConsultationRoom"
TABLE = "/Game/Patient/DT_Patients"
PATIENTS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "patients.json")))["patients"]
DEFAULT = next(p for p in PATIENTS if p.get("default"))


def blueprint_path(preset):
    return "/Game/MetaHumans/MHC_{0}/BP_MHC_{0}".format(preset)
MATERIALS = "/Game/Patient/Materials"
CUBE = "/Engine/BasicShapes/Cube"


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


def flat_material():
    """Parent for all room colours: a Color parameter and a matte surface."""
    path = MATERIALS + "/M_Flat"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.EditorAssetLibrary.load_asset(path)
    base = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        "M_Flat", MATERIALS, unreal.Material, unreal.MaterialFactoryNew())
    edit = unreal.MaterialEditingLibrary
    color = edit.create_material_expression(base, unreal.MaterialExpressionVectorParameter, -300, 0)
    color.set_editor_property("parameter_name", "Color")
    edit.connect_material_property(color, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = edit.create_material_expression(base, unreal.MaterialExpressionConstant, -300, 200)
    rough.set_editor_property("r", 0.8)
    edit.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    edit.recompile_material(base)
    unreal.EditorAssetLibrary.save_loaded_asset(base)
    return base


def material(name, color):
    """A flat colour: an instance of M_Flat."""
    path = "%s/%s" % (MATERIALS, name)
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        instance = unreal.EditorAssetLibrary.load_asset(path)
    else:
        instance = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, MATERIALS, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        unreal.MaterialEditingLibrary.set_material_instance_parent(instance, flat_material())
    edit = unreal.MaterialEditingLibrary
    edit.set_material_instance_vector_parameter_value(instance, "Color", unreal.LinearColor(*color, 1.0))
    edit.update_material_instance(instance)
    got = edit.get_material_instance_vector_parameter_value(instance, "Color")
    if abs(got.r - color[0]) > 0.01:
        raise RuntimeError("%s: colour not applied (got %s)" % (name, got))
    unreal.EditorAssetLibrary.save_loaded_asset(instance)
    return instance


def box(label, base, size, look):
    """A cube of the given size in cm standing on `base` (x, y, z of its bottom centre)."""
    x, y, z = base
    actor = spawn(unreal.StaticMeshActor, (x, y, z + size[2] / 2.0), label)
    mesh = actor.static_mesh_component
    mesh.set_static_mesh(unreal.EditorAssetLibrary.load_asset(CUBE))
    mesh.set_material(0, look)
    actor.set_actor_scale3d(unreal.Vector(*(s / 100.0 for s in size)))
    return actor


patient = spawn(patient_class, (0, 0, 0), "Patient")
patient.tags = ["VIPPatient"]  # the app swaps this one for the patient that fits the case
# the face follows the speech subject the game creates (Source/VIPPatient)
patient.set_editor_property("LiveLinkSubject", unreal.LiveLinkSubjectName(name="VIPSpeech"))
patient.set_editor_property("UseLiveLink", True)
_, extent = patient.get_actor_bounds(False)
head_z = extent.z * 2 - 15 if extent.z > 50 else 160

# MetaHumans face +Y, so the camera sits on +Y looking back
camera = spawn(unreal.CineCameraActor, (0, 165, head_z - 7), "PatientCamera", yaw=-90)
lens = camera.get_cine_camera_component()
lens.set_editor_property("current_focal_length", 50.0)
lens.set_editor_property("current_aperture", 2.8)
focus = lens.get_editor_property("focus_settings")
focus.focus_method = unreal.CameraFocusMethod.MANUAL
focus.manual_focus_distance = 160.0  # the eyes; the room behind falls softly out of focus
lens.set_editor_property("focus_settings", focus)
camera.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
camera.tags = ["VIPFollowHead"]  # moved with the head when a taller or shorter patient is chosen

# the room: calm clinic colours, everything behind the patient so the camera sees it
wall = material("MI_Wall", (0.42, 0.47, 0.48))
floor = material("MI_Floor", (0.20, 0.17, 0.15))
wood = material("MI_Wood", (0.30, 0.20, 0.12))
white = material("MI_White", (0.75, 0.75, 0.73))
box("BackWall", (0, -170, 0), (700, 10, 320), wall)
box("SideWall", (-260, 0, 0), (10, 400, 320), wall)
box("Floor", (0, 0, -5), (700, 600, 5), floor)
box("Cabinet", (-150, -135, 0), (90, 50, 95), wood)
box("CabinetTop", (-150, -135, 95), (94, 54, 3), white)
box("PictureFrame", (110, -164, 131), (78, 2, 58), wood)
box("Picture", (110, -162, 135), (70, 2, 50), white)


def light(label, location, yaw, pitch, intensity, size=80.0, follow_head=True):
    actor = spawn(unreal.RectLight, location, label, pitch=pitch, yaw=yaw)
    if follow_head:
        actor.tags = ["VIPFollowHead"]
    component = actor.light_component
    component.set_intensity(intensity)
    component.set_editor_property("source_width", size)
    component.set_editor_property("source_height", size)
    return component


light("KeyLight", (80, 100, head_z + 30), -128, -12, 8.0)
light("FillLight", (-100, 90, head_z), -42, 0, 3.0)
light("RimLight", (-60, -90, head_z + 40), 56, -18, 6.0)
light("WallLight", (60, 60, 260), -100, -35, 4.0, size=200.0, follow_head=False).set_editor_property(
    "light_color", unreal.Color(255, 236, 214, 255))

# a soft vignette, no film grain; exposure stays automatic
volume = spawn(unreal.PostProcessVolume, (0, 0, 0), "PostProcess")
volume.set_editor_property("unbound", True)
settings = volume.get_editor_property("settings")
for name, value in (("vignette_intensity", 0.35), ("film_grain_intensity", 0.0), ("bloom_intensity", 0.2)):
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
