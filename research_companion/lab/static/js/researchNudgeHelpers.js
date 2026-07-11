/**
 * researchNudgeHelpers.js — Pure helper for the "start a new research" nudge.
 *
 * When a user adds a draft into a research that already holds papers (or
 * already has a different draft), we gently suggest creating a fresh research
 * so each draft/project stays isolated (the 0.4 workspace model). This is a
 * non-blocking nudge — the user can always add to the current research.
 *
 * No DOM access — node-testable.
 */

/**
 * Decide whether to show the new-research nudge before adding a draft.
 * @param {{papers?: Map|Array, draftId?: string|null}} state
 * @returns {boolean}
 */
export function shouldSuggestNewResearch(state) {
  if (!state) return false;
  const paperCount = _size(state.papers);
  const hasDraft = !!state.draftId;
  // Non-empty research (has papers) or one that already has a draft -> nudge.
  return paperCount > 0 || hasDraft;
}

function _size(papers) {
  if (!papers) return 0;
  if (papers instanceof Map) return papers.size;
  if (Array.isArray(papers)) return papers.length;
  if (typeof papers.size === 'number') return papers.size;
  return 0;
}
