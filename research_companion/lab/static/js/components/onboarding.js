/**
 * components/onboarding.js — Onboarding stepper for the Home view.
 *
 * onboardingStep(state) is a pure function (no DOM).
 * renderOnboarding(state, el) renders the stepper into a DOM element.
 */

// ---------------------------------------------------------------------------
// Pure logic
// ---------------------------------------------------------------------------

/**
 * Derive the current onboarding step from application state.
 * Reads localStorage rc.tourMetSuggestions for the meet_suggestions step.
 *
 * @param {object} state
 * @returns {'connect'|'add_draft'|'ingest'|'meet_suggestions'|'done'}
 */
export function onboardingStep(state) {
  const settings = state.settings || {};
  const keys = settings.keys || {};
  const provider = settings.provider || 'anthropic';
  const keyName = provider === 'openai' ? 'openai_api_key' : 'anthropic_api_key';
  const keySet = keys[keyName] && keys[keyName].set;

  if (!keySet) return 'connect';

  if (!state.draftId) return 'add_draft';

  // Count non-draft papers
  const papers = state.papers instanceof Map ? state.papers : new Map();
  let nonDraftCount = 0;
  for (const [id, p] of papers) {
    if (id !== state.draftId && !p.is_draft) nonDraftCount++;
  }
  if (nonDraftCount === 0) return 'ingest';

  const suggestionCounts = state.suggestionCounts || {};
  const openCount = suggestionCounts.open || 0;
  const metSuggestions = typeof localStorage !== 'undefined'
    ? localStorage.getItem('rc.tourMetSuggestions')
    : null;
  if (openCount > 0 && !metSuggestions) return 'meet_suggestions';

  return 'done';
}

// ---------------------------------------------------------------------------
// Render (DOM-dependent)
// ---------------------------------------------------------------------------

const STEPS = [
  { key: 'connect',           label: 'Connect' },
  { key: 'add_draft',         label: 'Add Draft' },
  { key: 'ingest',            label: 'Add Papers' },
  { key: 'meet_suggestions',  label: 'Explore' },
];

const STEP_ORDER = STEPS.map(s => s.key);

/**
 * Render the onboarding stepper into el.
 * Binds button actions; does NOT remove itself when dismissed.
 *
 * @param {object} state
 * @param {HTMLElement} el
 * @param {object} [opts]
 * @param {Function} [opts.openIngest]  — opens ingest modal
 * @param {Function} [opts.onDismiss]   — called when Skip is clicked
 */
export function renderOnboarding(state, el, opts = {}) {
  const currentStep = onboardingStep(state);
  const currentIdx = STEP_ORDER.indexOf(currentStep);

  const stepHtml = STEPS.map((s, i) => {
    const isDone = i < currentIdx || currentStep === 'done';
    const isActive = s.key === currentStep;
    let cls = 'home-step';
    if (isDone) cls += ' done';
    else if (isActive) cls += ' active';

    const indicator = isDone
      ? `<span class="home-step-check">✓</span>`
      : `<span class="home-step-num">${i + 1}</span>`;

    return `<div class="${cls}">${indicator} ${s.label}</div>`;
  }).join('');

  let actionHtml = '';
  if (currentStep === 'connect') {
    actionHtml = `<a class="btn btn-accent btn-sm" href="#/settings">Go to Settings</a>`;
  } else if (currentStep === 'add_draft') {
    actionHtml = `<button class="btn btn-accent btn-sm" id="ob-open-ingest-single">Add your draft</button>`;
  } else if (currentStep === 'ingest') {
    actionHtml = `<button class="btn btn-accent btn-sm" id="ob-open-ingest-folder">Add papers</button>`;
  } else if (currentStep === 'meet_suggestions') {
    actionHtml = `<button class="btn btn-accent btn-sm" id="ob-open-suggestions">Open Suggestions</button>`;
  }

  el.innerHTML = `
    <div class="home-onboarding">
      <p class="home-onboarding-title">Get started with Research Companion</p>
      <div class="home-stepper">${stepHtml}</div>
      <div class="home-onboarding-actions">
        ${actionHtml}
        <button class="home-skip-link" id="ob-skip">Skip intro</button>
      </div>
    </div>`;

  // Bind events
  el.querySelector('#ob-skip')?.addEventListener('click', () => {
    localStorage.setItem('rc.tourDismissed', '1');
    if (typeof opts.onDismiss === 'function') opts.onDismiss();
  });

  el.querySelector('#ob-open-ingest-single')?.addEventListener('click', () => {
    if (typeof opts.openIngest === 'function') opts.openIngest('single');
  });

  el.querySelector('#ob-open-ingest-folder')?.addEventListener('click', () => {
    if (typeof opts.openIngest === 'function') opts.openIngest('folder');
  });

  el.querySelector('#ob-open-suggestions')?.addEventListener('click', () => {
    window.dispatchEvent(new CustomEvent('rc:toggle-suggestions'));
  });

  // Pulse the bell briefly when the user reaches the meet_suggestions step
  if (currentStep === 'meet_suggestions') {
    _pulseBell();
  }
}

/**
 * Add a short pulse animation class to the top-bar bell to draw the eye.
 * No-op if the bell is not in the DOM.
 */
function _pulseBell() {
  const bell = document.getElementById('topbar-bell');
  if (!bell || bell.classList.contains('bell-pulse')) return;
  bell.classList.add('bell-pulse');
  setTimeout(() => bell.classList.remove('bell-pulse'), 2400);
}
