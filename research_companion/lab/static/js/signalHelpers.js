/**
 * signalHelpers.js — the display model for a serialized `Signal`.
 *
 * Every deterministic checker now emits the same envelope (see
 * research_companion/checker_signals.py). Unifying the backend is not enough on
 * its own: without one renderer the same Signal surfaces as "Verified" on one
 * screen, "Passed" on another and "Clean" on a third — the divergence removed
 * from the backend, reintroduced one view at a time.
 *
 * THE RULE THIS MODULE FOLLOWS: it does not re-derive the epistemic rules. The
 * backend already computes `is_clean`, `is_adverse` and `needs_attention`, and
 * enforces at construction that an incomplete check cannot carry a conclusion.
 * Re-implementing that logic here would create a second source of truth that
 * silently drifts. This module decides only how a signal LOOKS.
 *
 * Pure and dependency-free (no DOM, no store) so it is node-testable. Returns
 * RAW strings; the caller escapes at the interpolation site.
 */

/** Shown wherever signals from model-assisted checks appear. */
export const HEURISTIC_DISCLAIMER =
  'This is an AI judgement, not a verified fact. It can be wrong — open the '
  + 'source and decide for yourself.';

/** Wording for the states a check can end in. Keyed by check_status. */
const _STATUS = {
  not_checked: {
    label: 'Not checked',
    title: 'This check never ran. That is not a finding about your work.',
  },
  degraded: {
    label: 'Could not check',
    title: 'The check was attempted and could not finish. NOT evidence of a problem.',
  },
  not_applicable: {
    label: 'Not applicable',
    title: 'This check has no meaning for this document. Nothing is outstanding.',
  },
  unknown: {
    label: 'Unknown',
    title: 'The state of this check could not be determined.',
  },
};

/** Why a check did not conclude, in words. Keyed by the `reason` code. */
const _REASON = {
  source_unavailable: 'a source could not be reached',
  parse_failed: 'the input could not be read',
  no_anchor: 'there was no locatable passage to check against',
  no_text: 'no text could be extracted',
  model_error: 'the model call failed',
  ambiguous: 'the result was inconclusive',
  user_disabled: 'it is switched off in Settings',
  not_configured: 'it is not configured',
  skipped: 'it was skipped this run',
  statistic_type_unsupported: 'this kind of statistic is not covered',
  no_such_requirement: 'this venue has no such requirement',
  not_relevant: 'it does not apply here',
};

/**
 * Display model for one serialized Signal.
 *
 * Domain wording may be supplied via `labels` — "Supported" reads better than
 * "Verified" for a citation. Only the WORDS are overridable: tone, isAdverse,
 * isClean and needsAttention always come from the backend flags, so vocabulary
 * can vary by surface while meaning cannot.
 *
 * @param {object|null} signal — a `Signal.to_dict()` payload
 * @param {object} [labels] — {clean, adverse, degraded, notChecked,
 *   notApplicable, heuristicTitle}
 * @returns {{show, label, tone, title, detail, needsAttention, isAdverse,
 *            isClean, isHeuristic}} — `show` false when there is nothing to
 *   render. Never throws.
 */
export function signalBadge(signal, labels = {}) {
  const s = (signal && typeof signal === 'object') ? signal : null;
  const blank = {
    show: false, label: '', tone: 'muted', title: '', detail: '',
    needsAttention: false, isAdverse: false, isClean: false, isHeuristic: false,
  };
  if (!s || !s.check_status) return blank;

  // Trust the backend's flags. See the rule in the module docstring.
  const isClean = s.is_clean === true;
  const isAdverse = s.is_adverse === true;
  const needsAttention = s.needs_attention === true;
  const isHeuristic = s.epistemic_class === 'heuristic_advisory';
  const detail = String(s.detail || '');

  // Incomplete states first: none of them is a finding about the work, and
  // conflating any with a pass or a problem is the failure this whole model
  // exists to prevent.
  const incomplete = _STATUS[s.check_status];
  if (incomplete && s.check_status !== 'checked') {
    const why = _REASON[s.reason];
    return {
      ...blank,
      show: true,
      label: _override(labels, s.check_status) || incomplete.label,
      tone: 'muted',
      title: why ? `${incomplete.title} (${why})` : incomplete.title,
      detail,
      needsAttention,
      isHeuristic,
    };
  }

  // A completed heuristic is still only a heuristic. Checked BEFORE the
  // finding, mirroring Signal.label(), so a matched rule is never rendered as
  // a definitive problem.
  if (isHeuristic) {
    return {
      ...blank,
      show: true,
      label: (isAdverse ? labels.adverse : labels.clean)
        || (isAdverse ? 'Flagged (advisory)' : 'No flag (advisory)'),
      tone: isAdverse ? 'warn' : 'ok',
      title: labels.heuristicTitle || HEURISTIC_DISCLAIMER,
      detail, needsAttention, isAdverse, isClean, isHeuristic: true,
    };
  }

  return {
    ...blank,
    show: true,
    label: (isAdverse ? labels.adverse : labels.clean)
      || (isAdverse ? 'Problem found' : 'Verified'),
    tone: isAdverse ? 'warn' : 'ok',
    title: isAdverse
      ? 'A completed check established this problem.'
      : 'A completed check established this.',
    detail, needsAttention, isAdverse, isClean,
  };
}

/** Domain wording for an incomplete state, if the caller supplied any. */
function _override(labels, status) {
  if (status === 'degraded') return labels.degraded;
  if (status === 'not_checked') return labels.notChecked;
  if (status === 'not_applicable') return labels.notApplicable;
  return '';
}

/**
 * Group signals by what they cost the reader, for a readiness view.
 *
 * Grouped by ACTIONABILITY, not by outcome. `notApplicable` is deliberately
 * separate from `needsReview`: a check that cannot apply to this document is
 * not an outstanding task, and putting it in a review pile would defeat the
 * reason that state exists.
 *
 * @param {Array|null} signals — serialized Signals
 * @returns {{needsAttention, needsReview, notApplicable, clean, total}}
 *   arrays plus a total. Never throws.
 */
export function groupSignals(signals) {
  const out = {
    needsAttention: [], needsReview: [], notApplicable: [], clean: [], total: 0,
  };
  const list = Array.isArray(signals) ? signals : [];
  for (const s of list) {
    if (!s || typeof s !== 'object') continue;
    out.total += 1;
    if (s.is_adverse === true) out.needsAttention.push(s);
    else if (s.check_status === 'not_applicable') out.notApplicable.push(s);
    else if (s.needs_attention === true) out.needsReview.push(s);
    else if (s.is_clean === true) out.clean.push(s);
    else out.needsReview.push(s);
  }
  return out;
}

/**
 * One honest sentence about a set of signals.
 *
 * Reports counts, never a score. A composite "87% ready" would collapse the
 * distinction between a problem found and a check that could not run, which is
 * the distinction the whole model preserves.
 *
 * @param {Array|null} signals
 * @returns {string} '' when there is nothing to report. Never throws.
 */
export function signalSummaryLine(signals) {
  const g = groupSignals(signals);
  if (!g.total) return '';
  const parts = [];
  if (g.needsAttention.length) {
    parts.push(`${g.needsAttention.length} issue${g.needsAttention.length === 1 ? '' : 's'} requiring attention`);
  }
  if (g.needsReview.length) {
    parts.push(`${g.needsReview.length} check${g.needsReview.length === 1 ? '' : 's'} could not be completed`);
  }
  if (g.clean.length) {
    parts.push(`${g.clean.length} passed`);
  }
  if (g.notApplicable.length) {
    parts.push(`${g.notApplicable.length} not applicable`);
  }
  if (!parts.length) return '';
  return `${parts.join(' · ')}.`;
}
