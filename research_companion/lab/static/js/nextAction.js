/**
 * nextAction.js — Pure next-best-action selector for the Home view.
 * DOM-free: no document/window references. Node-testable.
 */

/**
 * Select up to 3 next actions from application state.
 * Rules fire in priority order; first match wins per slot.
 *
 * @param {object} state
 * @returns {Array<{id,priority,label,detail,route?,action?}>}
 */
export function selectNextActions(state) {
  const candidates = [];

  const settings = state.settings || {};
  const keys = settings.keys || {};
  const provider = settings.provider || 'anthropic';
  const keyName = provider === 'openai' ? 'openai_api_key' : 'anthropic_api_key';
  const keySet = keys[keyName] && keys[keyName].set;

  // Rule 1: no API key
  if (!keySet) {
    candidates.push({
      id: 'connect',
      priority: 1,
      label: 'Connect a model',
      detail: 'Add your API key to enable AI features.',
      route: '#/settings',
    });
  }

  // Rule 2: no draft
  if (!state.draftId) {
    candidates.push({
      id: 'add-draft',
      priority: 2,
      label: 'Add your draft',
      detail: 'Set your paper as the draft to start analysis.',
      action: 'open-ingest',
    });
  }

  // Rule 3: papers < 3 (non-draft papers)
  const papers = state.papers instanceof Map ? state.papers : new Map();
  let nonDraftCount = 0;
  for (const [id, p] of papers) {
    if (id !== state.draftId && !p.is_draft) nonDraftCount++;
  }
  if (nonDraftCount < 3) {
    candidates.push({
      id: 'add-papers',
      priority: 3,
      label: 'Add related papers',
      detail: 'Add more papers for richer comparison.',
      action: 'open-ingest',
    });
  }

  // Rule 4: failures
  const failures = state.failures || {};
  const failureCount = Object.keys(failures).length;
  if (failureCount > 0) {
    candidates.push({
      id: 'fix-failures',
      priority: 4,
      label: `${failureCount} ingest failure${failureCount === 1 ? '' : 's'} — retry or remove`,
      detail: 'Some papers failed to ingest.',
      route: '#/library',
    });
  }

  // Rule 5: open citation-kind suggestions
  const suggestions = Array.isArray(state.suggestions) ? state.suggestions : [];
  const openCitations = suggestions.filter(s => s.status === 'open' && s.kind === 'citation');
  if (openCitations.length > 0) {
    const n = openCitations.length;
    candidates.push({
      id: 'verify-citations',
      priority: 5,
      label: `${n} citation${n === 1 ? '' : 's'} unverified — fix these first`,
      detail: 'Citation suggestions need attention.',
      action: 'open-suggestions',
    });
  }

  // Rule 6: open high severity suggestions
  const openHigh = suggestions.filter(s => s.status === 'open' && s.severity === 'high');
  if (openHigh.length > 0) {
    const n = openHigh.length;
    candidates.push({
      id: 'high-priority',
      priority: 6,
      label: `${n} high-priority suggestion${n === 1 ? '' : 's'}`,
      detail: 'High-severity issues need your attention.',
      action: 'open-suggestions',
    });
  }

  // Rule 7: suggestions list empty AND draft set
  if (suggestions.length === 0 && state.draftId) {
    candidates.push({
      id: 'analyze',
      priority: 7,
      label: 'Analyze your draft',
      detail: 'Open the suggestions panel and click Regenerate.',
      action: 'open-suggestions',
    });
  }

  // Rule 8: fallback — explore the timeline
  candidates.push({
    id: 'explore',
    priority: 8,
    label: 'Explore the timeline',
    detail: 'See your research journey so far.',
    route: '#/timeline',
  });

  // Return up to 3 distinct actions (already distinct by id; just slice top 3)
  return candidates.slice(0, 3);
}
