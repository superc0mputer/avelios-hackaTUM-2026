// VIP · Virtual Interview Patient — the website for teachers and students.
// One file, no build step. Sections: helpers · reference data · teacher (library, builder, responses)
// · student (patients, briefing, consultation, wrap-up, review) · start-up.
'use strict';

/* =========================================================================================
   helpers
   ========================================================================================= */
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value == null) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child != null && child !== false) node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function api(path, options = {}) {
  const init = { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } };
  if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error('The VIP server is not reachable. Is it still running?');
  }
  let data = {};
  try { data = await response.json(); } catch { /* empty body */ }
  if (!response.ok) {
    const details = Array.isArray(data.details) ? ' ' + data.details.slice(0, 4).join(' ') : '';
    const error = new Error((data.error || data.detail || `Request failed (${response.status}).`) + details);
    error.status = response.status;
    throw error;
  }
  return data;
}

let toastTimer;
function toast(message, isError = false) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.toggle('error', isError);
  node.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('show'), isError ? 6500 : 4000);
}

/** A small modal. actions: [{label, value, kind}] -> resolves with the chosen value ('' on Esc). */
function ask(title, body, actions) {
  const dialog = $('#confirm-dialog');
  if (dialog.open) dialog.close('');
  $('#confirm-title').textContent = title;
  $('#confirm-body').textContent = body;
  $('#confirm-actions').replaceChildren(...actions.map((action) =>
    el('button', { class: 'btn ' + (action.kind ? 'btn-' + action.kind : ''), value: action.value, text: action.label })));
  dialog.returnValue = '';
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener('close', () => resolve(dialog.returnValue), { once: true }));
}

function clock(seconds) {
  const s = Math.max(0, seconds);
  return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
}

function storage(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { /* private window: only a convenience */ }
  return null;
}

/* =========================================================================================
   reference data
   ========================================================================================= */
// The six MetaHumans (unreal/VIPPatient/Scripts/patients.json). Ages are how old each face looks.
// Unreal uses the chosen face if the case age is within 15 years, otherwise the closest age of the gender.
const FACES = [
  { id: 'man-01', name: 'Bruce', gender: 'male', age: 50, skin: '#c8987a', hair: '#4a3a2e', shirt: '#3f6f8f', bg: '#e1ecf2', style: 'short' },
  { id: 'man-02', name: 'Walter', gender: 'male', age: 72, skin: '#e2bba3', hair: '#d6d1ca', shirt: '#647a6c', bg: '#ebeee7', style: 'receding' },
  { id: 'man-03', name: 'Trey', gender: 'male', age: 25, skin: '#8a573c', hair: '#1d1511', shirt: '#2f4b66', bg: '#e2e9f2', style: 'short' },
  { id: 'woman-01', name: 'Lani', gender: 'female', age: 58, skin: '#b88264', hair: '#33261f', shirt: '#86566b', bg: '#f0e6ea', style: 'long' },
  { id: 'woman-02', name: 'Grace', gender: 'female', age: 76, skin: '#e8c7b2', hair: '#e4e0da', shirt: '#5b7690', bg: '#e6edf3', style: 'bob' },
  { id: 'woman-03', name: 'Sunita', gender: 'female', age: 28, skin: '#a46d4c', hair: '#15100d', shirt: '#2d7770', bg: '#e1f0ee', style: 'long' },
];
const faceById = (id) => FACES.find((face) => face.id === id) || FACES[0];

/** The face Unreal will actually show for this case (VIPCase.cpp rule). */
function effectiveFace(characterId, age, gender) {
  const chosen = FACES.find((face) => face.id === characterId);
  const years = Number(age);
  if (chosen && (!years || Math.abs(chosen.age - years) <= 15)) return chosen;
  const pool = FACES.filter((face) => face.gender === gender);
  const candidates = pool.length ? pool : FACES;
  if (!years) return chosen || candidates[0];
  return candidates.reduce((best, face) => (Math.abs(face.age - years) < Math.abs(best.age - years) ? face : best));
}

function portrait(characterId) {
  const f = faceById(characterId);
  const back = {
    long: `<path d="M19 29c0-12 6-19 13-19s13 7 13 19v15c-3 2-6 3-8 3V31H27v16c-2 0-5-1-8-3z" fill="${f.hair}"/>`,
    bob: `<path d="M19 30c0-12 6-19 13-19s13 7 13 19v7c-2 1-4 1-6 1V31H25v7c-2 0-4 0-6-1z" fill="${f.hair}"/>`,
  }[f.style] || '';
  const front = {
    short: `<path d="M20.5 25c-.5-9 4.5-15 11.5-15s12 6 11.5 15c-2-4-6-6.5-11.5-6.5S22.5 21 20.5 25z" fill="${f.hair}"/>`,
    receding: `<path d="M21 26c-.5-4 .5-7 2.5-9-.3 3 0 5 .5 7zM43 26c.5-4-.5-7-2.5-9 .3 3 0 5-.5 7z" fill="${f.hair}"/><path d="M24 17.5c2-3 5-4.5 8-4.5s6 1.5 8 4.5c-2.5-1-5-1.5-8-1.5s-5.5.5-8 1.5z" fill="${f.hair}" opacity=".8"/>`,
    long: `<path d="M20.5 26c.5-9 5-14.5 11.5-14.5S43 17 43.5 26c-3-5.5-7-8-11.5-8s-8.5 2.5-11.5 8z" fill="${f.hair}"/>`,
    bob: `<path d="M20.5 26c.5-9 5-14.5 11.5-14.5S43 17 43.5 26c-3-5-7-7-11.5-7s-8.5 2-11.5 7z" fill="${f.hair}"/>`,
  }[f.style];
  return `<svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" fill="${f.bg}"/>${back}
    <path d="M8 66c1.5-13 11-20 24-20s22.5 7 24 20z" fill="${f.shirt}"/>
    <path d="M27 37h10v9.5c-1.5 2-3.2 3-5 3s-3.5-1-5-3z" fill="${f.skin}" filter="brightness(.9)"/>
    <ellipse cx="32" cy="27.5" rx="11" ry="13" fill="${f.skin}"/>${front}</svg>`;
}
function setPortrait(node, characterId) { node.innerHTML = portrait(characterId); }

const PERSONALITIES = {
  no_preference: { label: 'Ordinary, cooperative', disclosure: 'Answers plainly; shares secrets once the student asks respectfully and specifically.' },
  downplays_everything: { label: 'Minimizing', disclosure: 'Plays things down at first; secrets come out after specific, respectful follow-up.' },
  anxious_talkative: { label: 'Anxious and talkative', disclosure: 'Volunteers context and drifts; secrets need empathetic, focused follow-up.' },
  shy_reserved: { label: 'Shy and reserved', disclosure: 'Brief answers at first; opens up with patience and gentle rapport.' },
  assertive: { label: 'Assertive', disclosure: 'Direct about symptoms; holds back personal details until invited.' },
  distrustful: { label: 'Distrustful', disclosure: 'Guarded until the student explains why they ask and builds trust.' },
  custom: { label: 'Custom', disclosure: 'Follows your description; secrets need trust and specific questions.' },
};
const MOODS = {
  neutral: 'Neutral', sad: 'Sad', fear: 'Scared', anger: 'Angry', confusion: 'Confused', boredom: 'Flat',
  happy: 'Cheerful', surprise: 'Unsettled', disgust: 'Irritated', confidence: 'Confident', excitement: 'Keyed up', playfulness: 'Joking',
};
const BREATHING = { fast_shallow: 'Fast breathing', laboured: 'Laboured breathing', slow_deep: 'Slow, deep breathing' };
const SIGNS = { pale: 'Pale', sweaty: 'Sweaty', jaundice: 'Jaundice', cyanosis: 'Cyanosis', tired: 'Tired', flushed: 'Flushed', red_eyes: 'Red eyes' };
const GENDERS = { male: 'Man', female: 'Woman', non_binary: 'Non-binary' };
const FACT_FIELDS = ['symptoms', 'medical_history', 'medications', 'allergies', 'family_history', 'lifestyle', 'secrets'];

const genderLabel = (gender) => GENDERS[gender] || gender || '';
const personMeta = (age, gender) => [age ? age + ' years' : '', genderLabel(gender)].filter(Boolean).join(' · ');

function conditionChips(presentation = {}) {
  const chips = [];
  if (presentation.pain) chips.push(el('span', { class: 'chip warn', text: `Pain ${presentation.pain}/10` }));
  if (presentation.breathing && BREATHING[presentation.breathing]) chips.push(el('span', { class: 'chip warn', text: BREATHING[presentation.breathing] }));
  (presentation.visible_signs || []).forEach((sign) => chips.push(el('span', { class: 'chip', text: SIGNS[sign] || sign })));
  return chips;
}

/* =========================================================================================
   screens and roles
   ========================================================================================= */
const SCREENS = ['screen-landing', 'screen-teacher', 'screen-student', 'screen-briefing', 'screen-consult', 'screen-wrapup', 'screen-review'];
function show(screenId) {
  SCREENS.forEach((id) => { $('#' + id).hidden = id !== screenId; });
  $('#topbar').hidden = screenId === 'screen-consult';
  document.body.dataset.screen = screenId;
  window.scrollTo({ top: 0 });
}

let role = null;
async function selectRole(next) {
  if (Consult.active) {
    const choice = await ask('Leave the interview?', 'Your notes are not submitted if you leave now.', [
      { label: 'Stay', value: '' }, { label: 'Leave interview', value: 'leave', kind: 'danger' }]);
    if (choice !== 'leave') return;
    Consult.teardown();
  }
  Timers.stop();
  role = next;
  $('#role-switch').hidden = false;
  $$('#role-switch button').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.role === next)));
  if (next === 'teacher') {
    show('screen-teacher');
    Teacher.showView('library');
  } else {
    show('screen-student');
    Student.loadPatients();
  }
}

/* =========================================================================================
   teacher
   ========================================================================================= */
const Teacher = {
  view: 'library',

  showView(view) {
    this.view = view;
    ['library', 'builder', 'responses'].forEach((name) => { $('#view-' + name).hidden = name !== view; });
    $$('.sidenav [data-view]').forEach((button) => {
      if (button.dataset.view === view) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    if (view === 'library') this.loadLibrary();
    if (view === 'responses') Responses.load();
    if (view === 'builder' && Builder.mode === null) Builder.open('new');
    this.refreshCount();
    window.scrollTo({ top: 0 });
  },

  async refreshCount() {
    try {
      const { submissions } = await api('/api/practice-results');
      const open = submissions.filter((s) => !s.grade).length;
      $('#response-count').textContent = open;
      $('#response-count').hidden = !open;
      $('#response-count').title = `${open} awaiting review`;
    } catch { /* the count is a hint only */ }
  },

  async loadLibrary() {
    const own = $('#own-cases');
    const presets = $('#preset-cases');
    try {
      const { cases } = await api('/api/cases');
      const mine = cases.filter((c) => !c.preset);
      $('#own-count').textContent = mine.length ? `${mine.length} case${mine.length === 1 ? '' : 's'}` : '';
      own.replaceChildren(...(mine.length ? mine.map((c) => this.caseCard(c)) : [el('div', { class: 'empty', style: 'grid-column:1/-1' },
        el('h2', { text: 'No cases of your own yet' }),
        el('p', { text: 'Create one from scratch, or duplicate a preset below and adapt it.' }),
        el('button', { class: 'btn btn-primary', type: 'button', text: 'New case', onclick: () => Builder.open('new') }))]));
      presets.replaceChildren(...cases.filter((c) => c.preset).map((c) => this.caseCard(c)));
    } catch (error) {
      toast(error.message, true);
    }
  },

  caseCard(c) {
    const face = el('span', { class: 'portrait' });
    setPortrait(face, effectiveFace(c.character_id, c.age, c.gender).id);
    const chips = [
      el('span', { class: 'chip accent', text: (PERSONALITIES[c.personality] || {}).label || c.personality }),
      el('span', { class: 'chip', text: MOODS[c.mood] || c.mood }),
      ...conditionChips(c.presentation),
    ];
    if (c.secrets) chips.push(el('span', { class: 'chip', text: `${c.secrets} secret${c.secrets === 1 ? '' : 's'}` }));
    const actions = c.preset
      ? [el('button', { class: 'btn btn-sm', type: 'button', text: 'View', onclick: () => Builder.openCase(c.case_id, 'view') }),
         el('button', { class: 'btn btn-sm', type: 'button', text: 'Duplicate', onclick: () => Builder.openCase(c.case_id, 'duplicate') })]
      : [el('button', { class: 'btn btn-sm', type: 'button', text: 'Edit', onclick: () => Builder.openCase(c.case_id, 'edit') }),
         el('button', { class: 'btn btn-sm btn-ghost', type: 'button', text: 'Duplicate', onclick: () => Builder.openCase(c.case_id, 'duplicate') }),
         el('button', { class: 'btn btn-sm btn-ghost', type: 'button', 'aria-label': 'Delete ' + c.name, text: 'Delete', onclick: () => this.deleteCase(c) })];
    return el('article', { class: 'card case-card' },
      el('div', { class: 'case-card-head' }, face, el('div', {},
        el('h3', { text: c.name }), el('p', { text: personMeta(c.age, c.gender) + ' · ' + c.case_id }))),
      el('div', { class: 'dx', title: 'Only teachers see the diagnosis' },
        el('span', { html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>' }),
        el('span', { text: c.diagnosis })),
      el('div', { class: 'chips' }, chips),
      el('div', { class: 'case-card-foot' },
        el('span', { class: 'meta', text: `${c.submissions} response${c.submissions === 1 ? '' : 's'}` }),
        actions));
  },

  async deleteCase(c) {
    const choice = await ask(`Delete ${c.name}?`, `${c.case_id} is removed from the library and students can no longer choose it. This can’t be undone.`,
      [{ label: 'Cancel', value: '' }, { label: 'Delete case', value: 'delete', kind: 'danger' }]);
    if (choice !== 'delete') return;
    try {
      await api('/api/case?case_id=' + encodeURIComponent(c.case_id), { method: 'DELETE' });
      toast(`${c.name} was deleted.`);
      this.loadLibrary();
    } catch (error) {
      toast(error.message, true);
    }
  },
};

/* ---------- the 4-step builder ---------- */
const Builder = {
  mode: null,        // 'new' | 'edit' | 'view' | 'duplicate'
  caseId: null,
  step: 0,
  furthest: 0,
  steps: 4,

  async openCase(caseId, mode) {
    try {
      const { case: data } = await api('/api/case?case_id=' + encodeURIComponent(caseId));
      this.open(mode, data);
    } catch (error) {
      toast(error.message, true);
    }
  },

  open(mode, data = null) {
    this.mode = mode;
    this.caseId = mode === 'edit' || mode === 'view' ? data.case_id : null;
    $('#case-form').reset();
    $('#pain').value = 0;
    if (data) this.fill(data, mode === 'duplicate');
    this.character = data ? data.character_id : null;
    this.userPicked = Boolean(data);
    const titles = {
      new: ['New case', 'Build a patient', 'Four short steps. Students only ever see the name, age and face.'],
      edit: ['Edit case · ' + this.caseId, data && data.patient.name, 'Changes apply the next time a student starts this patient.'],
      view: ['Preset · ' + this.caseId, data && data.patient.name, 'A ready-made scenario.'],
      duplicate: ['New case · copy', data && 'Copy of ' + data.patient.name, 'Adapt anything you like; saving creates a new case.'],
    }[mode];
    [$('#builder-eyebrow').textContent, $('#builder-title').textContent, $('#builder-sub').textContent] = titles;
    const readOnly = mode === 'view';
    $$('#case-form .step-panel').forEach((panel) => { panel.disabled = readOnly; });
    $('#preset-banner').hidden = !readOnly;
    this.furthest = mode === 'new' ? 0 : this.steps - 1;
    this.updateGender();
    this.updatePersonality();
    this.goto(0);
    $('#builder-status').textContent = '';
    $('#builder-status').classList.remove('error');
    if (Teacher.view !== 'builder') {
      Teacher.view = 'builder';
      ['library', 'builder', 'responses'].forEach((name) => { $('#view-' + name).hidden = name !== 'builder'; });
      $$('.sidenav [data-view]').forEach((button) => {
        if (button.dataset.view === 'builder' && mode === 'new') button.setAttribute('aria-current', 'page');
        else button.removeAttribute('aria-current');
      });
    }
    window.scrollTo({ top: 0 });
  },

  fill(data, asCopy) {
    const p = data.patient || {};
    $('#name').value = asCopy ? '' : (p.name || '');
    $('#name').placeholder = asCopy ? (p.name || 'Full name') : 'Full name';
    $('#age').value = p.age || '';
    const known = ['male', 'female', 'non_binary'].includes(p.gender);
    $('#gender').value = known ? p.gender : 'other';
    $('#gender-other').value = known ? '' : (p.gender || '');
    $('#life-story').value = p.life_story || '';
    $('#diagnosis').value = data.diagnosis || '';
    const personality = data.personality || {};
    $('#personality-type').value = personality.type || 'no_preference';
    $('#mood').value = personality.mood || 'neutral';
    $('#personality-description').value = personality.description || '';
    const pres = data.presentation || {};
    $('#pain').value = pres.pain || 0;
    $('#breathing').value = typeof pres.breathing === 'string' ? pres.breathing : '';
    const discomfort = pres.discomfort ? String([0.3, 0.6, 0.9].reduce((a, b) => (Math.abs(b - pres.discomfort) < Math.abs(a - pres.discomfort) ? b : a))) : '';
    $('#discomfort').value = discomfort;
    $$('#visible-signs input').forEach((box) => { box.checked = (pres.visible_signs || []).includes(box.value); });
    FACT_FIELDS.forEach((field) => { $('#' + field.replaceAll('_', '-')).value = (data[field] || []).join('\n'); });
  },

  read() {
    const gender = $('#gender').value === 'other' ? $('#gender-other').value.trim() : $('#gender').value;
    const lines = (id) => $('#' + id).value.split('\n').map((line) => line.trim()).filter(Boolean);
    const presentation = {};
    const pain = Number($('#pain').value);
    if (pain > 0) presentation.pain = pain;
    if ($('#breathing').value) presentation.breathing = $('#breathing').value;
    if ($('#discomfort').value) presentation.discomfort = Number($('#discomfort').value);
    const signs = $$('#visible-signs input:checked').map((box) => box.value);
    if (signs.length) presentation.visible_signs = signs;
    return {
      diagnosis: $('#diagnosis').value.trim(),
      character_id: this.character || effectiveFace(null, $('#age').value, gender).id,
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
      presentation,
      ...Object.fromEntries(FACT_FIELDS.map((field) => [field, lines(field.replaceAll('_', '-'))])),
    };
  },

  goto(step) {
    this.step = step;
    this.furthest = Math.max(this.furthest, step);
    $$('#case-form .step-panel').forEach((panel) => { panel.hidden = Number(panel.dataset.step) !== step; });
    $$('.step-tab').forEach((tab) => {
      const index = Number(tab.dataset.goto);
      tab.classList.toggle('done', index < step || (index <= this.furthest && index !== step));
      if (index === step) tab.setAttribute('aria-current', 'step'); else tab.removeAttribute('aria-current');
      tab.disabled = index > this.furthest;
    });
    const last = step === this.steps - 1;
    const readOnly = this.mode === 'view';
    $('#back-button').hidden = step === 0;
    $('#next-button').hidden = last;
    $('#save-button').hidden = !last || readOnly;
    $('#duplicate-button').hidden = !readOnly;
    $('#save-button').textContent = this.mode === 'edit' ? 'Save changes' : 'Save case';
    this.renderFaces();
    this.renderSummary();
  },

  validStep(step) {
    if (this.mode === 'view') return true;
    const panel = $(`#case-form .step-panel[data-step="${step}"]`);
    for (const field of $$('[required]', panel)) {
      if (!field.checkValidity()) {
        if (panel.hidden) this.goto(step);
        field.reportValidity();
        return false;
      }
    }
    return true;
  },

  next() {
    if (!this.validStep(this.step)) return;
    this.goto(Math.min(this.step + 1, this.steps - 1));
    $('#view-builder').scrollIntoView({ block: 'start', behavior: 'smooth' });
  },

  updateGender() {
    const other = $('#gender').value === 'other';
    $('#gender-other-wrap').hidden = !other;
    $('#gender-other').required = other;
    this.renderFaces();
    this.renderSummary();
  },

  updatePersonality() {
    const type = $('#personality-type').value;
    $('#personality-description').required = type === 'custom';
    $('#description-optional').textContent = type === 'custom' ? '(required for custom)' : '(optional)';
    $('#mapping-copy').textContent = PERSONALITIES[type].disclosure;
    this.renderSummary();
  },

  renderFaces() {
    const gender = $('#gender').value;
    const age = Number($('#age').value) || 0;
    const pool = gender === 'male' || gender === 'female' ? FACES.filter((face) => face.gender === gender) : FACES;
    // Until the teacher picks a face, follow the one closest in age
    if (!this.userPicked) this.character = effectiveFace(null, age, gender === 'male' || gender === 'female' ? gender : '').id;
    if (!pool.some((face) => face.id === this.character)) {
      this.character = effectiveFace(null, age, gender === 'male' || gender === 'female' ? gender : '').id;
      if (!pool.some((face) => face.id === this.character)) this.character = pool[0].id;
    }
    const readOnly = this.mode === 'view';
    $('#face-grid').replaceChildren(...pool.map((face) => {
      const far = age && Math.abs(face.age - age) > 15;
      const pic = el('span', { class: 'portrait' });
      setPortrait(pic, face.id);
      return el('button', {
        class: 'face-option' + (far ? ' far' : ''), type: 'button', disabled: readOnly,
        'aria-pressed': String(face.id === this.character),
        title: far ? `Looks about ${face.age}: Unreal would show a closer-aged face instead` : `Looks about ${face.age}`,
        onclick: () => { this.character = face.id; this.userPicked = true; this.renderFaces(); this.renderSummary(); },
      }, pic, el('span', {}, el('strong', { text: face.name }), el('small', { text: `Looks about ${face.age}` })));
    }));
  },

  renderSummary() {
    $('#pain-out').textContent = $('#pain').value + '/10';
    const data = this.read();
    const face = effectiveFace(data.character_id, data.patient.age, data.patient.gender);
    setPortrait($('#summary-portrait'), face.id);
    $('#summary-name').textContent = data.patient.name || $('#name').placeholder.replace('Full name', 'New patient');
    $('#summary-meta').textContent = personMeta(data.patient.age, data.patient.gender) || 'Age and gender';
    $('#summary-dx').textContent = data.diagnosis || '—';
    $('#summary-personality').textContent = `${PERSONALITIES[data.personality.type].label} · ${MOODS[data.personality.mood] || data.personality.mood}`;
    const condition = conditionChips(data.presentation).map((chip) => chip.textContent);
    $('#summary-condition').textContent = condition.length ? condition.join(', ') : 'Looks well';
    const counts = FACT_FIELDS.map((field) => [field, data[field].length]).filter(([, n]) => n);
    $('#summary-facts').textContent = counts.length
      ? counts.map(([field, n]) => `${n} ${field.replaceAll('_', ' ')}`).join(' · ') : '—';
  },

  async save(event) {
    event.preventDefault();
    if (this.mode === 'view') return;
    for (let step = 0; step < this.steps; step += 1) if (!this.validStep(step)) return;
    const button = $('#save-button');
    const status = $('#builder-status');
    button.disabled = true;
    status.classList.remove('error');
    status.textContent = 'Saving…';
    try {
      const payload = this.read();
      const result = this.mode === 'edit'
        ? await api('/api/case?case_id=' + encodeURIComponent(this.caseId), { method: 'PUT', body: payload })
        : await api('/api/cases', { method: 'POST', body: payload });
      toast(this.mode === 'edit' ? `${result.name} was updated.` : `${result.name} is ready for students (${result.case_id}).`);
      this.mode = null;
      Teacher.showView('library');
    } catch (error) {
      status.classList.add('error');
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  },
};

/* ---------- responses ---------- */
const Responses = {
  async load() {
    try {
      const [{ cases }, { submissions }] = await Promise.all([api('/api/cases'), api('/api/practice-results')]);
      $('#stat-responses').textContent = submissions.length;
      $('#stat-ungraded').textContent = submissions.filter((s) => !s.grade).length;
      $('#stat-cases').textContent = cases.length;
      const byCase = Object.fromEntries(cases.map((c) => [c.case_id, c]));
      const list = $('#response-list');
      if (!submissions.length) {
        list.replaceChildren(el('div', { class: 'empty', style: 'border:0' },
          el('h2', { text: 'No responses yet' }), el('p', { text: 'Finished interviews appear here.' })));
        return;
      }
      list.replaceChildren(...submissions.slice().reverse().map((s) => {
        const c = byCase[s.case_id] || {};
        const pic = el('span', { class: 'portrait' });
        setPortrait(pic, effectiveFace(c.character_id, c.age, c.gender).id);
        return el('button', {
          class: 'response-row', type: 'button', role: 'option', 'aria-selected': 'false',
          onclick: (event) => this.select(s, event.currentTarget),
        }, pic, el('span', {}, el('strong', { text: s.student_name || 'Student' }), el('small', { text: `${s.patient_name} · ${new Date(s.submitted_at).toLocaleDateString()}` })),
        el('span', { class: 'chip ' + (s.grade ? 'ok' : 'warn'), text: s.grade ? `Grade ${s.grade}` : 'To review' }));
      }));
    } catch (error) {
      toast(error.message, true);
    }
  },

  select(s, row) {
    $$('.response-row').forEach((r) => r.setAttribute('aria-selected', 'false'));
    row.setAttribute('aria-selected', 'true');
    $('#grading-empty').hidden = true;
    $('#grading-form').hidden = false;
    $('#grading-submission-id').value = s.submission_id;
    $('#grading-case').textContent = `${s.patient_name} · ${s.case_id}`;
    $('#grading-student').textContent = s.student_name || 'Student';
    $('#grading-when').textContent = 'Submitted ' + new Date(s.submitted_at).toLocaleString() + (s.timed_out ? ' · time ran out' : '');
    $('#review-disease').textContent = s.student_diagnosis || 'No diagnosis given before time ran out.';
    $('#review-correct').textContent = s.correct_diagnosis || 'The case was deleted.';
    $('#review-symptoms').textContent = s.symptoms || '—';
    $('#review-notes').textContent = s.notes || '—';
    const lines = s.transcript || [];
    $('#review-transcript-wrap').hidden = !lines.length;
    $('#review-transcript').replaceChildren(...lines.map((line) =>
      el('div', { class: 'line ' + line.role }, el('b', { text: line.role === 'patient' ? 'Patient' : 'Student' }), el('span', { text: line.text }))));
    $('#teacher-grade').value = s.grade || '';
    $('#teacher-feedback').value = s.feedback || '';
  },

  async save(event) {
    event.preventDefault();
    if (!$('#teacher-grade').reportValidity()) return;
    const button = $('#save-grade-button');
    button.disabled = true;
    try {
      await api('/api/grade', { method: 'POST', body: {
        submission_id: $('#grading-submission-id').value, grade: $('#teacher-grade').value, feedback: $('#teacher-feedback').value.trim(),
      } });
      toast('Review saved. The student sees it on their review page.');
      const id = $('#grading-submission-id').value;
      await this.load();
      Teacher.refreshCount();
      const { submissions } = await api('/api/practice-results');
      const again = submissions.find((s) => s.submission_id === id);
      const index = submissions.slice().reverse().findIndex((s) => s.submission_id === id);
      if (again && index >= 0) this.select(again, $$('.response-row')[index]);
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  },
};

/* =========================================================================================
   student
   ========================================================================================= */
const Timers = {
  handle: null,
  stop() { clearInterval(this.handle); this.handle = null; },
  run(seconds, onTick, onDone) {
    this.stop();
    let left = seconds;
    onTick(left);
    this.handle = setInterval(() => {
      left -= 1;
      onTick(left);
      if (left <= 0) { this.stop(); onDone(); }
    }, 1000);
  },
};

const Student = {
  caseId: null,
  info: null,            // {name, age, gender, character_id}
  results: [],

  name() { return $('#student-display-name').value.trim(); },

  async loadPatients() {
    $('#student-display-name').value = storage('vip-student-name') || '';
    const grid = $('#patient-grid');
    try {
      const [{ cases }, mine] = await Promise.all([
        api('/api/student-cases'),
        this.name() ? api('/api/my-results?student_name=' + encodeURIComponent(this.name())) : Promise.resolve({ submissions: [] }),
      ]);
      this.results = mine.submissions;
      if (!cases.length) {
        grid.replaceChildren(el('div', { class: 'empty', style: 'grid-column:1/-1' },
          el('h2', { text: 'No patients yet' }), el('p', { text: 'Your teacher adds practice cases here.' })));
        return;
      }
      grid.replaceChildren(...cases.map((c) => this.card(c)));
    } catch (error) {
      toast(error.message, true);
    }
  },

  card(c) {
    const pic = el('span', { class: 'portrait' });
    setPortrait(pic, effectiveFace(c.character_id, c.age, c.gender).id);
    const done = this.results.filter((r) => r.case_id === c.case_id).pop();
    const status = done
      ? el('span', { class: 'chip ' + (done.grade ? 'ok' : 'accent'), text: done.grade ? `Graded · ${done.grade}` : 'Submitted' })
      : el('span', { class: 'chip', text: 'New' });
    const buttons = done
      ? [el('button', { class: 'btn btn-sm', type: 'button', text: 'Review', onclick: () => this.showReview(done) }),
         el('button', { class: 'btn btn-sm btn-primary', type: 'button', text: 'Practise again', onclick: () => this.openBriefing(c) })]
      : [el('button', { class: 'btn btn-sm btn-primary', type: 'button', text: 'Start', onclick: () => this.openBriefing(c) })];
    return el('article', { class: 'card patient-card' },
      el('div', { class: 'patient-card-head' }, pic, el('div', {}, el('h3', { text: c.name }), el('p', { text: personMeta(c.age, c.gender) }))),
      el('div', { class: 'patient-card-foot' }, status, buttons));
  },

  async openBriefing(c) {
    if (!this.name()) {
      $('#student-display-name').focus();
      toast('Enter your name or student ID first.', true);
      return;
    }
    storage('vip-student-name', this.name());
    try {
      const briefing = await api('/api/briefing?case_id=' + encodeURIComponent(c.case_id));
      this.caseId = c.case_id;
      this.info = { ...briefing.patient, character_id: briefing.character_id };
      const face = effectiveFace(briefing.character_id, briefing.patient.age, briefing.patient.gender).id;
      setPortrait($('#briefing-portrait'), face);
      $('#briefing-name').textContent = briefing.patient.name;
      $('#briefing-meta').textContent = personMeta(briefing.patient.age, briefing.patient.gender);
      show('screen-briefing');
      Timers.run(120, (left) => { $('#briefing-timer').textContent = clock(left); }, () => this.begin());
    } catch (error) {
      toast(error.message, true);
    }
  },

  begin() {
    Timers.stop();
    Consult.enter(this.caseId, this.info);
  },

  toPatients() {
    Timers.stop();
    show('screen-student');
    this.loadPatients();
  },

  /* ---------- wrap-up and submit ---------- */
  wrapUp() {
    show('screen-wrapup');
    $('#wrapup-slot').append($('#notes-form'));
    $('#student-diagnosis').focus();
  },

  async submit(timedOut = false) {
    const form = $('#notes-form');
    if (!timedOut && !form.reportValidity()) return;
    const button = $('#submit-findings');
    button.disabled = true;
    const body = {
      case_id: this.caseId,
      student_name: this.name() || storage('vip-student-name') || 'Student',
      student_diagnosis: $('#student-diagnosis').value.trim(),
      symptoms: $('#student-symptoms').value.trim(),
      notes: $('#student-notes').value.trim(),
      timed_out: timedOut,
      transcript: Consult.transcript,
    };
    try {
      const result = await api('/api/practice-results', { method: 'POST', body });
      Timers.stop();
      $('#notes-slot').append(form);
      form.reset();
      this.showReview({ ...body, correct_diagnosis: result.correct_diagnosis, patient_name: result.patient_name, grade: null, feedback: '' }, true);
      if (timedOut) toast('Time is up. Your notes were submitted.');
    } catch (error) {
      toast(error.message, true);
      if (timedOut) this.wrapUp();
    } finally {
      button.disabled = false;
    }
  },

  showReview(r, fresh = false) {
    $('#review-eyebrow').textContent = `Review · ${r.patient_name || ''}`;
    $('#review-title').textContent = fresh ? 'Interview submitted' : 'Your interview';
    $('#review-intro').textContent = fresh
      ? 'Here is the case diagnosis. Your teacher can now read your notes and give feedback.'
      : 'Your submission and your teacher’s review.';
    $('#mine-diagnosis').textContent = r.student_diagnosis || 'No diagnosis given.';
    $('#mine-correct').textContent = r.correct_diagnosis || '—';
    $('#mine-symptoms').textContent = r.symptoms || '—';
    $('#mine-notes').textContent = r.notes || '';
    $('#mine-notes-wrap').hidden = !r.notes;
    const verdict = $('#mine-verdict');
    verdict.classList.toggle('graded', Boolean(r.grade));
    verdict.replaceChildren(...(r.grade
      ? [el('strong', { text: String(r.grade) }), el('span', { text: 'Grade from your teacher (1 = excellent, 5 = insufficient)' })]
      : [el('span', { text: 'Waiting for your teacher’s review.' })]));
    $('#mine-feedback-wrap').hidden = !r.feedback;
    $('#mine-feedback').textContent = r.feedback || '';
    show('screen-review');
  },
};

/* =========================================================================================
   the consultation: the patient (Unreal video or voice only), the conversation, notes
   ========================================================================================= */
// ElevenLabs browser SDK, loaded on demand (pinned version).
const ELEVENLABS_CLIENT_URL = 'https://cdn.jsdelivr.net/npm/@elevenlabs/client@1.36.1/+esm';
const PATIENT_AUDIO_RATE = 16000;   // the agent's output: mono 16-bit PCM
const INTERVIEW_SECONDS = 600;
const FACE_SWITCH_MS = 1500;        // Unreal's time to change the face after a case is sent
const FIRST_FRAME_MS = 7000;        // no picture by then: voice only
const STALL_MS = 4000;              // picture stopped: voice only until it comes back

/** Voice server WebSocket address: same host over HTTPS (tailscale serve maps /ws), else port 8787. */
function wsUrl(path) {
  return location.protocol === 'https:' ? `wss://${location.host}${path}` : `ws://${location.hostname}:8787${path}`;
}

const STATE_LABELS = {
  connecting: 'Connecting…', ready: 'Ready', listening: 'Listening', thinking: 'Thinking…',
  speaking: 'Patient speaking', offline: 'Not available', ended: 'Interview ended',
};

const Consult = {
  active: false,
  caseId: null,
  info: null,
  start: null,             // /api/start result
  transcript: [],          // [{role: 'student'|'patient', text}]
  conversation: null,      // ElevenLabs session
  stage: null,             // /ws/stage: audio and state to Unreal, Unreal client count back
  video: null,             // /ws/video: JPEG frames of the patient
  unreal: 0,
  loadedAt: 0,
  lastFrame: 0,
  watchdog: null,
  typing: false,
  agentLines: new Map(),

  enter(caseId, info) {
    this.teardown();
    this.active = true;
    this.caseId = caseId;
    this.info = info;
    this.start = null;
    this.transcript = [];
    this.agentLines.clear();
    this.unreal = 0;
    this.loadedAt = 0;
    this.lastFrame = 0;
    const face = effectiveFace(info.character_id, info.age, info.gender).id;
    [$('#stage-portrait'), $('#consult-portrait')].forEach((node) => setPortrait(node, face));
    $('#consult-name').textContent = info.name;
    $('#consult-meta').textContent = personMeta(info.age, info.gender);
    $('#captions').replaceChildren();
    $('#notes-slot').append($('#notes-form'));
    $('#notes-form').reset();
    $('#interview-timer').textContent = clock(INTERVIEW_SECONDS);
    $('#interview-timer-wrap').classList.remove('low');
    this.setNotes(false);
    this.setTyping(false);
    this.setTalkEnabled(false);
    this.note('');
    show('screen-consult');
    this.setStage('connecting', `Bringing in ${info.name.split(' ')[0]}…`, 'Preparing the consultation room');
    this.setState('connecting');
    this.openStage();
    this.openVideo();
    this.watchdog = setInterval(() => this.checkPicture(), 1000);
    this.load(true);
  },

  async load(first = false) {
    $('#retry-button').hidden = true;
    $('#stage-error').hidden = true;
    this.setStage('connecting', `Bringing in ${this.info.name.split(' ')[0]}…`, 'Preparing the consultation room');
    this.setState('connecting');
    try {
      this.start = await api('/api/start', { method: 'POST', body: { case_id: this.caseId } });
    } catch (error) {
      if (!this.active) return;
      this.setStage('offline', 'The patient couldn’t be loaded', 'Consultation room unavailable');
      $('#stage-error').textContent = error.message;
      $('#stage-error').hidden = false;
      $('#retry-button').hidden = false;
      this.setTalkEnabled(false);
      this.setState('offline');
      return;
    }
    if (!this.active) return;
    this.loadedAt = performance.now();
    this.lastFrame = 0;
    this.decideStage();
    this.prepareTalking();
    if (first || !Timers.handle) {
      Timers.run(INTERVIEW_SECONDS, (left) => {
        $('#interview-timer').textContent = clock(left);
        $('#interview-timer-wrap').classList.toggle('low', left <= 60);
        $('#wrapup-note').textContent = `Time left ${clock(left)} · submitted automatically at 00:00`;
      }, () => this.timeUp());
    }
  },

  /* ---------- the picture: Unreal video when it is there, voice only otherwise ---------- */
  setStage(mode, title, note) {
    $('#stage').dataset.mode = mode;
    if (title) $('#stage-title').textContent = title;
    if (note) $('#stage-note').textContent = note;
  },

  decideStage() {
    if (!this.loadedAt) return;
    const mode = $('#stage').dataset.mode;
    if (this.unreal > 0) {
      if (mode !== 'video') this.setStage('connecting', this.info.name, 'Waiting for the 3D patient…');
    } else {
      this.setStage('voice', this.info.name, '3D view offline · voice only');
    }
  },

  checkPicture() {
    if (!this.active || !this.loadedAt) return;
    const now = performance.now();
    const mode = $('#stage').dataset.mode;
    if (mode === 'connecting' && now - this.loadedAt > FIRST_FRAME_MS) {
      this.setStage('voice', this.info.name, '3D view not responding · voice only');
    } else if (mode === 'video' && now - this.lastFrame > STALL_MS) {
      this.setStage('voice', this.info.name, '3D view paused · voice only');
    }
  },

  openVideo() {
    const canvas = $('#stage-video');
    const paint = canvas.getContext('2d');
    let newest = null;
    let drawing = false;
    const draw = async () => {
      if (drawing || !newest) return;
      drawing = true;
      const blob = newest;
      newest = null;
      try {
        const picture = await createImageBitmap(blob);
        if (this.active && this.loadedAt && performance.now() - this.loadedAt > FACE_SWITCH_MS) {
          if (canvas.width !== picture.width || canvas.height !== picture.height) {
            canvas.width = picture.width;
            canvas.height = picture.height;
          }
          paint.drawImage(picture, 0, 0);
          this.lastFrame = performance.now();
          if ($('#stage').dataset.mode !== 'video' && $('#stage').dataset.mode !== 'offline') this.setStage('video');
        }
        picture.close();
      } catch { /* a broken frame: wait for the next one */ }
      drawing = false;
      draw();
    };
    const connect = () => {
      if (!this.active) return;
      let socket;
      try { socket = new WebSocket(wsUrl('/ws/video')); } catch { return; }
      this.video = socket;
      socket.binaryType = 'blob';
      socket.onmessage = (event) => { newest = event.data; draw(); };
      socket.onclose = () => {
        if (this.video !== socket) return;   // closed on purpose
        this.video = null;
        setTimeout(connect, 2500);
      };
    };
    paint.clearRect(0, 0, canvas.width, canvas.height);
    connect();
  },

  openStage() {
    const connect = () => {
      if (!this.active) return;
      let socket;
      try { socket = new WebSocket(wsUrl('/ws/stage')); } catch { return; }
      this.stage = socket;
      socket.onmessage = (event) => {
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (message.type === 'status') {
          this.unreal = message.unreal || 0;
          this.route();
          if (this.unreal === 0 && $('#stage').dataset.mode !== 'offline') this.decideStage();
          else if (this.unreal > 0 && $('#stage').dataset.mode === 'voice') this.loadedAt = performance.now() - FACE_SWITCH_MS;
        }
      };
      socket.onclose = () => {
        if (this.stage !== socket) return;
        this.stage = null;
        this.unreal = 0;
        this.route();
        if ($('#stage').dataset.mode !== 'offline') this.decideStage();
        setTimeout(connect, 2500);
      };
    };
    connect();
  },

  toStage(message) {
    if (this.stage && this.stage.readyState === WebSocket.OPEN) this.stage.send(JSON.stringify(message));
  },

  /** While Unreal is connected it plays the voice; the browser stays silent. */
  route() {
    if (this.conversation) {
      try { this.conversation.setVolume({ volume: this.unreal > 0 ? 0 : 1 }); } catch { /* not ready yet */ }
    }
  },

  /* ---------- the conversation ---------- */
  voiceAvailable() {
    return Boolean(this.start && this.start.agent_id && window.isSecureContext);
  },

  /** The talk controls work only once the patient is loaded. */
  setTalkEnabled(on) {
    $('#mic-button').disabled = !on;
    $('#type-toggle').disabled = !on;
    $$('#type-form input, #type-form button').forEach((node) => { node.disabled = !on; });
  },

  prepareTalking() {
    this.setTalkEnabled(true);
    if (this.start && this.start.voice_error) {
      this.note('Voice setup problem: ' + this.start.voice_error + ' You can type your questions instead.', true);
    }
    if (!this.voiceAvailable()) {
      $('#mic-button').disabled = true;
      $('#type-toggle').hidden = true;
      this.setTyping(true);
      if (!this.start?.voice_error) {
        this.note(window.isSecureContext
          ? 'Voice isn’t set up on this computer, so type your questions. The patient answers in text.'
          : 'The microphone needs a secure (https) address. Type your questions instead.');
      }
    } else {
      $('#mic-button').disabled = false;
      $('#type-toggle').hidden = false;
    }
    this.setState('ready');
  },

  setState(state) {
    $('#screen-consult').dataset.state = state;
    let label = STATE_LABELS[state] || state;
    if (state === 'ready') label = this.typing ? 'Ready · type to begin' : 'Ready · press Start talking';
    if (state === 'listening' && this.typing) label = 'Your turn';
    $('#status-label').textContent = label;
    const live = Boolean(this.conversation);
    $('#mic-button').classList.toggle('live', live);
    $('#mic-label').textContent = state === 'connecting' && !this.start ? 'Start talking'
      : live ? 'End conversation' : (state === 'connecting' ? 'Connecting…' : 'Start talking');
  },

  note(text, isError = false) {
    $('#dock-note').textContent = text;
    $('#dock-note').classList.toggle('error', isError);
  },

  setTyping(on) {
    this.typing = on;
    $('#type-form').hidden = !on;
    $('#mic-button').hidden = on;
    $('#type-toggle').setAttribute('aria-pressed', String(on));
    if (on) setTimeout(() => $('#type-input').focus(), 50);
    if ($('#screen-consult').dataset.state === 'ready') this.setState('ready');
  },

  async toggleTyping() {
    if (!this.typing && this.conversation) await this.endVoice();
    this.setTyping(!this.typing);
  },

  setNotes(open) {
    $('#screen-consult').classList.toggle('notes-open', open);
    $('#notes-toggle').setAttribute('aria-pressed', String(open));
    if (open) setTimeout(() => $('#student-diagnosis').focus({ preventScroll: true }), 300);
  },

  addLine(role, text, key) {
    const clean = String(text || '').trim();
    if (!clean) return;
    let entry = key ? this.agentLines.get(key) : null;
    if (entry) entry.text = clean;
    else {
      entry = { role, text: clean };
      this.transcript.push(entry);
      if (key) this.agentLines.set(key, entry);
    }
    const recent = this.transcript.slice(-3);
    $('#captions').replaceChildren(...recent.map((line) =>
      el('div', { class: 'caption ' + line.role }, el('b', { text: line.role === 'patient' ? this.info.name.split(' ')[0] : 'You' }), line.text)));
  },

  historyForEngine() {
    return this.transcript.map((line) => ({ role: line.role === 'patient' ? 'assistant' : 'user', content: line.text }));
  },

  async toggleVoice() {
    if (this.conversation) await this.endVoice();
    else await this.startVoice();
  },

  async startVoice() {
    if (!this.voiceAvailable() || this.conversation) return;
    $('#mic-button').disabled = true;
    this.note('');
    this.setState('connecting');
    $('#mic-label').textContent = 'Connecting…';
    try {
      const { Conversation } = await import(ELEVENLABS_CLIENT_URL);
      this.conversation = await Conversation.startSession({
        agentId: this.start.agent_id,
        // WebSocket mode delivers the patient's raw PCM in onAudio, which goes on to Unreal.
        connectionType: 'websocket',
        onAudio: (pcm) => this.toStage({ type: 'audio', sample_rate: PATIENT_AUDIO_RATE, pcm_b64: pcm }),
        // Barge-in: the student talked over the patient. The SDK stops the browser audio; Unreal stops too.
        onInterruption: () => {
          this.toStage({ type: 'interrupt' });
          this.setState('listening');
        },
        onConnect: () => {
          this.toStage({ type: 'state', state: 'listening' });
          this.setState('listening');
        },
        onDisconnect: () => {
          this.conversation = null;
          this.toStage({ type: 'state', state: 'idle' });
          if (this.active) this.setState('ready');
        },
        onModeChange: ({ mode }) => {
          if (mode === 'speaking') this.setState('speaking');
          else {
            this.toStage({ type: 'state', state: 'listening' });
            this.setState('listening');
          }
        },
        onMessage: (payload) => {
          const fromPatient = payload.role ? payload.role === 'agent' : payload.source === 'ai';
          if (fromPatient) {
            this.addLine('patient', payload.message, payload.response_id || null);
          } else {
            this.addLine('student', payload.message);
            this.setState('thinking');
            // The desktop app's agent talks to OpenAI directly: report the turn so the face reacts
            if (this.start.signed) api('/api/director', { method: 'POST', body: { messages: this.historyForEngine() } }).catch(() => {});
          }
        },
        onError: (message) => this.note(String(message || 'The voice connection had a problem.'), true),
      });
      this.route();
      this.setState('listening');
    } catch (error) {
      this.conversation = null;
      const name = error && error.name;
      if (name === 'NotAllowedError' || name === 'NotFoundError') {
        this.note(name === 'NotAllowedError'
          ? 'Microphone access is blocked. Allow it in the browser, or type your questions.'
          : 'No microphone found. Type your questions instead.', true);
        this.setTyping(true);
      } else {
        this.note('The voice connection could not start: ' + (error && error.message ? error.message : error) + ' You can type instead.', true);
      }
      this.setState('ready');
    } finally {
      $('#mic-button').disabled = !this.voiceAvailable();
    }
  },

  async endVoice() {
    const session = this.conversation;
    this.conversation = null;
    if (session) {
      try { await session.endSession(); } catch { /* already closed */ }
    }
    this.toStage({ type: 'state', state: 'idle' });
    if (this.active) this.setState('ready');
  },

  async sendTyped(event) {
    event.preventDefault();
    const input = $('#type-input');
    const text = input.value.trim();
    if (!text || !this.start || $('#screen-consult').dataset.state === 'thinking') return;
    input.value = '';
    this.addLine('student', text);
    this.setState('thinking');
    try {
      const { reply } = await api('/api/turn', { method: 'POST', body: { messages: this.historyForEngine() } });
      if (!this.active) return;
      this.addLine('patient', reply);
      this.note('');
    } catch (error) {
      this.note(error.message, true);
    }
    if (this.active) this.setState('listening');
    input.focus();
  },

  /* ---------- ending ---------- */
  async end() {
    const choice = await ask('End the interview?', 'The conversation closes and you write up your findings. You can’t return to this patient afterwards.', [
      { label: 'Keep interviewing', value: '' },
      { label: 'Leave without submitting', value: 'leave', kind: 'ghost' },
      { label: 'End and write up', value: 'end', kind: 'primary' },
    ]);
    if (choice === 'leave') {
      this.teardown();
      Student.toPatients();
    } else if (choice === 'end') {
      this.teardown();
      Student.wrapUp();
    }
  },

  timeUp() {
    this.teardown();
    Student.submit(true);
  },

  teardown() {
    if (!this.active && !this.conversation && !this.stage && !this.video) return;
    this.active = false;
    clearInterval(this.watchdog);
    this.watchdog = null;
    if (this.conversation) {
      const session = this.conversation;
      this.conversation = null;
      session.endSession().catch(() => {});
    }
    if (this.stage) {
      const socket = this.stage;
      this.stage = null;
      try { socket.send(JSON.stringify({ type: 'state', state: 'idle' })); } catch { /* closed */ }
      socket.close();
    }
    if (this.video) {
      const socket = this.video;
      this.video = null;
      socket.close();
    }
    $('#screen-consult').classList.remove('notes-open');
  },
};

/* =========================================================================================
   start-up: wire the page
   ========================================================================================= */
function wire() {
  $$('[data-role]').forEach((button) => button.addEventListener('click', () => selectRole(button.dataset.role)));
  $$('.sidenav [data-view]').forEach((button) => button.addEventListener('click', () => {
    if (button.dataset.view === 'builder') Builder.open('new');
    Teacher.showView(button.dataset.view);
  }));
  document.addEventListener('click', (event) => {
    const action = event.target.closest('[data-action]')?.dataset.action;
    if (action === 'new-case') { Builder.open('new'); Teacher.showView('builder'); }
    if (action === 'back-to-library') { Builder.mode = null; Teacher.showView('library'); }
    if (action === 'to-patients') Student.toPatients();
  });

  // builder
  $('#case-form').addEventListener('submit', (event) => Builder.save(event));
  $('#next-button').addEventListener('click', () => Builder.next());
  $('#back-button').addEventListener('click', () => Builder.goto(Math.max(0, Builder.step - 1)));
  $$('.step-tab').forEach((tab) => tab.addEventListener('click', () => {
    const target = Number(tab.dataset.goto);
    if (target > Builder.step && !Builder.validStep(Builder.step)) return;
    Builder.goto(target);
  }));
  $('#duplicate-button').addEventListener('click', () => Builder.openCase(Builder.caseId, 'duplicate'));
  $('#gender').addEventListener('change', () => Builder.updateGender());
  $('#age').addEventListener('input', () => { Builder.renderFaces(); Builder.renderSummary(); });
  $('#personality-type').addEventListener('change', () => Builder.updatePersonality());
  $('#pain').addEventListener('input', () => { $('#pain-out').textContent = $('#pain').value + '/10'; });
  $('#case-form').addEventListener('input', () => Builder.renderSummary());
  $('#case-form').addEventListener('change', () => { $('#pain-out').textContent = $('#pain').value + '/10'; Builder.renderSummary(); });

  // responses
  $('#grading-form').addEventListener('submit', (event) => Responses.save(event));

  // student
  let nameTimer;
  $('#student-display-name').addEventListener('input', () => {
    storage('vip-student-name', Student.name());
    clearTimeout(nameTimer);
    nameTimer = setTimeout(() => Student.loadPatients(), 500);
  });
  $('#begin-interview-button').addEventListener('click', () => Student.begin());
  $('#submit-findings').addEventListener('click', () => Student.submit(false));

  // consultation
  $('#mic-button').addEventListener('click', () => Consult.toggleVoice());
  $('#type-toggle').addEventListener('click', () => Consult.toggleTyping());
  $('#type-form').addEventListener('submit', (event) => Consult.sendTyped(event));
  $('#captions-toggle').addEventListener('click', (event) => {
    const on = event.currentTarget.getAttribute('aria-pressed') !== 'true';
    event.currentTarget.setAttribute('aria-pressed', String(on));
    $('#screen-consult').classList.toggle('no-captions', !on);
  });
  $('#notes-toggle').addEventListener('click', () => Consult.setNotes(!$('#screen-consult').classList.contains('notes-open')));
  $('#notes-close').addEventListener('click', () => Consult.setNotes(false));
  $('#end-interview-button').addEventListener('click', () => Consult.end());
  $('#retry-button').addEventListener('click', () => Consult.load());
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && Consult.active && $('#screen-consult').classList.contains('notes-open') && !$('#confirm-dialog').open) Consult.setNotes(false);
  });
  window.addEventListener('beforeunload', () => Consult.teardown());

  $('#pain-out').textContent = '0/10';
  show('screen-landing');
}

wire();
