// The desktop app's additions to the website, without changing the website's files (see README.md here):
// the live patient behind the page, the "page"/"live" modes for hud.css, and the app's API keys.
// Loaded in <head>, before app.js, so the two wrappers below are in place when it runs.
(() => {
  const VOICE = location.hostname + ':8787';

  // ---- The app's voice agent is private to the user's ElevenLabs account: connect by signed link ----
  // The website connects with a plain agent id; swap in the signed address here.
  const nativeFetch = window.fetch.bind(window);
  const NativeWebSocket = window.WebSocket;
  let signedUrl = null;
  let signedMode = false;

  async function refreshSignedUrl() {
    try {
      const response = await nativeFetch('/api/signed-url', { cache: 'no-store' });
      signedUrl = response.ok ? (await response.json()).signed_url : null;
    } catch { signedUrl = null; }
  }
  setInterval(() => { if (signedMode) refreshSignedUrl(); }, 5 * 60 * 1000);  // links expire

  // The patient is shown only once Unreal has been told who it is: before that it still shows the
  // previous (or default) person, who may not even have the right gender or age.
  const SWITCH_MS = 2500;  // time Unreal gets to change the face
  let revealTimer;

  function patientState(ready, text) {
    clearTimeout(revealTimer);
    document.documentElement.classList.toggle('hud-patient-ready', ready);
    const note = document.getElementById('hud-waiting');
    if (note) note.textContent = text;
  }

  window.fetch = async (input, options) => {
    if (!String(input?.url || input).endsWith('/api/start')) return nativeFetch(input, options);
    patientState(false, 'Waiting for the patient…');
    showHint('');
    const failed = async () => {
      patientState(false, 'The patient could not be loaded.');
      const keys = await nativeFetch('/api/keys').then((r) => (r.ok ? r.json() : null)).catch(() => null);
      if (keys?.app && !keys.openai) showHint('To load a patient, add your API keys: click Leave, then API KEYS.');
    };
    let response;
    try {
      response = await nativeFetch(input, options);
    } catch (error) {
      failed();
      throw error;
    }
    if (!response.ok) {
      failed();
      return response;
    }
    const result = await response.clone().json();
    signedMode = Boolean(result.signed);
    if (signedMode) await refreshSignedUrl();
    if (result.voice_error) showHint('Voice setup problem: ' + result.voice_error);
    else if (signedMode && !result.agent_id) {
      showHint('"Start talking" needs your ElevenLabs key: click Leave, then API KEYS.');
    }
    revealTimer = setTimeout(() => patientState(true, 'Waiting for the patient…'), SWITCH_MS);
    return response;
  };

  window.WebSocket = class extends NativeWebSocket {
    constructor(url, protocols) {
      let target = String(url);
      if (signedMode && signedUrl && /elevenlabs\.io\/v1\/convai\/conversation/.test(target)) {
        const wanted = new URL(target);
        const signed = new URL(signedUrl);
        wanted.searchParams.forEach((value, key) => {
          if (key !== 'agent_id' && !signed.searchParams.has(key)) signed.searchParams.set(key, value);
        });
        target = signed.toString();
        signedUrl = null;               // one use
        setTimeout(refreshSignedUrl, 0);
      }
      super(target, protocols);
    }
  };

  // A line in the conversation box saying what is missing; it stays until the next patient
  function showHint(text) {
    let hint = document.getElementById('hud-hint');
    if (!hint) {
      const card = document.querySelector('.conversation-card');
      if (!card) return;
      hint = document.createElement('p');
      hint.id = 'hud-hint';
      hint.className = 'conversation-note';
      card.append(hint);
    }
    hint.textContent = text;
  }

  // The website leaves "Submit findings" disabled on "Saving…" after a successful submit, so it is
  // stuck in the next interview. (Harmless to keep once the website resets it itself.)
  let submitLabel = '';
  function resetSubmitButton() {
    const button = document.getElementById('submit-notes');
    if (!button) return;
    submitLabel ||= button.innerHTML;
    button.innerHTML = submitLabel;
    button.disabled = false;
  }

  // ---- The patient: JPEG frames from Unreal, relayed by the voice server ----
  // Connected only during the interview; Unreal only captures while somebody watches.
  function patientView(stage, canvas) {
    const paint = canvas.getContext('2d');
    let socket = null;
    let wanted = false;
    let newest = null;
    let drawing = false;

    async function draw() {
      if (drawing || !newest) return;
      drawing = true;
      const blob = newest;
      newest = null;
      try {
        const picture = await createImageBitmap(blob);
        if (wanted) {
          if (canvas.width !== picture.width || canvas.height !== picture.height) {
            canvas.width = picture.width;
            canvas.height = picture.height;
          }
          paint.drawImage(picture, 0, 0);
          stage.classList.add('has-video');
        }
        picture.close();
      } catch { /* a broken frame: wait for the next one */ }
      drawing = false;
      draw();
    }

    function connect() {
      const mine = new NativeWebSocket('ws://' + VOICE + '/ws/video');
      socket = mine;
      mine.binaryType = 'blob';
      mine.onmessage = (event) => { newest = event.data; draw(); };
      mine.onclose = () => {
        if (socket !== mine) return;  // closed on purpose
        socket = null;
        setTimeout(() => { if (wanted && !socket) connect(); }, 2000);
      };
    }

    return (show) => {
      if (show === wanted) return;
      wanted = show;
      if (show) {
        connect();
        return;
      }
      const old = socket;
      socket = null;
      old?.close();
      newest = null;
      stage.classList.remove('has-video');  // the next interview must not start on this patient
    };
  }

  // ---- "live" while the interview screen is up, the plain website ("page") otherwise ----
  function followScreens(showPatient) {
    const interview = document.getElementById('interview-screen');
    const apply = () => {
      const live = Boolean(interview) && !interview.hidden;
      if (!live) {  // the next interview starts fresh
        patientState(false, 'Waiting for the patient…');
        setNotesClosed(false);
      } else {
        resetSubmitButton();
      }
      document.body.dataset.hud = live ? 'live' : 'page';
      showPatient(live);
    };
    apply();
    if (interview) new MutationObserver(apply).observe(interview, { attributes: true, attributeFilter: ['hidden'] });
  }
  function setNotesClosed(closed) {
    document.body.classList.toggle('hud-notes-closed', closed);
    const button = document.querySelector('.hud-notes-button');
    if (button) button.textContent = closed ? 'Show notes' : 'Hide notes';
  }

  // Buttons the interview needs in the app. The top bar is hidden there, so "Leave" stands in for
  // its SWITCH ROLE button: without it, an interview that cannot start has no way out.
  function addInterviewButtons() {
    const tools = document.querySelector('.interview-tools');
    if (!tools) return;
    const make = (label, className, onClick) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'back-button ' + className;
      button.textContent = label;
      button.addEventListener('click', onClick);
      return button;
    };
    tools.prepend(
      make('Leave', 'hud-only', () => {
        if (window.confirm('Leave this interview? Your notes are not saved.')) {
          document.getElementById('switch-role-button')?.click();
        }
      }),
      make('Hide notes', 'hud-only hud-notes-button', () => {
        setNotesClosed(!document.body.classList.contains('hud-notes-closed'));
      }),
    );
    // "Finish interview" checks the notes: they must be visible, or nothing seems to happen
    document.getElementById('end-interview-button')?.addEventListener('click', () => setNotesClosed(false), true);
  }

  // ---- The user's own OpenAI and ElevenLabs keys (packaged app only) ----
  async function addKeyScreen() {
    let status;
    try {
      const response = await nativeFetch('/api/keys');
      if (!response.ok) return;
      status = await response.json();
    } catch { return; }
    if (!status.app) return;  // the team's own setup uses engine/.env instead

    document.body.insertAdjacentHTML('beforeend', `
      <div id="hud-keys" hidden role="dialog" aria-modal="true" aria-labelledby="hud-keys-title">
        <section class="card section">
          <p class="eyebrow">API KEYS</p>
          <h2 id="hud-keys-title">Add your own API keys</h2>
          <p class="section-intro">The patient thinks with OpenAI and speaks with ElevenLabs, using <b>your</b> accounts. The keys are stored encrypted on this computer only and are sent only to OpenAI and ElevenLabs. To make the voice work, the app also stores your OpenAI key as a secret in your ElevenLabs workspace and creates one agent there called “VIP Patient (local app)”.</p>
          <form id="hud-keys-form" class="grid two" autocomplete="off">
            <label class="field"><span>OpenAI API key</span><input id="hud-openai" type="password" placeholder="sk-…" spellcheck="false"><small id="hud-openai-state"></small></label>
            <label class="field"><span>ElevenLabs API key</span><input id="hud-eleven" type="password" placeholder="Paste your ElevenLabs key" spellcheck="false"><small id="hud-eleven-state"></small></label>
            <div class="field full hud-keys-actions">
              <button class="save-button" id="hud-keys-save" type="submit">Check &amp; save keys</button>
              <button class="back-button" id="hud-keys-forget" type="button">Forget keys</button>
              <button class="back-button" id="hud-keys-close" type="button">Close</button>
            </div>
          </form>
          <p class="conversation-note" id="hud-keys-note"></p>
        </section>
      </div>`);
    const $ = (id) => document.getElementById(id);
    const dialog = $('hud-keys');
    const showState = (state) => {
      $('hud-openai-state').textContent = state.openai ? 'Saved on this computer.' : '';
      $('hud-eleven-state').textContent = state.elevenlabs ? 'Saved on this computer.' : '';
    };
    showState(status);
    dialog.hidden = status.openai && status.elevenlabs;

    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'top-tag';
    open.textContent = 'API KEYS';
    open.addEventListener('click', () => { dialog.hidden = false; });
    document.querySelector('.topbar')?.append(open);
    $('hud-keys-close').addEventListener('click', () => { dialog.hidden = true; });

    $('hud-keys-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const save = $('hud-keys-save');
      save.disabled = true;
      $('hud-keys-note').textContent = 'Checking the keys and setting up your patient agent…';
      try {
        const response = await nativeFetch('/api/keys', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ openai_key: $('hud-openai').value, elevenlabs_key: $('hud-eleven').value }),
        });
        const result = await response.json();
        if (!response.ok) {
          const errors = result.detail?.errors;
          throw new Error(errors ? Object.values(errors).join(' ') : (result.detail || result.error || 'Could not save the keys.'));
        }
        $('hud-openai').value = '';
        $('hud-eleven').value = '';
        showState(result);
        $('hud-keys-note').textContent = result.voice_error
          ? 'Keys saved, but the voice could not be set up: ' + result.voice_error
          : 'Keys saved.';
        if (result.ready && !result.voice_error) dialog.hidden = true;
      } catch (error) {
        $('hud-keys-note').textContent = error.message;
      } finally {
        save.disabled = false;
      }
    });

    $('hud-keys-forget').addEventListener('click', async () => {
      const response = await nativeFetch('/api/keys', { method: 'DELETE' });
      if (response.ok) {
        showState(await response.json());
        $('hud-keys-note').textContent = 'The keys were removed from this computer.';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.body.insertAdjacentHTML('afterbegin',
      '<div id="hud-stage" aria-hidden="true"><canvas id="hud-video"></canvas></div>' +
      '<p id="hud-waiting">Waiting for the patient…</p>');
    resetSubmitButton();  // remembers the button's own label
    addInterviewButtons();
    followScreens(patientView(document.getElementById('hud-stage'), document.getElementById('hud-video')));
    addKeyScreen();
  });
})();
