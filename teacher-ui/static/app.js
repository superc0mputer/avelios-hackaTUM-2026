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

function applyUnrealRouting() {
  if (!conversation) return;
  conversation.setVolume({ volume: unrealListeners > 0 ? 0 : 1 });
  $('#conversation-note').textContent = unrealListeners > 0 ? 'The patient speaks through the MetaHuman.' : '';
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

// The packaged app: the agent lives in the user's ElevenLabs account and is reached by signed URL.
let liveSigned = false;

async function startCase(caseId, button) {
  if (!caseId) return;
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
    liveSigned = Boolean(result.signed);
    $('#status').textContent = 'Live now: ' + result.name + ', ' + result.age;
    $('#conversation-patient').textContent = 'Live now: ' + result.name + ', ' + result.age;
    $('#talk-link').href = result.talk_url || '#';
    $('#talk-link').hidden = !result.talk_url;
    let note = '';
    if (result.voice_error) note = 'Voice setup problem: ' + result.voice_error;
    else if (liveSigned && !liveAgentId) note = 'Add your ElevenLabs key under API KEYS to talk.';
    else if (!liveAgentId) note = 'Set ELEVENLABS_AGENT_ID in engine/.env to talk in the browser.';
    $('#conversation-note').textContent = note;
    $('#conversation-panel').hidden = false;
    $('#conversation-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    $('#status').textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

$('#start-button').addEventListener('click', () => startCase(savedCaseId, $('#start-button')));
$('#example-start').addEventListener('click', () => startCase($('#example-case').value, $('#example-start')));

// ---- API keys (packaged app): the user's own OpenAI and ElevenLabs keys ----
function showKeyState(status) {
  $('#openai-key-state').textContent = status.openai ? 'Saved on this computer.' : '';
  $('#elevenlabs-key-state').textContent = status.elevenlabs ? 'Saved on this computer.' : '';
  $('#examples-panel').hidden = !status.ready;
}

async function loadExamples() {
  try {
    const response = await fetch('/api/examples');
    if (!response.ok) return;
    const { cases, loaded } = await response.json();
    const select = $('#example-case');
    select.replaceChildren();
    for (const item of cases || []) {
      if (item.error) continue;
      const option = document.createElement('option');
      option.value = item.case_id;
      option.textContent = item.name + (item.age ? ', ' + item.age : '') + ' (' + item.case_id + ')';
      option.selected = item.case_id === loaded;
      select.appendChild(option);
    }
  } catch (error) { /* the case list is optional */ }
}

async function loadKeyStatus() {
  try {
    const response = await fetch('/api/keys');
    if (!response.ok) return;
    const status = await response.json();
    if (!status.app) return;  // the team's own setup uses engine/.env instead
    $('#keys-toggle').hidden = false;
    $('#keys-panel').hidden = status.openai && status.elevenlabs;
    showKeyState(status);
    if (status.ready) loadExamples();
  } catch (error) { /* voice server not running: the case form still works */ }
}

$('#keys-toggle').addEventListener('click', () => {
  $('#keys-panel').hidden = !$('#keys-panel').hidden;
  if (!$('#keys-panel').hidden) $('#keys-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
});

$('#keys-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('#keys-save');
  button.disabled = true;
  $('#keys-note').textContent = 'Checking the keys and setting up your patient agent…';
  try {
    const response = await fetch('/api/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ openai_key: $('#openai-key').value, elevenlabs_key: $('#elevenlabs-key').value }),
    });
    const result = await response.json();
    if (!response.ok) {
      const errors = result.detail && result.detail.errors;
      throw new Error(errors ? Object.values(errors).join(' ') : (result.detail || result.error || 'Could not save the keys.'));
    }
    $('#openai-key').value = '';
    $('#elevenlabs-key').value = '';
    showKeyState(result);
    const credits = result.checks && result.checks.elevenlabs && result.checks.elevenlabs.credits_left;
    $('#keys-note').textContent = result.voice_error
      ? 'Keys saved, but the voice could not be set up: ' + result.voice_error
      : 'Keys saved.' + (credits != null ? ' ElevenLabs credits left: ' + credits.toLocaleString() + '.' : '');
    if (result.ready) {
      loadExamples();
      if (!result.voice_error) $('#keys-panel').hidden = true;
      showToast('Ready. Pick a patient and start talking.');
    }
  } catch (error) {
    $('#keys-note').textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$('#keys-forget').addEventListener('click', async () => {
  const response = await fetch('/api/keys', { method: 'DELETE' });
  if (response.ok) {
    showKeyState(await response.json());
    $('#keys-note').textContent = 'The keys were removed from this computer.';
  }
});

loadKeyStatus();

async function sessionTarget() {
  if (!liveSigned) return { agentId: liveAgentId };
  const response = await fetch('/api/signed-url');
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || result.error || 'Could not get a conversation link.');
  return { signedUrl: result.signed_url };
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
    const { Conversation } = await import(ELEVENLABS_CLIENT_URL);
    const target = await sessionTarget();
    openStage();
    conversation = await Conversation.startSession({
      ...target,
      // WebSocket mode delivers the patient's raw PCM in onAudio, which we relay to Unreal.
      connectionType: 'websocket',
      onAudio: (base64Audio) => sendToStage({ type: 'audio', sample_rate: PATIENT_AUDIO_RATE, pcm_b64: base64Audio }),
      onConnect: () => setConversationState('listening', 'Listening'),
      onDisconnect: () => {
        conversation = null;
        if (stage) stage.close();
        setConversationState('idle', 'Not connected');
        $('#talk-button').hidden = false;
        $('#talk-button').disabled = false;
        $('#end-button').hidden = true;
      },
      onModeChange: ({ mode }) => setConversationState(mode, mode === 'speaking' ? 'Patient is speaking' : 'Listening'),
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
