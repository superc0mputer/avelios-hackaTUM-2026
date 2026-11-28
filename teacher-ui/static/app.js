const $ = (selector) => document.querySelector(selector);

const disclosureProfiles = {
  no_preference: 'An ordinary, cooperative patient; shares secrets once the student asks respectfully and specifically.',
  downplays_everything: 'Minimizes at first; secrets emerge after specific, respectful follow-up.',
  anxious_talkative: 'Volunteers context and may digress; secrets need empathetic, focused follow-up.',
  shy_reserved: 'Gives brief answers at first; opens up with gentle rapport.',
  assertive: 'Answers directly about symptoms; holds back personal details until invited.',
  distrustful: 'Stays guarded until the student explains the purpose and builds rapport.',
  custom: 'Disclosure behavior is inferred from the custom description and selected mood.',
};

const characters = [
  { id: 'man-01', label: 'Man 01', gender: 'male' },
  { id: 'man-02', label: 'Man 02', gender: 'male' },
  { id: 'man-03', label: 'Man 03', gender: 'male' },
  { id: 'woman-01', label: 'Woman 01', gender: 'female' },
  { id: 'woman-02', label: 'Woman 02', gender: 'female' },
  { id: 'woman-03', label: 'Woman 03', gender: 'female' },
];
const categories = ['symptoms', 'medical_history', 'medications', 'allergies', 'family_history', 'lifestyle', 'secrets'];
const stepTitles = ['Patient profile', 'Personality & mood', 'Clinical facts'];
const stepHints = [
  'Start with the patient’s identity and diagnosis.',
  'Choose how the patient behaves and feels at the start.',
  'Add the facts the patient can share during the interview.',
];
let currentStep = 0;
let toastTimer;
let savedCaseId = null;

function linesFrom(id) {
  return document.getElementById(id).value.split('\n').map((line) => line.trim()).filter(Boolean);
}

function makeCase() {
  const gender = $('#gender').value === 'other'
    ? $('#gender-other').value.trim()
    : $('#gender').value;
  const facts = Object.fromEntries(categories.map((category) => [
    category,
    linesFrom(category.replaceAll('_', '-')),
  ]));
  return {
    diagnosis: $('#diagnosis').value.trim(),
    character_id: $('#character-id').value,
    patient: {
      name: $('#name').value.trim(),
      age: Number.parseInt($('#age').value || '0', 10),
      gender,
      life_story: $('#life-story').value.trim(),
    },
    personality: {
      type: $('#personality-type').value,
      description: $('#personality-description').value.trim(),
      mood: $('#mood').value,
    },
    ...facts,
  };
}

function showToast(message, error = false) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.toggle('error', error);
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 4500);
}

function visibleCharacters() {
  const gender = $('#gender').value;
  if (gender === 'male' || gender === 'female') {
    return characters.filter((character) => character.gender === gender);
  }
  return characters;
}

function selectCharacter(characterId) {
  const character = characters.find((item) => item.id === characterId);
  if (!character) return;
  $('#character-id').value = character.id;
  $('#character-title').textContent = character.label;
  $('#avatar-window').dataset.characterId = character.id;
  $('#character-options').querySelectorAll('button').forEach((button) => {
    const selected = button.dataset.characterId === character.id;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
}

function renderCharacters() {
  const options = $('#character-options');
  const visible = visibleCharacters();
  options.replaceChildren();
  visible.forEach((character) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'character-option';
    button.dataset.characterId = character.id;
    button.setAttribute('aria-label', 'Select ' + character.label);
    button.innerHTML = '<span class="character-swatch" aria-hidden="true"><i></i></span><span>' + character.label + '</span>';
    button.addEventListener('click', () => selectCharacter(character.id));
    options.append(button);
  });
  const selected = visible.some((character) => character.id === $('#character-id').value)
    ? $('#character-id').value
    : visible[0].id;
  selectCharacter(selected);
}

function showStep(index) {
  currentStep = index;
  document.querySelectorAll('.wizard-step').forEach((panel, step) => {
    panel.hidden = step !== index;
  });
  $('#wizard-count').textContent = 'STEP ' + (index + 1) + ' OF ' + stepTitles.length;
  $('#wizard-title').textContent = stepTitles[index];
  $('#wizard-hint').textContent = stepHints[index];
  $('#progress-fill').style.width = (((index + 1) / stepTitles.length) * 100) + '%';
  document.querySelectorAll('[data-step-label]').forEach((label, step) => {
    label.classList.toggle('active', step === index);
    label.classList.toggle('complete', step < index);
  });
  $('#back-button').hidden = index === 0;
  $('#next-button').hidden = index === stepTitles.length - 1;
  $('#save-button').hidden = index !== stepTitles.length - 1;
  $('#status').textContent = '';
}

function validateCurrentStep() {
  const panel = document.querySelector('.wizard-step[data-step="' + currentStep + '"]');
  for (const field of panel.querySelectorAll(':required')) {
    if (!field.checkValidity()) {
      field.reportValidity();
      return false;
    }
  }
  return true;
}

function updateGenderFields() {
  const other = $('#gender').value === 'other';
  $('#gender-other-wrap').hidden = !other;
  $('#gender-other').required = other;
  renderCharacters();
}

$('#gender').addEventListener('change', updateGenderFields);
$('#personality-type').addEventListener('change', (event) => {
  const custom = event.target.value === 'custom';
  $('#personality-description').required = custom;
  $('#personality-description').placeholder = custom
    ? 'Describe how the patient behaves and how they reveal personal details'
    : 'Extra nuance: reactions, humour, and how the patient’s past shapes the conversation';
  $('#mapping-copy').textContent = disclosureProfiles[event.target.value];
});

$('#next-button').addEventListener('click', () => {
  if (!validateCurrentStep()) return;
  showStep(Math.min(currentStep + 1, stepTitles.length - 1));
  $('#wizard-heading').scrollIntoView({ behavior: 'smooth', block: 'start' });
});

$('#back-button').addEventListener('click', () => {
  showStep(Math.max(currentStep - 1, 0));
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

$('#case-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!validateCurrentStep()) return;
  const button = $('#save-button');
  button.disabled = true;
  $('#status').textContent = 'Validating and saving…';
  try {
    const response = await fetch('/api/cases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(makeCase()),
    });
    const result = await response.json();
    if (!response.ok) {
      const details = (result.details || []).slice(0, 5).join(' ');
      throw new Error(details || result.error || 'Could not save the case.');
    }
    $('#status').textContent = 'Saved ' + result.saved_as;
    showToast('Saved ' + result.saved_as);
    savedCaseId = result.case_id;
    loadSavedCases();
    $('#start-button').hidden = false;
  } catch (error) {
    $('#status').textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

// ---- Live interview: load the saved case, then talk to the patient in this page ----
// ElevenLabs browser SDK, loaded on demand (pinned version).
const ELEVENLABS_CLIENT_URL = 'https://cdn.jsdelivr.net/npm/@elevenlabs/client@1.36.1/+esm';
let liveAgentId = null;
let conversation = null;
const agentBubbles = new Map();
// The agent's output format: mono 16-bit PCM at this rate (ElevenLabs agent setting).
const PATIENT_AUDIO_RATE = 16000;
let stage = null;          // WebSocket to the voice server, relays audio to Unreal
let unrealListeners = 0;   // MetaHuman clients connected; while > 0 the browser stays silent

// Same origin over HTTPS (tailscale serve maps /ws to the voice server), else the voice server port.
function stageUrl() {
  return location.protocol === 'https:'
    ? 'wss://' + location.host + '/ws/stage'
    : 'ws://' + location.hostname + ':8787/ws/stage';
}

// Several people can open this page, but only one computer runs the MetaHuman. Every page sends
// the patient's voice there so the lips move (and everyone sees it in the live video); only the
// page that ticks this box has the demo computer play it out loud and goes quiet itself.
// Default: on for the demo computer itself (localhost), off elsewhere; remembered per browser.
const METAHUMAN_KEY = 'vip-metahuman-voice';
function initialMetaHumanChoice() {
  try {
    const saved = localStorage.getItem(METAHUMAN_KEY);
    if (saved !== null) return saved === '1';
  } catch (error) { /* storage blocked: fall back to the default */ }
  return ['localhost', '127.0.0.1'].includes(location.hostname);
}
$('#metahuman-voice').checked = initialMetaHumanChoice();
$('#metahuman-voice').addEventListener('change', () => {
  try { localStorage.setItem(METAHUMAN_KEY, $('#metahuman-voice').checked ? '1' : '0'); } catch (error) { /* ignore */ }
  applyUnrealRouting();
});

function useMetaHuman() {
  return unrealListeners > 0 && $('#metahuman-voice').checked;
}

// ---- Live video of the patient (JPEG frames from Unreal, relayed by the voice server) ----
let video = null;
let videoUrlObject = null;
let videoWanted = false;

function videoUrl() {
  return location.protocol === 'https:'
    ? 'wss://' + location.host + '/ws/video'
    : 'ws://' + location.hostname + ':8787/ws/video';
}

function openVideo() {
  videoWanted = true;
  if (video) return;
  $('#patient-video-box').hidden = false;
  try {
    video = new WebSocket(videoUrl());
  } catch (error) {
    video = null;
    return;
  }
  video.binaryType = 'blob';
  video.onmessage = (event) => {
    if (!(event.data instanceof Blob)) return;
    const next = URL.createObjectURL(event.data);
    $('#patient-video').src = next;
    if (videoUrlObject) URL.revokeObjectURL(videoUrlObject);
    videoUrlObject = next;
    $('#patient-video-note').textContent = '';
    const first = !watchingVideo();
    lastFrameAt = performance.now();
    if (first) applyUnrealRouting();
  };
  video.onclose = () => {
    video = null;
    $('#patient-video-note').textContent = 'The patient video is not available right now.';
    if (videoWanted) setTimeout(openVideo, 3000);
  };
}

// ---- Lip sync: the video of the lips arrives later than the voice (browser -> homebox -> Unreal
// -> picture -> back). While someone watches the video, this page plays the voice itself, delayed
// by that trip, instead of letting the ElevenLabs SDK play it at once. ----
const LIP_SYNC_KEY = 'vip-lipsync-ms';
let lipSyncMs = 400;
try { lipSyncMs = Number(localStorage.getItem(LIP_SYNC_KEY) ?? 400); } catch (error) { /* default */ }
let lastFrameAt = -Infinity;
let audioOut = null;      // AudioContext for the delayed voice
let playHead = 0;         // when the next queued chunk starts (AudioContext time)
let queued = [];          // scheduled chunks, stopped on interruption

function watchingVideo() {
  return performance.now() - lastFrameAt < 2000;
}

function delayedVoice() {
  return watchingVideo() && !useMetaHuman();
}

function showLipSync() {
  $('#lipsync').value = String(lipSyncMs);
  $('#lipsync-value').textContent = lipSyncMs + ' ms';
}
showLipSync();
$('#lipsync').addEventListener('input', () => {
  lipSyncMs = Number($('#lipsync').value);
  try { localStorage.setItem(LIP_SYNC_KEY, String(lipSyncMs)); } catch (error) { /* ignore */ }
  showLipSync();
});

function playDelayed(base64Audio) {
  if (!audioOut) return;
  const raw = atob(base64Audio);
  const samples = new Float32Array(raw.length >> 1);
  for (let i = 0; i < samples.length; i++) {
    const v = raw.charCodeAt(2 * i) | (raw.charCodeAt(2 * i + 1) << 8);  // 16-bit little endian
    samples[i] = (v >= 0x8000 ? v - 0x10000 : v) / 0x8000;
  }
  if (!samples.length) return;
  const buffer = audioOut.createBuffer(1, samples.length, PATIENT_AUDIO_RATE);
  buffer.copyToChannel(samples, 0);
  const source = audioOut.createBufferSource();
  source.buffer = buffer;
  source.connect(audioOut.destination);
  // A new sentence starts lipSyncMs from now; chunks of the same sentence follow back to back
  playHead = Math.max(playHead, audioOut.currentTime + lipSyncMs / 1000);
  source.start(playHead);
  playHead += buffer.duration;
  queued.push(source);
  source.onended = () => { queued = queued.filter((s) => s !== source); };
}

function stopDelayed() {
  for (const source of queued) {
    try { source.stop(); } catch (error) { /* already ended */ }
  }
  queued = [];
  playHead = 0;
}

function applyUnrealRouting() {
  $('#metahuman-toggle').hidden = unrealListeners === 0;
  $('#lipsync-row').hidden = !watchingVideo();
  if (!conversation) return;
  conversation.setVolume({ volume: useMetaHuman() || delayedVoice() ? 0 : 1 });
  $('#conversation-note').textContent = useMetaHuman() ? 'The patient speaks through the MetaHuman.' : '';
}

function openStage() {
  try {
    stage = new WebSocket(stageUrl());
  } catch (error) {
    stage = null;
    return;
  }
  stage.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'status') {
      unrealListeners = message.unreal || 0;
      applyUnrealRouting();
    }
  };
  stage.onclose = () => { stage = null; unrealListeners = 0; applyUnrealRouting(); };
}

function sendToStage(message) {
  if (stage && stage.readyState === WebSocket.OPEN) stage.send(JSON.stringify(message));
}

function setConversationState(state, label) {
  $('#conversation-state').dataset.state = state;
  $('#conversation-state').textContent = label;
}

function addBubble(role, text, responseId) {
  const log = $('#conversation-log');
  log.querySelector('.conversation-empty')?.remove();
  let bubble = responseId ? agentBubbles.get(responseId) : null;
  if (!bubble) {
    bubble = document.createElement('div');
    bubble.className = 'bubble ' + (role === 'agent' ? 'agent' : 'user');
    bubble.innerHTML = '<small></small><span></span>';
    bubble.querySelector('small').textContent = role === 'agent' ? 'Patient' : 'You';
    log.appendChild(bubble);
    if (responseId) agentBubbles.set(responseId, bubble);
  }
  bubble.querySelector('span').textContent = text;
  log.scrollTop = log.scrollHeight;
}

async function loadSavedCases() {
  try {
    const response = await fetch('/api/cases');
    if (!response.ok) return;
    const { cases } = await response.json();
    const select = $('#saved-case');
    select.replaceChildren(...cases.map((c) => {
      const option = document.createElement('option');
      option.value = c.case_id;
      option.textContent = c.name + ', ' + c.age + '  (' + c.case_id + ')';
      return option;
    }));
    if (cases.length) select.value = cases[cases.length - 1].case_id;  // newest first choice
    $('#saved-patients').hidden = cases.length === 0;
  } catch (error) {
    // The picker is optional; the form still works without it
  }
}
loadSavedCases();

$('#saved-start').addEventListener('click', () => {
  const caseId = $('#saved-case').value;
  if (caseId) startConversation(caseId, $('#saved-start'));
});

$('#start-button').addEventListener('click', () => {
  if (savedCaseId) startConversation(savedCaseId, $('#start-button'));
});

async function startConversation(caseId, button) {
  button.disabled = true;
  $('#status').textContent = 'Loading the patient…';
  try {
    const response = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_id: caseId }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not start the conversation.');
    liveAgentId = result.agent_id;
    $('#status').textContent = 'Live now: ' + result.name + ', ' + result.age;
    $('#conversation-patient').textContent = 'Live now: ' + result.name + ', ' + result.age;
    $('#talk-link').href = result.talk_url || '#';
    $('#talk-link').hidden = !result.talk_url;
    $('#conversation-note').textContent = liveAgentId ? '' : 'Set ELEVENLABS_AGENT_ID in engine/.env to talk in the browser.';
    $('#conversation-panel').hidden = false;
    openVideo();
    $('#conversation-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    $('#status').textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

$('#talk-button').addEventListener('click', async () => {
  if (!liveAgentId || conversation) return;
  if (!window.isSecureContext) {
    $('#conversation-note').textContent = 'The microphone only works over HTTPS (or localhost). Open this page through its https:// address.';
    return;
  }
  $('#talk-button').disabled = true;
  $('#conversation-note').textContent = '';
  setConversationState('connecting', 'Connecting…');
  try {
    // Created during the click, so the browser lets it play sound
    audioOut = audioOut || new AudioContext();
    await audioOut.resume();
    const { Conversation } = await import(ELEVENLABS_CLIENT_URL);
    openStage();
    conversation = await Conversation.startSession({
      agentId: liveAgentId,
      // WebSocket mode delivers the patient's raw PCM in onAudio, which we relay to Unreal.
      connectionType: 'websocket',
      // Always to the MetaHuman (when one is connected) so its lips move; audible only if this page asks
      onAudio: (base64Audio) => {
        sendToStage({ type: 'audio', sample_rate: PATIENT_AUDIO_RATE, pcm_b64: base64Audio, audible: useMetaHuman() });
        if (delayedVoice()) playDelayed(base64Audio);
      },
      // The student talked over the patient: drop the rest of the answer here and in Unreal
      onInterruption: () => {
        stopDelayed();
        sendToStage({ type: 'interrupt' });
      },
      onConnect: () => setConversationState('listening', 'Listening'),
      onDisconnect: () => {
        conversation = null;
        stopDelayed();
        if (stage) stage.close();
        setConversationState('idle', 'Not connected');
        $('#talk-button').hidden = false;
        $('#talk-button').disabled = false;
        $('#end-button').hidden = true;
      },
      onModeChange: ({ mode }) => {
        setConversationState(mode, mode === 'speaking' ? 'Patient is speaking' : 'Listening');
        // The MetaHuman looks attentive while the student talks
        if (mode === 'listening') sendToStage({ type: 'state', state: 'listening' });
      },
      onMessage: (payload) => {
        const role = payload.role || (payload.source === 'ai' ? 'agent' : 'user');
        addBubble(role, payload.message, role === 'agent' ? payload.response_id : null);
      },
      onError: (message) => {
        $('#conversation-note').textContent = String(message || 'Conversation error.');
      },
    });
    $('#talk-button').hidden = true;
    $('#end-button').hidden = false;
    applyUnrealRouting();
  } catch (error) {
    conversation = null;
    setConversationState('idle', 'Not connected');
    $('#conversation-note').textContent = error && error.name === 'NotAllowedError'
      ? 'Microphone access was blocked. Allow it in the browser and try again.'
      : 'Could not start the conversation: ' + (error && error.message ? error.message : error);
  } finally {
    $('#talk-button').disabled = false;
  }
});

$('#end-button').addEventListener('click', async () => {
  if (conversation) await conversation.endSession();
});

$('#mood').value = 'neutral';
$('#mapping-copy').textContent = disclosureProfiles[$('#personality-type').value];
renderCharacters();
showStep(0);
