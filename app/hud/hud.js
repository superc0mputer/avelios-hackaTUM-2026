// The desktop app's additions to the website (see README.md here). The website itself shows the live
// patient (Unreal's video over /ws/video) and falls back to voice only, so this adds just two things:
//   * the app's voice agent lives in the user's own ElevenLabs account: connect by signed link;
//   * the user's own OpenAI and ElevenLabs keys (the API KEYS dialog).
// Loaded in <head>, before app.js, so the two wrappers below are in place when it runs.
(() => {
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

  // After a case is loaded, fetch a signed conversation link if the app's agent needs one
  window.fetch = async (input, options) => {
    const response = await nativeFetch(input, options);
    if (String(input?.url || input).endsWith('/api/start') && response.ok) {
      try {
        const result = await response.clone().json();
        signedMode = Boolean(result.signed);
        if (signedMode) await refreshSignedUrl();
      } catch { /* not JSON: leave it to the page */ }
    }
    return response;
  };

  // The website connects with a plain agent id; swap in the signed address here (one use per link)
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
        signedUrl = null;
        setTimeout(refreshSignedUrl, 0);
      }
      super(target, protocols);
    }
  };

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
      <dialog class="modal" id="hud-keys" aria-labelledby="hud-keys-title">
        <form id="hud-keys-form" autocomplete="off">
          <div class="modal-body">
            <p class="eyebrow">API keys</p>
            <h2 id="hud-keys-title">Add your own API keys</h2>
            <p>The patient thinks with OpenAI and speaks with ElevenLabs, using <b>your</b> accounts. The keys are stored
              on this computer only (on Windows encrypted for your user account) and are sent only to OpenAI and ElevenLabs. To make the voice work, the app also
              stores your OpenAI key as a secret in your ElevenLabs workspace and creates one agent there called
              “VIP Patient (local app)”.</p>
            <div class="grid" style="margin-top:18px">
              <label class="field"><span>OpenAI API key</span><input id="hud-openai" type="password" placeholder="sk-…" spellcheck="false"><small class="field-hint" id="hud-openai-state"></small></label>
              <label class="field"><span>ElevenLabs API key</span><input id="hud-eleven" type="password" placeholder="Paste your ElevenLabs key" spellcheck="false"><small class="field-hint" id="hud-eleven-state"></small></label>
            </div>
            <p class="field-hint" id="hud-keys-note" role="status" style="margin-top:12px"></p>
          </div>
          <div class="modal-actions">
            <button class="btn btn-ghost" id="hud-keys-forget" type="button">Forget keys</button>
            <button class="btn" id="hud-keys-close" type="button">Close</button>
            <button class="btn btn-primary" id="hud-keys-save" type="submit">Check &amp; save keys</button>
          </div>
        </form>
      </dialog>`);
    const $ = (id) => document.getElementById(id);
    const dialog = $('hud-keys');
    const showState = (state) => {
      $('hud-openai-state').textContent = state.openai ? 'Saved on this computer.' : '';
      $('hud-eleven-state').textContent = state.elevenlabs ? 'Saved on this computer.' : '';
    };
    showState(status);
    if (!(status.openai && status.elevenlabs)) dialog.showModal();

    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'top-tag';
    open.textContent = 'API KEYS';
    open.addEventListener('click', () => dialog.showModal());
    document.querySelector('.topbar')?.append(open);
    $('hud-keys-close').addEventListener('click', () => dialog.close());

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
        if (result.ready && !result.voice_error) dialog.close();
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

  document.addEventListener('DOMContentLoaded', addKeyScreen);
})();
