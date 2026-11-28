# The website in the desktop app

The Windows app shows **one window**: the website from `teacher-ui/`. Unreal runs without a window of its
own and sends its picture to the voice server (`/ws/video`). The website's interview screen draws that
picture full screen behind the controls, and switches to a voice-only view when Unreal is not running or
stops sending frames. This works the same in a normal browser, so there is one interview design for both.

`page_server.py` serves `teacher-ui/` and adds, only here:

- `hud.js`: connects to the user's own ElevenLabs agent by signed link, and the **API KEYS** dialog for the
  user's OpenAI and ElevenLabs keys;
- `hud.css`: the small styling those need.

## Preview

```
python app/hud/page_server.py          # http://127.0.0.1:8765, voice server on 8787 as usual
```
