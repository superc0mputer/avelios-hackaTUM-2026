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

// Ages: how old each MetaHuman looks (unreal/VIPPatient/Scripts/patients.json). Unreal uses the
// chosen face if the case age is within 15 years, otherwise the closest age of the same gender.
const characters = [
  { id: 'man-01', label: 'Man 01 · about 50', gender: 'male', age: 50 },
  { id: 'man-02', label: 'Man 02 · about 72', gender: 'male', age: 72 },
  { id: 'man-03', label: 'Man 03 · about 25', gender: 'male', age: 25 },
  { id: 'woman-01', label: 'Woman 01 · about 58', gender: 'female', age: 58 },
  { id: 'woman-02', label: 'Woman 02 · about 76', gender: 'female', age: 76 },
  { id: 'woman-03', label: 'Woman 03 · about 28', gender: 'female', age: 28 },
];
const categories = ['symptoms', 'medical_history', 'medications', 'allergies', 'family_history', 'lifestyle', 'secrets'];
const stepTitles = ['Patient profile', 'Personality & mood', 'Condition', 'Clinical facts'];
const stepHints = [
  'Start with the patient’s identity and diagnosis.',
  'Choose how the patient behaves and feels at the start.',
  'Choose how the illness shows on the patient.',
  'Add the facts the patient can share during the interview.',
];
let currentStep = 0;
let toastTimer;
let savedCaseId = null;
let savedCaseData = null;
let activeRole = null;
let timerHandle = null;
let activeSubmission = false;
const STUDENT_CASES_KEY = 'vip-completed-cases';

function showOnly(screenId) {
  ['role-screen', 'teacher-shell', 'student-cases-screen', 'briefing-screen', 'interview-screen']
    .forEach((id) => { $('#' + id).hidden = id !== screenId; });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function stopTimer() {
  if (timerHandle) clearInterval(timerHandle);
  timerHandle = null;
}

function runTimer(seconds, outputId, onDone) {
  stopTimer();
  let remaining = seconds;
  const paint = () => {
    const minutes = Math.floor(remaining / 60).toString().padStart(2, '0');
    const secondsLeft = (remaining % 60).toString().padStart(2, '0');
    $('#' + outputId).textContent = minutes + ':' + secondsLeft;
  };
  paint();
  timerHandle = setInterval(() => {
    remaining -= 1;
    paint();
    if (remaining <= 0) {
      stopTimer();
      onDone();
    }
  }, 1000);
}

function selectRole(role) {
  activeRole = role;
  $('#switch-role-button').hidden = false;
  $('#top-context-label').textContent = role === 'teacher' ? 'Teacher workspace' : 'Student practice';
  $('#switch-role-button').textContent = 'SWITCH ROLE';
  if (role === 'teacher') {
    showOnly('teacher-shell');
    $('#switch-role-button').textContent = 'TEACHER · SWITCH';
    showTeacherTab('cases');
  } else {
    $('#switch-role-button').textContent = 'STUDENT · SWITCH';
    $('#student-display-name').value = localStorage.getItem('vip-student-name') || '';
    showOnly('student-cases-screen');
    loadStudentCases();
  }
}

function showTeacherTab(tab) {
  $('#authoring-screen').hidden = tab !== 'cases';
  $('#teacher-dashboard').hidden = tab !== 'dashboard';
  document.querySelectorAll('[data-teacher-tab]').forEach((button) => {
    button.classList.toggle('active', button.dataset.teacherTab === tab);
  });
  if (tab === 'dashboard') loadTeacherDashboard();
}

function completedCaseIds() {
  try { return new Set(JSON.parse(localStorage.getItem(STUDENT_CASES_KEY) || '[]')); }
  catch { return new Set(); }
}

async function loadStudentCases() {
  const list = $('#student-case-list');
  list.replaceChildren();
  try {
    const response = await fetch('/api/student-cases');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not load the patient list.');
    const completed = completedCaseIds();
    if (!result.cases.length) {
      list.innerHTML = '<div class="empty-state"><span>✦</span><h2>No patients are ready yet</h2><p>Your teacher will add practice cases here.</p></div>';
      return;
    }
    result.cases.forEach((patient, index) => {
      const done = completed.has(patient.case_id);
      const card = document.createElement('article');
      card.className = 'student-case-card' + (done ? ' completed' : '');
      const avatar = document.createElement('div');
      avatar.className = 'case-avatar';
      avatar.dataset.characterId = patient.character_id || '';
      avatar.textContent = patient.name.split(/\s+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase();
      const copy = document.createElement('div');
      copy.className = 'student-case-copy';
      const eyebrow = document.createElement('p');
      eyebrow.className = 'eyebrow';
      eyebrow.textContent = 'PATIENT ' + String(index + 1).padStart(2, '0');
      const name = document.createElement('h2');
      name.textContent = patient.name;
      const detail = document.createElement('p');
      detail.textContent = [patient.age ? patient.age + ' years old' : '', patient.gender].filter(Boolean).join(' · ');
      copy.append(eyebrow, name, detail);
      const start = document.createElement('button');
      start.className = done ? 'case-complete-button' : 'save-button';
      start.type = 'button';
      start.textContent = done ? 'Completed ✓' : 'Start case →';
      start.disabled = done;
      start.addEventListener('click', () => openBriefing(patient.case_id));
      card.append(avatar, copy, start);
      list.append(card);
    });
  } catch (error) {
    showToast(error.message, true);
  }
}

async function openBriefing(caseId) {
  const studentName = $('#student-display-name').value.trim();
  if (!studentName) {
    $('#student-display-name').focus();
    showToast('Enter your name or ID before starting a patient.', true);
    return;
  }
  localStorage.setItem('vip-student-name', studentName);
  try {
    const response = await fetch('/api/briefing?case_id=' + encodeURIComponent(caseId));
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not load the patient briefing.');
    savedCaseId = caseId;
    activeSubmission = false;
    savedCaseData = { patient: result.patient, character_id: result.character_id };
    $('#briefing-name').textContent = result.patient.name;
    $('#briefing-demographics').textContent = [result.patient.age ? result.patient.age + ' years old' : '', result.patient.gender].filter(Boolean).join(' · ');
    $('#briefing-avatar-initials').textContent = result.patient.name.split(/\s+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase();
    $('#briefing-avatar').dataset.characterId = result.character_id || '';
    showOnly('briefing-screen');
    runTimer(120, 'briefing-timer', beginStudentInterview);
  } catch (error) {
    showToast(error.message, true);
  }
}

function beginStudentInterview() {
  if (!savedCaseId || activeSubmission) return;
  stopTimer();
  enterInterviewScreen(savedCaseData, savedCaseId, true);
}

async function loadTeacherDashboard() {
  try {
    const [casesResponse, resultsResponse] = await Promise.all([
      fetch('/api/cases'), fetch('/api/practice-results'),
    ]);
    const caseData = await casesResponse.json();
    const resultData = await resultsResponse.json();
    if (!casesResponse.ok || !resultsResponse.ok) throw new Error('Could not load teacher dashboard.');
    $('#stat-responses').textContent = resultData.submissions.length;
    $('#stat-ungraded').textContent = resultData.submissions.filter((item) => !item.grade).length;
    $('#stat-cases').textContent = caseData.cases.length;
    $('#response-count').textContent = resultData.submissions.length;
    const list = $('#response-list');
    list.replaceChildren();
    if (!resultData.submissions.length) {
      list.innerHTML = '<div class="empty-state"><span>▤</span><h2>No student responses yet</h2><p>When students finish an interview, their findings will appear here.</p></div>';
      return;
    }
    resultData.submissions.slice().reverse().forEach((submission) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'response-row';
      button.innerHTML = '<span class="response-mark">' + (submission.grade ? '✓' : '·') + '</span><span class="response-row-copy"><strong></strong><small></small></span><span class="response-grade"></span>';
      button.querySelector('strong').textContent = submission.student_name || 'Student';
      button.querySelector('small').textContent = submission.patient_name + ' · ' + submission.case_id;
      button.querySelector('.response-grade').textContent = submission.grade ? submission.grade + '/5' : 'Review';
      button.addEventListener('click', () => showSubmissionForGrading(submission, button));
      list.append(button);
    });
  } catch (error) {
    showToast(error.message, true);
  }
}

function showSubmissionForGrading(submission, button) {
  document.querySelectorAll('.response-row').forEach((row) => row.classList.remove('selected'));
  button.classList.add('selected');
  $('.grading-empty').hidden = true;
  $('#grading-form').hidden = false;
  $('#grading-submission-id').value = submission.submission_id;
  $('#grading-student-title').textContent = submission.student_name || 'Student';
  $('#grading-case-title').textContent = submission.patient_name + ' · ' + submission.case_id;
  $('#review-disease').textContent = submission.student_diagnosis || 'No disease recorded before time ended.';
  $('#review-symptoms').textContent = submission.symptoms || 'No symptoms recorded.';
  $('#review-notes').textContent = submission.notes || 'No notes added.';
  $('#review-correct-diagnosis').textContent = submission.correct_diagnosis;
  $('#teacher-grade').value = submission.grade || '';
  $('#teacher-feedback').value = submission.feedback || '';
}

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
    presentation: makePresentation(),
    ...facts,
  };
}

// How the illness shows on the MetaHuman; empty fields are left out.
function makePresentation() {
  const presentation = {};
  const pain = $('#pain').value.trim();
  if (pain !== '') presentation.pain = Number(pain);
  if ($('#breathing').value) presentation.breathing = $('#breathing').value;
  if ($('#discomfort').value) presentation.discomfort = Number($('#discomfort').value);
  const signs = [...document.querySelectorAll('#visible-signs input:checked')].map((box) => box.value);
  if (signs.length) presentation.visible_signs = signs;
  return presentation;
}

function showToast(message, error = false) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.toggle('error', error);
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 4500);
}

function enterInterviewScreen(caseData, caseId, isStudent = false) {
  savedCaseData = caseData;
  savedCaseId = caseId;
  activeSubmission = false;
  agentBubbles.clear();
  $('#conversation-log').innerHTML = '<p class="conversation-empty">The patient is waiting. Start the interview when you are ready.</p>';
  $('#student-notes-form').reset();
  $('#student-name').value = localStorage.getItem('vip-student-name') || '';
  $('#student-notes-form').hidden = false;
  $('#submission-summary').hidden = true;
  $('#talk-button').hidden = false;
  $('#talk-button').disabled = true;
  $('#end-button').hidden = true;
  $('#retry-load-button').hidden = true;
  $('#conversation-note').textContent = '';
  setConversationState('idle', 'Not connected');
  $('#practice-patient-name').textContent = caseData.patient.name;
  const genderNames = { male: 'Man', female: 'Woman', non_binary: 'Non-binary' };
  const gender = genderNames[caseData.patient.gender] || caseData.patient.gender;
  $('#practice-patient-summary').textContent = caseData.patient.age + ' years · ' + gender;
  const character = characters.find((item) => item.id === caseData.character_id);
  $('#practice-character-tag').textContent = character ? character.label : 'Patient character';
  $('#stage-avatar').dataset.characterId = caseData.character_id || '';
  $('#stage-label').dataset.connected = 'false';
  $('#unreal-stage-status').textContent = 'Preview only · Unreal display not connected';
  $('#conversation-patient').textContent = 'Start by introducing yourself and inviting the patient to speak.';
  showOnly('interview-screen');
  $('#interview-screen').scrollIntoView({ behavior: 'smooth', block: 'start' });
  loadPatient();
  if (isStudent) runTimer(600, 'interview-timer', () => submitStudentNotes(true));
}

async function loadPatient() {
  if (!savedCaseId) return;
  $('#retry-load-button').hidden = true;
  $('#talk-button').disabled = true;
  setConversationState('connecting', 'Preparing patient…');
  $('#conversation-note').textContent = '';
  try {
    const response = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_id: savedCaseId }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not prepare the patient.');
    liveAgentId = result.agent_id;
    $('#conversation-patient').textContent = 'Patient ready: ' + result.name + ', ' + result.age + '. The patient waits for you to speak first.';
    $('#talk-link').href = result.talk_url || '#';
    $('#talk-link').hidden = !result.talk_url;
    $('#talk-button').disabled = !liveAgentId;
    setConversationState('ready', 'Ready');
    $('#unreal-stage-status').textContent = 'Preview · ' + (savedCaseData.character_id || 'selected character');
  } catch (error) {
    liveAgentId = null;
    setConversationState('idle', 'Not connected');
    $('#conversation-note').textContent = error.message;
    $('#retry-load-button').hidden = false;
    $('#unreal-stage-status').textContent = 'Preview only · Unreal display not connected';
  }
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
  const caseData = makeCase();
  const button = $('#save-button');
  button.disabled = true;
  $('#status').textContent = 'Validating and saving…';
  try {
    const response = await fetch('/api/cases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(caseData),
    });
    const result = await response.json();
    if (!response.ok) {
      const details = (result.details || []).slice(0, 5).join(' ');
      throw new Error(details || result.error || 'Could not save the case.');
    }
    $('#status').textContent = 'Saved ' + result.saved_as;
    $('#case-form').reset();
    updateGenderFields();
    showStep(0);
    showTeacherTab('dashboard');
    showToast('Case saved. It is now available to students.');
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
  $('#stage-label').dataset.connected = String(unrealListeners > 0);
  $('#unreal-stage-status').textContent = unrealListeners > 0
    ? 'Unreal display connected'
    : 'Preview only · Unreal display not connected';
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
      $('#stage-label').dataset.connected = String(unrealListeners > 0);
      $('#unreal-stage-status').textContent = unrealListeners > 0
        ? 'Unreal display connected'
        : 'Preview only · Unreal display not connected';
      applyUnrealRouting();
    }
  };
  stage.onclose = () => {
    stage = null;
    unrealListeners = 0;
    $('#stage-label').dataset.connected = 'false';
    $('#unreal-stage-status').textContent = 'Preview only · Unreal display not connected';
    applyUnrealRouting();
  };
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

$('#retry-load-button').addEventListener('click', loadPatient);

async function submitStudentNotes(timedOut = false) {
  if (activeSubmission) return;
  if (!timedOut && !$('#student-notes-form').reportValidity()) return;
  activeSubmission = true;
  const submit = $('#submit-notes');
  submit.disabled = true;
  submit.textContent = 'Saving for professor…';
  try {
    const response = await fetch('/api/practice-results', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        case_id: savedCaseId,
        student_name: $('#student-name').value.trim(),
        student_diagnosis: $('#student-diagnosis').value.trim(),
        symptoms: $('#student-symptoms').value.trim(),
        notes: $('#student-notes').value.trim(),
        timed_out: timedOut,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not save your notes.');
    stopTimer();
    const completed = completedCaseIds();
    completed.add(savedCaseId);
    localStorage.setItem(STUDENT_CASES_KEY, JSON.stringify([...completed]));
    if (conversation) {
      try {
        await conversation.endSession();
      } catch {
        // The saved submission remains available even if the voice session closes unexpectedly.
      }
    }
    showToast(timedOut ? 'Time is up. Your interview has been submitted.' : 'Your interview has been submitted.');
    activeSubmission = false;
    showOnly('student-cases-screen');
    loadStudentCases();
  } catch (error) {
    showToast(error.message, true);
    activeSubmission = false;
    submit.disabled = false;
    submit.innerHTML = 'Submit findings <span>→</span>';
  }
}

$('#student-notes-form').addEventListener('submit', (event) => {
  event.preventDefault();
  submitStudentNotes(false);
});

$('#end-interview-button').addEventListener('click', () => submitStudentNotes(false));

$('#begin-interview-button').addEventListener('click', beginStudentInterview);

$('#briefing-back-button').addEventListener('click', () => {
  stopTimer();
  showOnly('student-cases-screen');
});

document.querySelectorAll('[data-role]').forEach((button) => {
  button.addEventListener('click', () => selectRole(button.dataset.role));
});

document.querySelectorAll('[data-teacher-tab]').forEach((button) => {
  button.addEventListener('click', () => showTeacherTab(button.dataset.teacherTab));
});

$('#switch-role-button').addEventListener('click', async () => {
  stopTimer();
  if (conversation) {
    try { await conversation.endSession(); } catch { /* leave role picker available */ }
  }
  showOnly('role-screen');
  $('#switch-role-button').hidden = true;
  $('#top-context-label').textContent = 'Virtual patient learning';
});

$('#dashboard-create-case').addEventListener('click', () => showTeacherTab('cases'));

$('#student-display-name').addEventListener('input', (event) => {
  localStorage.setItem('vip-student-name', event.target.value.trim());
});

$('#grading-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('#save-grade-button');
  button.disabled = true;
  try {
    const response = await fetch('/api/grade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        submission_id: $('#grading-submission-id').value,
        grade: $('#teacher-grade').value,
        feedback: $('#teacher-feedback').value.trim(),
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not save review.');
    showToast('Grade and feedback saved.');
    await loadTeacherDashboard();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

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
    openStage();
    conversation = await Conversation.startSession({
      agentId: liveAgentId,
      // WebSocket mode delivers the patient's raw PCM in onAudio, which we relay to Unreal.
      connectionType: 'websocket',
      onAudio: (base64Audio) => sendToStage({ type: 'audio', sample_rate: PATIENT_AUDIO_RATE, pcm_b64: base64Audio }),
      // The student talked over the patient: the MetaHuman stops speaking too
      onInterruption: () => sendToStage({ type: 'interrupt' }),
      onConnect: () => setConversationState('listening', 'Listening'),
      onDisconnect: () => {
        conversation = null;
        sendToStage({ type: 'state', state: 'idle' });
        if (stage) stage.close();
        setConversationState('idle', 'Not connected');
        $('#talk-button').hidden = false;
        $('#talk-button').disabled = false;
        $('#end-button').hidden = true;
      },
      onModeChange: ({ mode }) => {
        setConversationState(mode, mode === 'speaking' ? 'Patient is speaking' : 'Listening');
        // The MetaHuman looks attentive while the student talks (thinking comes from the voice server)
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
