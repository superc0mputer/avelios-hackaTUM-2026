# The website on top of the patient (desktop app)

The Windows app shows **one window**. Up to the interview it is the website from `teacher-ui/` as it is.
When the interview starts, the live patient fills the window and the interview controls float over them.
Unreal runs without a window of its own and sends its picture to the page (`/ws/video`).

Nothing in `teacher-ui/` is changed for this. Keep building the website as usual; `page_server.py`
adds `hud.css` and `hud.js` only when the app serves the page.

## Preview your website changes on the patient

Without Unreal the interview's background is a plain gradient, with the same layout:

```
python app/hud/page_server.py          # http://127.0.0.1:8765, voice server on 8787 as usual
```

## What happens to new website content

- **Any screen except the interview** looks exactly as on the website. Nothing to do here.
- **The interview** ("live" mode) places known parts around the patient's face. The app relies on these
  names; if you rename one, update `hud.css`:

| Name in `index.html` | Where it floats |
|---|---|
| `#interview-screen` | switches to live mode while visible |
| `.interview-topline`, `.interview-tools` | top: title left, timer and buttons right |
| `.patient-identity` | under the title |
| `.student-notes-panel` | right edge |
| `.conversation-card`, `#conversation-log` | bottom left |
| `.patient-stage` | hidden (the real patient is behind the page) |

A **new** block inside the interview screen is not placed automatically: give it a position in the
"live mode" part of `hud.css`, keeping the middle of the screen free for the face.
