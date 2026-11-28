"""Imports the free Fab "Office Pack - Modern Office Interior Props" into /Game/OfficePack.

The pack cannot be in our public repository (Fab licence), so everyone downloads it from their
own Fab library, in the GLB format (materials and textures included; glTF is in metres, which
Unreal converts). FBX and OBJ are used only if no GLB is found: the OBJ has no materials.

Where the file is looked for, first match wins (GLB/glTF before FBX before OBJ):
  VIP_OFFICE_PACK (path to the file or its folder)
  unreal/OfficePack/ (anything below it)
  ~/Downloads/VaultCache/FabLibrary/Office_Pack*/  (where Fab's Download button puts it)

Run alone to list the imported meshes with sizes: -ExecutePythonScript=.../office_pack.py
"""
import glob
import os

import unreal

DESTINATION = "/Game/OfficePack"
HERE = os.path.dirname(os.path.abspath(__file__))
lib = unreal.EditorAssetLibrary


def log(message):
    unreal.log_warning("VIP: " + str(message))


FORMATS = (".glb", ".gltf", ".fbx", ".obj")  # best first


def find_pack_file():
    folders = []
    env = os.environ.get("VIP_OFFICE_PACK", "").strip()
    if env and os.path.isfile(env):
        return os.path.abspath(env)
    if env:
        folders.append(env)
    folders.append(os.path.join(HERE, "..", "..", "OfficePack"))
    home = os.path.expanduser("~")
    for root in (os.path.join(home, "Downloads", "VaultCache", "FabLibrary"),
                 os.path.join(home, "Documents", "VaultCache", "FabLibrary"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "VaultCache", "FabLibrary")):
        folders += glob.glob(os.path.join(root, "Office_Pack*"))
    files = []
    for folder in folders:
        files += [f for f in glob.glob(os.path.join(folder, "**", "*"), recursive=True)
                  if os.path.isfile(f) and os.path.splitext(f)[1].lower() in FORMATS]
    if not files:
        return None
    files.sort(key=lambda f: FORMATS.index(os.path.splitext(f)[1].lower()))
    return os.path.abspath(files[0])


def meshes():
    """Imported static meshes by name (empty when the pack is not imported)."""
    found = {}
    if not lib.does_directory_exist(DESTINATION):
        return found
    for path in lib.list_assets(DESTINATION, recursive=True, include_folder=False):
        asset = lib.load_asset(path)
        if isinstance(asset, unreal.StaticMesh):
            found[asset.get_name()] = asset
    return found


def ensure_imported():
    """Import the OBJ once; returns the meshes by name, or {} when the pack is not available."""
    existing = meshes()
    if existing:
        return existing
    obj = find_pack_file()
    if not obj:
        log("office pack not found (see office_pack.py); using the scripted office")
        return {}
    log("importing office pack from " + obj)
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", obj)
    task.set_editor_property("destination_path", DESTINATION)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", True)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    for path in lib.list_assets(DESTINATION, recursive=True, include_folder=False):
        lib.save_asset(path, only_if_is_dirty=False)
    found = meshes()
    log("office pack: %d meshes" % len(found))
    return found


def describe(found):
    for name in sorted(found):
        mesh = found[name]
        box = mesh.get_bounding_box()
        size = box.max - box.min
        center = (box.max + box.min) * 0.5
        log("mesh %-22s size %6.1f %6.1f %6.1f  center %7.1f %7.1f %7.1f  slots %d" % (
            name, size.x, size.y, size.z, center.x, center.y, center.z, len(mesh.static_materials)))


if __name__ == "__main__":
    describe(ensure_imported())
    log("STAGE OK")
