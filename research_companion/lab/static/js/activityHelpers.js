/**
 * activityHelpers.js — Pure, DOM-free helpers for the background-activity
 * indicator UI (W5-ACT).
 *
 * All functions are stateless and have no DOM dependencies so they can be
 * tested with node --test.
 */

// ---------------------------------------------------------------------------
// Exported helpers
// ---------------------------------------------------------------------------

/**
 * Derive a {count, label} summary from the activeJobs Map.
 *
 * @param {Map|null|undefined} activeJobs  — Map<job_id, {kind, label, target}>
 * @returns {{ count: number, label: string }}
 */
export function activitySummary(activeJobs) {
  if (!activeJobs || activeJobs.size === 0) {
    return { count: 0, label: '' };
  }
  const count = activeJobs.size;
  if (count === 1) {
    const [, job] = activeJobs.entries().next().value;
    return { count: 1, label: job.label || '' };
  }
  return { count, label: `${count} tasks running` };
}

/**
 * Return a Set of non-empty targets from kind==='add' jobs.
 * Used to mark citation rows as "Downloading…" in the citations panel.
 *
 * @param {Map|null|undefined} activeJobs
 * @returns {Set<string>}
 */
export function citationDownloadTargets(activeJobs) {
  const result = new Set();
  if (!activeJobs) return result;
  for (const [, job] of activeJobs) {
    if (job.kind === 'add' && job.target) {
      result.add(job.target);
    }
  }
  return result;
}

/**
 * Return true when any active job has kind==='citations'.
 *
 * @param {Map|null|undefined} activeJobs
 * @returns {boolean}
 */
export function isResolving(activeJobs) {
  if (!activeJobs) return false;
  for (const [, job] of activeJobs) {
    if (job.kind === 'citations') return true;
  }
  return false;
}
