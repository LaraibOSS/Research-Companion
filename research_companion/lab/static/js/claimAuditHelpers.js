/**
 * claimAuditHelpers.js — display model for claim-audit outcomes.
 *
 * The rendering rule mirrors the backend guarantee: only ONE outcome criticises
 * a citation. Everything else means *we could not check*, and must never be
 * shown in a way that reads as an accusation — or as a clean tick.
 *
 * Pure and dependency-free (no DOM, no store) so it is node-testable. Returns
 * RAW strings; the caller escapes at the interpolation site.
 */

/** Wording shown wherever an audit result appears. */
export const CLAIM_AUDIT_DISCLAIMER =
  'Claim checks are an AI judgement of whether the cited passage supports the '
  + 'claim. They are advisory, can be wrong, and never block anything — open the '
  + 'source and decide for yourself.';

const _BADGES = {
  supported: {
    label: 'Supported',
    tone: 'ok',
    title: 'The cited passage supports this claim (AI judgement).',
  },
  not_supported: {
    label: 'Not supported',
    tone: 'warn',
    title: 'The cited passage does not appear to establish this claim (AI judgement — verify).',
  },
  unverifiable: {
    label: 'Could not check',
    tone: 'muted',
    title: 'The passage could not be retrieved or judged. This is NOT a finding about the citation.',
  },
  anchorless: {
    label: 'No anchor',
    tone: 'muted',
    title: 'This citation has no locator, so there was nothing to check against.',
  },
  not_checked: {
    label: 'Not checked',
    tone: 'muted',
    title: 'Claim auditing did not run for this citation.',
  },
};

/**
 * Display model for one audit result.
 * @param {object|null} audit — the `audit` block stored on a citation
 * @returns {{show, label, tone, title, reason, isAdverse}} — `show` is false
 *   when there is nothing to display. Never throws.
 */
export function claimAuditBadge(audit) {
  const a = (audit && typeof audit === 'object') ? audit : null;
  if (!a || !a.outcome) {
    return { show: false, label: '', tone: 'muted', title: '', reason: '', isAdverse: false };
  }
  const spec = _BADGES[a.outcome] || _BADGES.not_checked;
  return {
    show: true,
    label: spec.label,
    tone: spec.tone,
    title: spec.title,
    reason: String(a.reason || ''),
    // trust the backend's own flag rather than re-deriving the rule here, so
    // the two can never disagree about what counts as an accusation
    isAdverse: a.is_adverse === true,
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
