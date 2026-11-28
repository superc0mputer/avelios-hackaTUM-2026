"""The doctor's office around the seated patient (used by build_scene.py).

Seen from the doctor's chair: the desk in the foreground, the patient on a chair behind it, and
behind the patient the examination side of the room (not the doctor's side, or the patient looks
like the doctor): a privacy curtain, disinfectant, gloves, a sharps container and a blood-pressure
unit on the wall, a supply cabinet, an examination couch, a sink, a window with blinds, a poster,
an eye chart, a clock and a plant. Everything is built from Unreal's basic shapes and our own images
(textures/, drawn by make_textures.py), so a clean build needs no downloads.

Units: cm. The patient faces +Y (towards the camera); the camera looks along -Y, so -X is on
the camera's left.
"""
import os

import unreal

MATERIALS = "/Game/Patient/Materials"
TEXTURES = "/Game/Patient/Textures"
TEXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textures")
CUBE = "/Engine/BasicShapes/Cube"
CYLINDER = "/Engine/BasicShapes/Cylinder"
SPHERE = "/Engine/BasicShapes/Sphere"

SEAT_TOP = 46.0      # chair seat height; the hips sit 10 cm above it (VIPPatients::SeatHipHeight = 56)
DESK_TOP = 76.0
BACK_WALL_Y = -175.0
LEFT = -1.0          # -X is the camera's left

lib = unreal.EditorAssetLibrary
edit = unreal.MaterialEditingLibrary
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def log(message):
    unreal.log_warning("VIP: " + str(message))


# ---------------------------------------------------------------- materials

def _base_material(name, build):
    path = "%s/%s" % (MATERIALS, name)
    if lib.does_asset_exist(path):
        return lib.load_asset(path)
    base = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, MATERIALS, unreal.Material, unreal.MaterialFactoryNew())
    build(base)
    edit.recompile_material(base)
    lib.save_loaded_asset(base)
    return base


def _surface(base):
    """Color, Roughness and Metallic parameters: paint, wood, plastic, steel."""
    color = edit.create_material_expression(base, unreal.MaterialExpressionVectorParameter, -400, 0)
    color.set_editor_property("parameter_name", "Color")
    edit.connect_material_property(color, "", unreal.MaterialProperty.MP_BASE_COLOR)
    for i, (param, default, prop) in enumerate((("Roughness", 0.7, unreal.MaterialProperty.MP_ROUGHNESS),
                                                ("Metallic", 0.0, unreal.MaterialProperty.MP_METALLIC))):
        node = edit.create_material_expression(base, unreal.MaterialExpressionScalarParameter, -400, 200 + 150 * i)
        node.set_editor_property("parameter_name", param)
        node.set_editor_property("default_value", default)
        edit.connect_material_property(node, "", prop)


def _image(base):
    """An image (Image texture parameter); Glow > 0 makes it light up (the view out of the window)."""
    tex = edit.create_material_expression(base, unreal.MaterialExpressionTextureSampleParameter2D, -600, 0)
    tex.set_editor_property("parameter_name", "Image")
    edit.connect_material_property(tex, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)
    glow = edit.create_material_expression(base, unreal.MaterialExpressionScalarParameter, -600, 300)
    glow.set_editor_property("parameter_name", "Glow")
    glow.set_editor_property("default_value", 0.0)
    mult = edit.create_material_expression(base, unreal.MaterialExpressionMultiply, -300, 200)
    edit.connect_material_expressions(tex, "RGB", mult, "A")
    edit.connect_material_expressions(glow, "", mult, "B")
    edit.connect_material_property(mult, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    rough = edit.create_material_expression(base, unreal.MaterialExpressionConstant, -300, 400)
    rough.set_editor_property("r", 0.55)
    edit.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)


def _instance(name, parent):
    path = "%s/%s" % (MATERIALS, name)
    if lib.does_asset_exist(path):
        return lib.load_asset(path)
    instance = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, MATERIALS, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    edit.set_material_instance_parent(instance, parent)
    return instance


def surface(name, color, roughness=0.7, metallic=0.0):
    instance = _instance(name, _base_material("M_Surface", _surface))
    edit.set_material_instance_vector_parameter_value(instance, "Color", unreal.LinearColor(*color, 1.0))
    edit.set_material_instance_scalar_parameter_value(instance, "Roughness", roughness)
    edit.set_material_instance_scalar_parameter_value(instance, "Metallic", metallic)
    edit.update_material_instance(instance)
    lib.save_loaded_asset(instance)
    return instance


def texture(name):
    path = "%s/%s" % (TEXTURES, name)
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", os.path.join(TEXTURE_DIR, name + ".png"))
    task.set_editor_property("destination_path", TEXTURES)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", True)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    if not lib.does_asset_exist(path):
        raise RuntimeError("could not import " + name)
    return lib.load_asset(path)


def image(name, glow=0.0):
    instance = _instance("MI_" + name[2:], _base_material("M_Image", _image))
    edit.set_material_instance_texture_parameter_value(instance, "Image", texture(name))
    edit.set_material_instance_scalar_parameter_value(instance, "Glow", glow)
    edit.update_material_instance(instance)
    lib.save_loaded_asset(instance)
    return instance


# ---------------------------------------------------------------- shapes

def _mesh_actor(label, mesh_path, location, scale, look, yaw=0.0, pitch=0.0, roll=0.0):
    actor = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*location),
                                          unreal.Rotator(roll=roll, pitch=pitch, yaw=yaw))
    actor.set_actor_label(label)
    mesh = actor.static_mesh_component
    mesh.set_static_mesh(lib.load_asset(mesh_path))
    mesh.set_material(0, look)
    actor.set_actor_scale3d(unreal.Vector(*scale))
    actor.set_folder_path("Office")
    return actor


def box(label, center_bottom, size, look, yaw=0.0):
    """A box of `size` (x, y, z in cm) whose bottom face is centred on `center_bottom`."""
    x, y, z = center_bottom
    return _mesh_actor(label, CUBE, (x, y, z + size[2] / 2.0), tuple(s / 100.0 for s in size), look, yaw=yaw)


def cylinder(label, center_bottom, diameter, height, look, axis="z"):
    x, y, z = center_bottom
    if axis == "z":
        return _mesh_actor(label, CYLINDER, (x, y, z + height / 2.0), (diameter / 100.0, diameter / 100.0, height / 100.0), look)
    # lying along X (paper roll, faucet spout)
    return _mesh_actor(label, CYLINDER, (x, y, z), (diameter / 100.0, diameter / 100.0, height / 100.0), look, roll=90.0)


def sphere(label, center, diameter, look, squash=1.0, yaw=0.0, pitch=0.0, roll=0.0, stretch=1.0):
    return _mesh_actor(label, SPHERE, center, (diameter * stretch / 100.0, diameter / 100.0, diameter * squash / 100.0), look,
                       yaw=yaw, pitch=pitch, roll=roll)


def picture(label, center, width, height, look, frame_look, frame=4.0, depth=2.5):
    """A framed image on the back wall, facing the camera (+Y)."""
    x, y, z = center
    box(label + "Frame", (x, y, z - height / 2 - frame), (width + 2 * frame, depth, height + 2 * frame), frame_look)
    # the image is a very thin box just in front of the frame
    box(label, (x, y + depth / 2 + 0.3, z - height / 2), (width, 0.4, height), look)


# ---------------------------------------------------------------- the Fab office pack

# Pieces of the pack (names from the GLB). Every mesh keeps its place in the artist's scene, so a
# group is moved and turned as one: the first name is the anchor that lands on the target.
PACK_DESK = ["Table", "WQ54438", "keys", "lamp01", "board001", "board002", "Cup_tea01", "P1", "P2", "Fax_mach001"]
PACK_PATIENT_CHAIR = ["WQ54347"]
PACK_CURTAIN_WIDE = ["bd2020040320157"]
PACK_CURTAIN = ["bd2020040320156"]
PACK_PLANT = ["WQ54415"]
PACK_RUG = ["carpet"]
# where the visitor chair's seat surface is above its lowest point (chair seat at SEAT_TOP)
PACK_CHAIR_SEAT = 47.0


def place_group(label, pack, names, target, yaw=0.0):
    """Put the group so the anchor's footprint centre is at target (x, y) with its bottom at target z."""
    import math
    anchor = pack.get(names[0])
    if anchor is None:
        log("office pack has no %s, skipping %s" % (names[0], label))
        return []
    box_ = anchor.get_bounding_box()
    cx, cy = (box_.min.x + box_.max.x) / 2, (box_.min.y + box_.max.y) / 2
    t = math.radians(yaw)
    rx, ry = cx * math.cos(t) - cy * math.sin(t), cx * math.sin(t) + cy * math.cos(t)
    location = unreal.Vector(target[0] - rx, target[1] - ry, target[2] - box_.min.z)
    placed = []
    for name in names:
        mesh = pack.get(name)
        if mesh is None:
            continue
        actor = actors.spawn_actor_from_class(unreal.StaticMeshActor, location, unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw))
        actor.static_mesh_component.set_static_mesh(mesh)
        actor.set_actor_label("%s_%s" % (label, name))
        actor.set_folder_path("Office/Pack")
        placed.append(actor)
    return placed


def _pack_furniture(pack):
    """Furniture from the Fab pack: the patient's chair, the doctor's desk, curtains over the window, plant, rug."""
    # the patient sits in a visitor chair facing the doctor (the chairs face +Y in the pack, like the patient)
    place_group("PatientChair", pack, PACK_PATIENT_CHAIR, (0, -3, SEAT_TOP - PACK_CHAIR_SEAT))
    # the desk turned round: its working side, with monitor, keyboard and lamp, faces the doctor (camera)
    place_group("Desk", pack, PACK_DESK, (0, 125, 0), yaw=180.0)
    # sheer curtains over the window behind the patient, the fig plant in front of them
    place_group("Curtain", pack, PACK_CURTAIN_WIDE, (LEFT * 125, BACK_WALL_Y + 6, 0))
    place_group("Plant", pack, PACK_PLANT, (LEFT * 150, BACK_WALL_Y + 70, 0))
    place_group("Rug", pack, PACK_RUG, (0, 40, 0))


# ---------------------------------------------------------------- the office

def build(head_z, pack=None):
    """The office; `pack` = meshes of the Fab office pack by name (office_pack.py), or None for the scripted one."""
    wall = surface("MI_Wall", (0.52, 0.53, 0.50), 0.9)
    accent = surface("MI_WallAccent", (0.50, 0.56, 0.53), 0.9)  # calm sage behind the patient
    skirting = surface("MI_Skirting", (0.85, 0.85, 0.82), 0.5)
    floor = surface("MI_Floor", (0.33, 0.30, 0.26), 0.55)
    desk_top = surface("MI_DeskTop", (0.16, 0.10, 0.06), 0.4)
    desk_body = surface("MI_DeskBody", (0.80, 0.80, 0.78), 0.5)
    fabric = surface("MI_ChairFabric", (0.06, 0.10, 0.14), 0.95)
    steel = surface("MI_Steel", (0.55, 0.56, 0.58), 0.35, 0.0)  # not metallic: with nothing to reflect, metal renders black
    dark = surface("MI_DarkPlastic", (0.03, 0.03, 0.035), 0.4)
    white = surface("MI_WhitePlastic", (0.8, 0.8, 0.78), 0.35)
    paper = surface("MI_Paper", (0.85, 0.85, 0.82), 0.8)
    wood_frame = surface("MI_FrameWood", (0.25, 0.16, 0.09), 0.5)
    black_frame = surface("MI_FrameBlack", (0.02, 0.02, 0.02), 0.4)
    leaf = surface("MI_Leaf", (0.07, 0.20, 0.06), 0.6)
    pot = surface("MI_Pot", (0.55, 0.52, 0.48), 0.8)
    couch = surface("MI_CouchVinyl", (0.13, 0.27, 0.33), 0.45)
    binders = [surface("MI_Binder%d" % i, c, 0.5) for i, c in enumerate(
        ((0.05, 0.15, 0.40), (0.45, 0.05, 0.05), (0.05, 0.30, 0.15), (0.60, 0.50, 0.10), (0.08, 0.08, 0.08), (0.75, 0.75, 0.72)))]

    # --- room shell: floor, walls with an accent behind the patient, skirting boards
    box("Floor", (0, 0, -5), (800, 700, 5), floor)
    box("BackWall", (0, BACK_WALL_Y - 5, 0), (800, 10, 300), wall)
    box("AccentWall", (0, BACK_WALL_Y + 0.5, 0), (190, 1, 300), accent)
    box("LeftWall", (LEFT * 260, 0, 0), (10, 700, 300), wall)
    box("RightWall", (-LEFT * 260, 0, 0), (10, 700, 300), wall)
    box("Ceiling", (0, 0, 300), (800, 700, 5), skirting)
    box("Skirting", (0, BACK_WALL_Y + 1.5, 0), (800, 2, 8), skirting)

    wx, wz, ww, wh = LEFT * 165, 100.0, 95.0, 120.0  # the window (behind the curtain with the pack)
    if pack:
        _pack_furniture(pack)
    else:
        # --- the patient's chair (seat under the hips, back behind the shoulders)
        box("ChairSeat", (0, -6, SEAT_TOP - 7), (48, 46, 7), fabric)
        box("ChairBack", (0, -32, SEAT_TOP + 8), (46, 6, 44), fabric, yaw=0.0)
        for sx in (-20, 20):
            for sy in (-26, 14):
                cylinder("ChairLeg", (sx, sy, 0), 3, SEAT_TOP - 7, steel)
        for sx in (-20, 20):
            cylinder("ChairBackPost", (sx, -30, SEAT_TOP - 7), 2.5, 22, steel)

        # --- the doctor's desk between the camera and the patient
        desk_front = 62.0  # patient side
        box("DeskTop", (0, desk_front + 37, DESK_TOP - 3), (170, 74, 3), desk_top)
        box("DeskPanel", (0, desk_front + 4, 0), (166, 3, DESK_TOP - 3), desk_body)       # modesty panel
        box("DeskDrawers", (-LEFT * 58, desk_front + 37, 0), (46, 68, DESK_TOP - 3), desk_body)
        box("DeskLegLeft", (LEFT * 82, desk_front + 37, 0), (4, 68, DESK_TOP - 3), desk_body)
        # monitor seen from behind on the camera's right, keyboard, papers, a mug and a pen cup
        box("MonitorStand", (-LEFT * 72, desk_front + 34, DESK_TOP), (20, 16, 1.5), dark)
        box("MonitorNeck", (-LEFT * 72, desk_front + 34, DESK_TOP), (4, 3, 12), dark)
        box("Monitor", (-LEFT * 72, desk_front + 36, DESK_TOP + 8), (48, 3, 29), dark, yaw=-LEFT * 28)
        box("Keyboard", (-LEFT * 45, desk_front + 58, DESK_TOP), (42, 14, 2), white, yaw=-LEFT * 8)
        box("Papers", (LEFT * 28, desk_front + 44, DESK_TOP), (22, 30, 1.2), paper, yaw=-8)
        box("Papers2", (LEFT * 30, desk_front + 45, DESK_TOP + 1.2), (21, 29.7, 0.6), paper, yaw=4)
        cylinder("Mug", (LEFT * 62, desk_front + 30, DESK_TOP), 8, 10, white)
        cylinder("PenCup", (LEFT * 72, desk_front + 18, DESK_TOP), 7, 11, dark)
        for i, dx in enumerate((-1.5, 0.5, 2)):
            cylinder("Pen%d" % i, (LEFT * 72 + dx, desk_front + 18 + dx, DESK_TOP + 6), 0.9, 12, binders[i])

        # --- window with blinds on the back wall, camera's left, clear of everything else
        box("WindowView", (wx, BACK_WALL_Y + 0.8, wz), (ww, 0.5, wh), image("T_WindowView", glow=4.0))
        for side in (-1, 1):
            box("WindowFrameSide", (wx + side * (ww / 2 + 3), BACK_WALL_Y + 1, wz - 3), (6, 6, wh + 6), skirting)
        box("WindowFrameTop", (wx, BACK_WALL_Y + 1, wz + wh), (ww + 12, 6, 6), skirting)
        box("WindowSill", (wx, BACK_WALL_Y + 3, wz - 3), (ww + 16, 8, 3), skirting)
        for i in range(int(wh / 10)):  # venetian blinds, open: the view shows between the slats
            box("Blind", (wx, BACK_WALL_Y + 6, wz + 6 + i * 10), (ww + 2, 2.5, 0.4), white)
        box("BlindRail", (wx, BACK_WALL_Y + 7, wz + wh - 5), (ww + 6, 6, 5), white)

        # --- plant in the corner under the window
        px, py = LEFT * 215, BACK_WALL_Y + 40
        cylinder("PlantPot", (px, py, 0), 38, 42, pot)
        import math
        import random
        rng = random.Random(3)
        leaf_light = surface("MI_LeafLight", (0.12, 0.28, 0.08), 0.6)
        for i in range(110):  # a bushy plant: long flat leaves, tilted every way, around a few stems
            height = rng.uniform(52, 145)
            spread = rng.uniform(0.35, 1.0) * (8 + 24 * math.sin(math.pi * (height - 45) / 105))
            angle = rng.uniform(0, 2 * math.pi)
            sphere("Leaf%d" % i, (px + spread * math.cos(angle), py + spread * math.sin(angle) * 0.8, height),
                   rng.uniform(7, 10), rng.choice((leaf, leaf, leaf_light)), squash=0.12, stretch=rng.uniform(1.8, 2.6),
                   yaw=math.degrees(angle) + rng.uniform(-30, 30), pitch=rng.uniform(-35, 35), roll=rng.uniform(-30, 30))
        for i, dx in enumerate((-4, 0, 5)):
            cylinder("PlantStem%d" % i, (px + dx, py, 40), 2, 70 + 15 * i, wood_frame)

    # --- white supply cabinet on the camera's right: boxes of supplies and bottles behind glass doors
    sx, sw, sd, sh = -LEFT * 130, 80.0, 36.0, 195.0
    sy = BACK_WALL_Y + sd / 2 + 1
    for side in (-1, 1):
        box("CabinetSide", (sx + side * (sw / 2 - 1), sy, 0), (2.5, sd, sh), desk_body)
    box("CabinetBase", (sx, sy, 0), (sw, sd, 80), desk_body)  # closed lower cupboard
    for z in (80, 120, 160, sh - 2.5):
        box("CabinetShelf", (sx, sy, z), (sw, sd, 2.5), desk_body)
    for side in (-1, 1):  # glass door frames
        box("CabinetDoorStile", (sx + side * (sw / 4), sy + sd / 2, 82), (2, 1.5, sh - 84), desk_body)
    box("CabinetDoorHandle", (sx - 4, sy + sd / 2 + 1, 50), (1.5, 2, 14), steel)
    box("CabinetDoorHandle2", (sx + 4, sy + sd / 2 + 1, 50), (1.5, 2, 14), steel)
    import random
    rng = random.Random(7)
    supply_colors = [surface("MI_Supply%d" % i, c, 0.6) for i, c in enumerate(
        ((0.80, 0.80, 0.78), (0.35, 0.55, 0.75), (0.30, 0.55, 0.40), (0.75, 0.75, 0.80), (0.70, 0.35, 0.30)))]
    for z in (82.5, 122.5, 162.5):
        x = sx - sw / 2 + 5
        while x < sx + sw / 2 - 12:
            if rng.random() < 0.35:  # a few bottles
                cylinder("Bottle", (x + 3, sy, z), 6, rng.choice((14, 18, 22)), rng.choice((white, supply_colors[1])))
                x += 8
                continue
            width = rng.choice((10, 14, 18))
            box("SupplyBox", (x + width / 2, sy, z), (width, 24, rng.choice((10, 14, 18, 22))), rng.choice(supply_colors))
            x += width + 1.5

    # --- behind the patient, on the camera's right: disinfectant, sharps container, glove boxes
    wall_front = BACK_WALL_Y + 1
    yellow = surface("MI_SharpsYellow", (0.75, 0.55, 0.02), 0.5)
    red = surface("MI_SharpsRed", (0.55, 0.04, 0.03), 0.5)
    grey = surface("MI_DeviceGrey", (0.62, 0.63, 0.65), 0.45)
    box("Disinfectant", (-LEFT * 52, wall_front + 5, 104), (12, 10, 27), white)
    box("DisinfectantNozzle", (-LEFT * 52, wall_front + 10, 106), (3, 3, 3), grey)
    box("SharpsContainer", (-LEFT * 52, wall_front + 8, 142), (19, 15, 18), yellow)
    box("SharpsLid", (-LEFT * 52, wall_front + 8, 160), (20, 16, 3), red)
    glove_colors = [surface("MI_Gloves%d" % i, c, 0.6) for i, c in enumerate(
        ((0.15, 0.30, 0.65), (0.40, 0.25, 0.60), (0.80, 0.80, 0.80)))]
    box("GloveHolderBack", (-LEFT * 80, wall_front + 0.5, 108), (27, 1, 56), steel)
    for i, look in enumerate(glove_colors):
        box("GloveBox%d" % i, (-LEFT * 80, wall_front + 7, 110 + i * 18), (25, 12, 13), look)
        box("GloveHolderBar%d" % i, (-LEFT * 80, wall_front + 13.5, 112 + i * 18), (27, 0.6, 0.6), steel)
    # blood-pressure unit with a round dial and the cuff hanging next to it
    box("BloodPressure", (-LEFT * 112, wall_front + 4, 135), (20, 8, 26), grey)
    dial = cylinder("BloodPressureDial", (-LEFT * 112, wall_front + 8.5, 151), 15, 1, image("T_Clock"))
    dial.set_actor_rotation(unreal.Rotator(roll=90.0, pitch=0.0, yaw=0.0), False)
    box("BloodPressureCuff", (-LEFT * 126, wall_front + 6, 112), (8, 6, 28), surface("MI_Cuff", (0.12, 0.22, 0.40), 0.8))

    if not pack:
        # --- privacy curtain on a ceiling rail, drawn back to the camera's left
        curtain = surface("MI_Curtain", (0.32, 0.46, 0.50), 0.95)
        rail_y = BACK_WALL_Y + 75
        box("CurtainRail", (LEFT * 95, rail_y, 236), (130, 3, 3), steel)
        for i in range(10):  # bunched folds
            x = LEFT * (58 + i * 6.5)
            box("CurtainFold%d" % i, (x, rail_y + (2.5 if i % 2 else -2.5), 12), (7.5, 4, 222), curtain)

    # --- poster, eye chart and clock away from the window
    picture("Poster", (-LEFT * 205, BACK_WALL_Y + 1, 150), 50, 71, image("T_Poster"), black_frame, frame=1.5)
    picture("EyeChart", (LEFT * 255, 40, 145), 42, 70, image("T_EyeChart"), black_frame, frame=1.5)
    clock = cylinder("Clock", (-LEFT * 130, BACK_WALL_Y + 4, 228), 30, 4, image("T_Clock"))
    clock.set_actor_rotation(unreal.Rotator(roll=90.0, pitch=0.0, yaw=0.0), False)

    # --- examination couch along the right wall, partly in view
    cx, cy = -LEFT * 215, -40.0
    box("CouchBase", (cx, cy, 0), (60, 170, 58), desk_body)
    box("CouchPad", (cx, cy, 58), (64, 180, 10), couch)
    box("CouchPaper", (cx, cy, 68), (50, 175, 0.4), paper)
    cylinder("CouchPaperRoll", (cx, cy + 92, 70), 12, 52, paper, axis="x")

    # --- sink and dispensers on the left wall
    box("SinkCabinet", (LEFT * 240, -60, 0), (40, 70, 85), desk_body)
    box("SinkBasin", (LEFT * 236, -60, 85), (46, 74, 6), white)
    cylinder("Faucet", (LEFT * 250, -60, 91), 3, 22, steel)
    box("Dispenser", (LEFT * 254, -60, 130), (8, 28, 36), white)

    # --- lights: daylight through the window and a soft ceiling panel
    day = actors.spawn_actor_from_class(unreal.RectLight, unreal.Vector(wx, BACK_WALL_Y + 20, wz + wh / 2),
                                        unreal.Rotator(roll=0.0, pitch=-20.0, yaw=90.0))
    day.set_actor_label("WindowLight")
    day.light_component.set_intensity(4.0)
    day.light_component.set_editor_property("source_width", ww)
    day.light_component.set_editor_property("source_height", wh)
    day.light_component.set_editor_property("light_color", unreal.Color(232, 242, 255, 255))  # daylight: slightly cool
    ceiling = actors.spawn_actor_from_class(unreal.RectLight, unreal.Vector(0, -60, 296),
                                            unreal.Rotator(roll=0.0, pitch=-90.0, yaw=0.0))
    ceiling.set_actor_label("CeilingLight")
    ceiling.light_component.set_intensity(3.5)
    ceiling.light_component.set_editor_property("source_width", 240.0)  # large, so shadows on the wall stay soft
    ceiling.light_component.set_editor_property("source_height", 160.0)
    ceiling.light_component.set_editor_property("light_color", unreal.Color(235, 245, 255, 255))
    box("CeilingPanel", (0, -60, 297), (122, 62, 2), skirting)
    # Lumen is off (frame rate), so nothing bounces light into shadows and they turn black: a large,
    # weak, shadowless light from the doctor's side stands in for the bounce light of a real room
    fill = actors.spawn_actor_from_class(unreal.RectLight, unreal.Vector(0, 160, 190),
                                         unreal.Rotator(roll=0.0, pitch=-8.0, yaw=-90.0))
    fill.set_actor_label("BounceFill")
    fill.light_component.set_intensity(2.0)
    fill.light_component.set_editor_property("source_width", 400.0)
    fill.light_component.set_editor_property("source_height", 250.0)
    fill.light_component.set_editor_property("cast_shadows", False)
    fill.light_component.set_editor_property("attenuation_radius", 900.0)
    fill.light_component.set_editor_property("light_color", unreal.Color(255, 246, 236, 255))
    log("office built")
