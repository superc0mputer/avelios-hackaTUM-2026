"""Issue #22: drive the patient's face from the microphone and compare each mood with Neutral.

You add the MetaHuman (Audio) source in the Live Link window when asked; the script does the rest.

Runs in the full editor (not -game, which has no Python). From the repository root, on macOS:

  open -n "/Users/Shared/Epic Games/UE_5.8/Engine/Binaries/Mac/UnrealEditor.app" --args \
    "$PWD/unreal/VIPPatient/VIPPatient.uproject" "-ExecCmds=py $PWD/unreal/VIPPatient/Scripts/face_test.py" \
    "-ini:EditorSettings:[/Script/UnrealEd.EditorPerformanceSettings]:bThrottleCPUWhenNotForeground=False"

Screenshots land in Saved/Screenshots/FaceTestAB. Nothing in the level is saved.
"""
import os
import time
import traceback

import unreal

LEVEL = "/Game/Patient/ConsultationRoom"
SUBJECT = "VIPAudio"
MOODS = ["HAPPINESS", "SADNESS", "FEAR", "DISGUST", "ANGER", "SURPRISE",
         "BOREDOM", "CONFIDENCE", "CONFUSION", "EXCITEMENT", "PLAYFULNESS"]
FLIPS = 3  # each mood is shown this often, always after the same time in Neutral
SECONDS = 4.0
STEPS = [(mood, name) for mood in MOODS for name in ["NEUTRAL", mood] * FLIPS]
OUTPUT = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir()),
                      "Screenshots", "FaceTestAB")
api = unreal.MetaHumanLocalLiveLinkSourceBlueprint


def log(message):
    unreal.log_warning("VIP: " + str(message))


def tell(message):
    log(message)
    unreal.EditorDialog.show_message("VIP face test", message, unreal.AppMsgType.OK)


def find_audio_subject():
    """The audio source has to be added by hand: Python loses the pointer inside the source
    handle that create_audio_source returns, so create_audio_subject always fails."""
    for key in unreal.LiveLinkBlueprintLibrary.get_live_link_subjects(False, False):
        settings = api.get_subject_settings(key)
        if settings and hasattr(settings, "set_mood"):
            return str(key.subject_name.name), settings
    return None, None


def drive_face(patient, subject):
    patient.set_editor_property("LiveLinkSubject", unreal.LiveLinkSubjectName(name=subject))
    patient.set_editor_property("UseLiveLink", True)
    for mesh in patient.get_components_by_class(unreal.SkeletalMeshComponent):
        mesh.set_update_animation_in_editor(True)


def prepare_scene():
    levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    levels.load_level(LEVEL)
    by_label = {a.get_actor_label(): a for a in actors.get_all_level_actors()}
    patient, camera = by_label["Patient"], by_label["PatientCamera"]

    levels.editor_set_viewport_realtime(True)
    levels.pilot_level_actor(camera)
    levels.editor_set_game_view(True)

    eye = camera.get_actor_location()
    label = actors.spawn_actor_from_class(
        unreal.TextRenderActor, unreal.Vector(0, eye.y - 105, eye.z + 10),
        unreal.Rotator(roll=0.0, pitch=0.0, yaw=90.0))
    text = label.text_render
    text.set_world_size(2.5)
    text.set_horizontal_alignment(unreal.HorizTextAligment.EHTA_CENTER)
    return patient, camera, text


class MoodCycle:
    """Flips between Neutral and one mood, so a difference is easy to spot."""

    def __init__(self, settings, camera, text):
        self.settings, self.camera, self.text = settings, camera, text
        self.index = -1
        self.next_step()
        self.handle = unreal.register_slate_post_tick_callback(self.tick)

    def next_step(self):
        self.index += 1
        self.start, self.shot = time.time(), False
        if self.index >= len(STEPS):
            self.settings.set_mood(unreal.AudioDrivenAnimationMood.NEUTRAL)
            self.text.set_text("done")
            return
        mood, name = STEPS[self.index]
        self.settings.set_mood(getattr(unreal.AudioDrivenAnimationMood, name))
        self.settings.set_mood_intensity(1.0)
        self.text.set_text("%s %d/%d: %s" % (mood, MOODS.index(mood) + 1, len(MOODS),
                                             "neutral" if name == "NEUTRAL" else "MOOD ON"))
        log("step %d %s" % (self.index, name))

    def tick(self, _delta):
        try:
            elapsed = time.time() - self.start
            mood, name = STEPS[self.index]
            # one pair of screenshots per mood, from the last flip
            if not self.shot and elapsed >= 3.0 and self.index % (2 * FLIPS) >= 2 * FLIPS - 2:
                self.shot = True
                path = os.path.join(OUTPUT, "%s_%s.png" % (mood, "off" if name == "NEUTRAL" else "on"))
                unreal.AutomationLibrary.take_high_res_screenshot(1280, 720, path, camera=self.camera)
            if elapsed >= SECONDS:
                self.next_step()
                if self.index >= len(STEPS):
                    self.finish()
        except Exception:
            unreal.unregister_slate_post_tick_callback(self.handle)
            tell(traceback.format_exc())

    def finish(self):
        unreal.unregister_slate_post_tick_callback(self.handle)
        log("FACE TEST DONE")
        tell("Done. The microphone stays connected. To try moods yourself: Window > Virtual Production > "
             "Live Link, select the subject, then Controls > Mood. Do not save the level.")


def start_after_load(_delta):
    """Open the scene, then wait for the user to add the audio source."""
    global waited, scene, cycle
    waited += 1
    if waited < 120:  # let the editor finish opening
        return
    try:
        if scene is None:
            os.makedirs(OUTPUT, exist_ok=True)
            scene = prepare_scene()
            scene[2].set_text("waiting for audio source")
            tell("Click OK, then add the microphone:\n\n"
                 "1. Window > Virtual Production > Live Link\n"
                 "2. + Add Source > MetaHuman (Audio)\n"
                 "3. Audio device: MacBook Air Microphone, subject name: %s\n"
                 "4. Create\n\n"
                 "Allow microphone access if macOS asks." % SUBJECT)
            return
        if waited % 60:
            return
        subject, settings = find_audio_subject()
        if not subject:
            return
        unreal.unregister_slate_post_tick_callback(startup)
        patient, camera, text = scene
        log("found subject " + subject)
        drive_face(patient, subject)
        tell("Found %s. After OK, keep talking in a normal voice for about %d minutes. The label flips between neutral "
             "and MOOD ON every 4 seconds. Watch the lips and the expression, and keep the Live "
             "Link window from covering the patient." % (subject, round(len(STEPS) * SECONDS / 60)))
        cycle = MoodCycle(settings, camera, text)
    except Exception:
        unreal.unregister_slate_post_tick_callback(startup)
        tell(traceback.format_exc())


waited = 0
scene = None
cycle = None
startup = unreal.register_slate_post_tick_callback(start_after_load)
