/**
 * claimAuditHelpers.js — claim-audit wording over the canonical signal renderer.
 *
 * This used to be a second implementation of the epistemic rules: its own map
 * from outcome to label, tone and adverse-ness, sitting alongside the same
 * logic in Python. Two implementations of one rule drift, and the rule here is
 * the one the product is built on — that a check which could not run is never
 * shown as a check that passed.
 *
 * It now supplies only VOCABULARY. "Supported" reads better than "Verified" for
 * a citation, so the words are domain-specific; tone, isAdverse, isClean and
 * needsAttention all come from `signalHelpers`, which in turn reads the flags
 * computed and invariant-checked in signals.py.
 *
 * Pure and dependency-free. Returns RAW strings; the caller escapes.
 */

import { signalBadge } from './signalHelpers.js';

/** Wording shown wherever an audit result appears. */
export const CLAIM_AUDIT_DISCLAIMER =
  'Claim checks are an AI judgement of whether the cited passage supports the '
  + 'claim. They are advisory, can be wrong, and never block anything — open the '
  + 'source and decide for yourself.';

/**
 * Claim-audit wording for each state. Note "Could not check" and "No anchor"
 * are deliberately distinct from each other and from "Not supported": the
 * first two are failures to check, and only the third criticises the citation.
 */
const CLAIM_AUDIT_LABELS = {
  heuristicTitle: CLAIM_AUDIT_DISCLAIMER,
  clean: 'Supported',
  adverse: 'Not supported',
  degraded: 'Could not check',
  notChecked: 'Not checked',
  notApplicable: 'Not applicable',
};

/** Outcome -> wording, for the anchorless case the status alone cannot express. */
const _ANCHORLESS_LABEL = 'No anchor';

/**
 * Display model for one audit result.
 *
 * @param {object|null} audit — the `audit` block stored on a citation. Reads
 *   `audit.signal`, the canonical payload; falls back to nothing if absent.
 * @returns {{show, label, tone, title, reason, isAdverse}} — `show` is false
 *   when there is nothing to display. Never throws.
 */
export function claimAuditBadge(audit) {
  const a = (audit && typeof audit === 'object') ? audit : null;
  const badge = signalBadge(a ? a.signal : null, CLAIM_AUDIT_LABELS);
  if (!badge.show) {
    return { show: false, label: '', tone: 'muted', title: '', reason: '', isAdverse: false };
  }

  // ANCHORLESS and UNVERIFIABLE are both DEGRADED — correctly, since each is a
  // failure to check rather than a finding — but they are different failures
  // and the user can act on one of them.
  const label = a.outcome === 'anchorless' ? _ANCHORLESS_LABEL : badge.label;

  return {
    show: true,
    label,
    tone: badge.tone,
    title: badge.title,
    reason: String(a.reason || badge.detail || ''),
    isAdverse: badge.isAdverse,
  };
}

/**
 * One honest sentence about a batch of audits.
 * Reports what was actually settled, never conflating "could not check" with
 * "checked and fine".
 * @param {object|null} summary — the `summary` block from an audit run
 * @returns {string} — '' when there is nothing to report. Never throws.
 */
export function claimAuditSummaryLine(summary) {
  const s = (summary && typeof summary === 'object') ? summary : null;
  if (!s) return '';
  const total = Number(s.total) || 0;
  if (total === 0) return '';
  const checked = Number(s.checked) || 0;
  const adverse = Number(s.adverse) || 0;
  const inconclusive = Number(s.inconclusive) || 0;

  const parts = [`${checked} of ${total} citation${total === 1 ? '' : 's'} checked`];
  parts.push(adverse === 0
    ? 'none flagged as unsupported'
    : `${adverse} flagged as unsupported`);
  if (inconclusive > 0) {
    parts.push(`${inconclusive} could not be checked`);
  }
  return `${parts.join(' · ')}.`;
}
