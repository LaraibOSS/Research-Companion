/**
 * directionsProvenance.js — pure helpers that make "Generate directions"
 * explainable and honest.
 *
 * Two jobs:
 *   1. ingestStatus(state) — is the library still being built? Generating while
 *      papers are mid-ingest silently grounds the suggestions on a partial
 *      library, so the UI must be able to warn first.
 *   2. provenanceLine(grounding) — turn the server's real grounding counts into
 *      one sentence stating exactly what the suggestions were built from.
 *
 * Dependency-free (no DOM, no store) and node-testable. Returns RAW strings —
 * the caller escapes at the interpolation site, per brainstorm.js's convention.
 */

/**
 * Inspect the library for in-flight ingest work.
 * @param {object} state — store state ({ papers: Map, activeJobs: Map })
 * @returns {{busy: boolean, pending: number, failed: number, ready: number,
 *   total: number, message: string}} — never throws.
 */
export function ingestStatus(state) {
  const s = (state && typeof state === 'object') ? state : {};
  const papers = s.papers instanceof Map ? s.papers : new Map();
  const jobs = s.activeJobs instanceof Map ? s.activeJobs : new Map();

  let pending = 0;
  let failed = 0;
  let ready = 0;
  for (const p of papers.values()) {
    if (!p || p.is_draft) continue;
    if (p.status === 'done') ready += 1;
    else if (p.status === 'failed') failed += 1;
    else pending += 1;
  }

  // An add/ingest job still running means more papers are on the way even if
  // they have not appeared in the papers map yet.
  let jobsRunning = 0;
  for (const j of jobs.values()) {
    if (j && (j.kind === 'add' || j.kind === 'ingest')) jobsRunning += 1;
  }

  // "Busy" means work is genuinely in flight. Papers sitting at pending with no
  // running job are not being added — they are simply not analyzed yet, and
  // saying otherwise would be a lie the user waits on forever.
  const busy = jobsRunning > 0;
  const total = ready + pending + failed;

  let message = '';
  if (busy) {
    const n = pending > 0 ? pending : jobsRunning;
    message = `${n} paper${n === 1 ? ' is' : 's are'} still being added. `
      + `Generate now and directions will only use the ${ready} already analyzed.`;
  } else if (pending > 0) {
    message = `${pending} paper${pending === 1 ? ' has' : 's have'} not been analyzed yet — `
      + `directions will use the ${ready} analyzed one${ready === 1 ? '' : 's'}. `
      + `Retry them from the Library to include them.`;
  } else if (failed > 0) {
    message = `${ready} of ${total} papers analyzed — ${failed} could not be downloaded. `
      + `Add those PDFs manually from the Library so they count toward your directions.`;
  }

  return { busy, pending: pending + jobsRunning, failed, ready, total, message };
}

/**
 * One sentence naming exactly what the directions were grounded in.
 * @param {object|null} grounding — {papers, concepts, gaps, total} from the API
 * @returns {string} — '' when there is nothing to report. Never throws.
 */
export function provenanceLine(grounding) {
  const g = (grounding && typeof grounding === 'object') ? grounding : null;
  if (!g) return '';
  const papers = Number(g.papers) || 0;
  const concepts = Number(g.concepts) || 0;
  const gaps = Number(g.gaps) || 0;
  if (papers + concepts + gaps === 0) return '';

  const parts = [];
  if (papers) parts.push(`${papers} paper${papers === 1 ? '' : 's'}`);
  if (concepts) parts.push(`${concepts} concept${concepts === 1 ? '' : 's'} from your graph`);
  if (gaps) parts.push(`${gaps} open gap${gaps === 1 ? '' : 's'}`);

  let list;
  if (parts.length === 1) list = parts[0];
  else if (parts.length === 2) list = `${parts[0]} and ${parts[1]}`;
  else list = `${parts.slice(0, -1).join(', ')}, and ${parts[parts.length - 1]}`;

  return `Grounded in ${list}.`;
}

/** What the Research Directions section does, shown above the button. */
export const DIRECTIONS_INTRO =
  'Turns what you have collected into concrete things you could work on. It reads '
  + 'your topic, the papers you added, the concepts in your knowledge graph, and the '
  + 'open gaps your papers themselves report — then proposes research directions, each '
  + 'citing the real papers behind it.';

/** Shown under generated directions. */
export const DIRECTIONS_DISCLAIMER =
  'AI-suggested and not exhaustive — these come only from the papers you have '
  + 'actually added, so adding more will change them. Open the cited papers and '
  + 'verify before acting on a direction.';
