/**
 * zoteroHelpers.js — pure display logic for "Import from Zotero".
 *
 * DOM-free so it is tested under node. The wording of the status comes from
 * the server (interop/zotero.check), which knows why Zotero could not be
 * read; these helpers only decide how to show it and how to summarise a
 * finished import report without dropping any part of the denominator.
 */

/** How many failed job polls in a row before the modal stops asking. */
export const MAX_POLL_FAILURES = 5;

/**
 * GET /api/zotero/status payload -> what the Zotero tab shows.
 * @returns {{ready: boolean, tone: 'ok'|'warn'|'muted', message: string}}
 */
export function statusView(status) {
  const s = status || {};
  const message = typeof s.message === 'string' && s.message
    ? s.message
    : 'Could not tell whether Zotero is reachable.';
  if (s.ok === true && s.state === 'ready') {
    return { ready: true, tone: 'ok', message };
  }
  if (s.state === 'disabled' || s.state === 'not_running') {
    return { ready: false, tone: 'warn', message };
  }
  return { ready: false, tone: 'muted', message };
}

/** Collections payload -> <option> models, "Whole library" first. */
export function collectionOptions(payload) {
  const cols = (payload && Array.isArray(payload.collections)) ? payload.collections : [];
  const opts = [{ value: '', label: 'Whole library' }];
  for (const c of cols) {
    if (!c || !c.key) continue;
    const n = Number.isInteger(c.items) ? ` (${c.items})` : '';
    opts.push({ value: String(c.key), label: `${c.name || c.key}${n}` });
  }
  return opts;
}

function _plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * A finished import report -> one summary sentence. Every bucket is named,
 * including zero ones that matter (could not be added), so "12 added" is
 * never read without its denominator.
 */
export function reportSummary(report) {
  const r = report || {};
  const total = r.total || 0;
  const added = r.added || 0;
  const meta = r.metadata_only || 0;
  const already = r.already_in_library || 0;
  const failed = Array.isArray(r.failed) ? r.failed.length : 0;
  const noPdf = r.no_pdf || 0;
  if (total === 0) return 'Nothing to import: no papers were found in Zotero.';
  if (r.dry_run) {
    return `Preview of ${_plural(total, 'item', 'items')}: ${added} would be added, `
      + `${meta} would be added as details only, ${already} already in your library, `
      + `${failed} could not be checked. Nothing has been added yet.`;
  }
  const pdfNote = noPdf ? ` (${noPdf} still without a PDF)` : '';
  return `Of ${_plural(total, 'item', 'items')}: ${added} added${pdfNote}, `
    + `${meta} added as details only, ${already} already in your library, `
    + `${failed} could not be added.`;
}

const _METHOD = {
  arxiv: 'by arXiv id',
  doi: 'by DOI',
  pdf: 'from the PDF in Zotero',
  metadata: 'details only',
};

/**
 * Report items -> display rows {title, text, tone}. Plain strings: the
 * caller escapes them before they reach innerHTML.
 */
export function reportRows(report) {
  const items = (report && Array.isArray(report.items)) ? report.items : [];
  return items.map((row) => {
    const title = (row && row.title) || '(untitled)';
    const how = _METHOD[row && row.method] || '';
    switch (row && row.outcome) {
      case 'already_in_library':
        return { title, text: 'Already in your library', tone: 'muted' };
      case 'failed':
        return { title, text: `Could not add: ${row.reason || 'unknown reason'}`, tone: 'warn' };
      case 'would_add':
        return { title, text: `Would add ${how}`, tone: 'ok' };
      case 'would_add_metadata_only':
        return { title, text: 'Would add details only (no identifier or PDF)', tone: 'muted' };
      case 'metadata_only':
        return { title, text: 'Added, details only', tone: 'muted' };
      case 'added':
        return { title, text: row.has_pdf ? `Added ${how}` : `Added ${how}; no PDF yet`,
                 tone: row.has_pdf ? 'ok' : 'warn' };
      default:
        return { title, text: 'Unknown outcome', tone: 'muted' };
    }
  });
}

/**
 * One job poll's result -> what to do next.
 * @returns {'continue'|'done'|'failed'|'give-up'}
 */
export function nextPoll({ job, error, consecutiveFailures = 0 } = {}) {
  if (error) {
    if (error.status === 404) return 'give-up';
    return consecutiveFailures + 1 >= MAX_POLL_FAILURES ? 'give-up' : 'continue';
  }
  const status = job && job.status;
  if (status === 'done') return 'done';
  if (status === 'failed') return 'failed';
  return 'continue';
}

/** Progress line while the job runs. */
export function progressText(job) {
  const p = (job && job.progress) || {};
  const verb = job && job.dry_run ? 'Checking' : 'Importing';
  if (!p.total) return `${verb}…`;
  return `${verb} ${p.done || 0} of ${p.total}…`;
}
