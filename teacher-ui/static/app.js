const $ = (selector) => document.querySelector(selector);

const disclosureProfiles = {
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

// Load the saved case into the patient engine, then open the ElevenLabs conversation.
$('#start-button').addEventListener('click', async () => {
  if (!savedCaseId) return;
  const button = $('#start-button');
  // Open the tab inside the click so the browser does not block it; navigate once loaded.
  const tab = window.open('about:blank', '_blank');
  button.disabled = true;
  $('#status').textContent = 'Loading the patient…';
  try {
    const response = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_id: savedCaseId }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not start the conversation.');
    $('#status').textContent = 'Live now: ' + result.name + ', ' + result.age;
    if (result.talk_url && tab) {
      tab.location.href = result.talk_url;
    } else {
      if (tab) tab.close();
      showToast('Loaded ' + result.name + '. Set ELEVENLABS_AGENT_ID to open the conversation.', true);
    }
  } catch (error) {
    if (tab) tab.close();
    $('#status').textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$('#mood').value = 'neutral';
$('#mapping-copy').textContent = disclosureProfiles[$('#personality-type').value];
renderCharacters();
showStep(0);
