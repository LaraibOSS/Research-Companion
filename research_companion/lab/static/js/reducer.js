/**
 * reducer.js — Pure, DOM-free state reducer for the Research Lab.
 *
 * applyEvent(state, evt) -> string[]  (list of changed topics to notify)
 *
 * State shape:
 *   papers:    Map<paper_id, paper>
 *   draftId:   string | null
 *   sections:  []
 *   lab:       { counts: {} }
 *   jobs:      Map<string, job>
 *   connection: string
 *   failures:  {}
 *   graphSeq:  number
 *   ingestLog: Array<{ok, label, path, stage, error, paperId, seq}>
 *              Flat list of per-file ingest outcomes keyed by insertion order (seq).
 *              Each ingest_failed pushes {ok:false, ...}.
 *              Each paper_added during an active job pushes {ok:true, label, paperId}.
 *              The progressDock derives its mini-list from this array.
 */

/**
 * Apply a single SSE event to the state object (mutates in place).
 * Returns an array of topic strings that changed (for subscribers).
 * Unknown event kinds are silently ignored and return [].
 *
 * @param {object} state
 * @param {object} evt  — parsed JSON event with an "event" discriminator
 * @returns {string[]}  — changed topics
 */
export function applyEvent(state, evt) {
  const kind = evt && evt.event;
  if (!kind) return [];

  switch (kind) {
    case 'paper_added': {
      const existing = state.papers.get(evt.paper_id) || {};
      state.papers.set(evt.paper_id, {
        ...existing,
        paper_id: evt.paper_id,
        title: evt.title || existing.title || '',
        source: evt.source || existing.source || '',
        status: 'processing',
        authors: existing.authors || [],
        year: existing.year || null,
        strength: existing.strength || null,
        is_draft: existing.is_draft || false,
        stance_counts: existing.stance_counts || { strengthens: 0, challenges: 0, alternative: 0 },
        failure_reason: null,
      });

      // If a job is active, push a success entry to ingestLog for the dock mini-list
      if (!state.ingestLog) state.ingestLog = [];
      const activeJob = state.jobs && state.jobs.get('ingest');
      if (activeJob && activeJob.status === 'running') {
        const label = evt.title
          || (evt.source ? _basename(evt.source) : null)
          || evt.paper_id;
        state.ingestLog.push({
          ok:      true,
          label,
          paperId: evt.paper_id,
          seq:     state.ingestLog.length,
        });
        return ['papers', 'ingestLog'];
      }

      return ['papers'];
    }

    case 'section_tree_built': {
      // Mark paper with section count; no material state change for UI topics
      const paper = state.papers.get(evt.paper_id);
      if (paper) {
        paper.n_sections = evt.n_sections;
      }
      return ['papers'];
    }

    case 'section_extracted': {
      // Section detail for a paper — acknowledged; no top-level state change
      return [];
    }

    case 'graph_delta': {
      state.graphSeq = (state.graphSeq || 0) + 1;
      return ['graph'];
    }

    case 'alignment_ready': {
      const paper = state.papers.get(evt.paper_id);
      if (paper) {
        paper.stance = evt.verdict;
        paper.score = evt.score;
        // Flag that stance_counts (server-side aggregate) may be stale;
        // main.js watches for this and triggers a debounced GET /api/papers.
        paper.alignmentFresh = false;
      }
      // Notify 'alignment' topic so draft view can re-fetch alignment data
      return ['papers', 'alignment'];
    }

    case 'strength_updated': {
      const paper = state.papers.get(evt.paper_id);
      if (paper) {
        paper.strength = {
          score: evt.score,
          band: evt.band,
          color: evt.color,
        };
      }
      return ['papers'];
    }

    case 'ingest_failed': {
      const paperId = evt.paper_id;
      const failKey = paperId || evt.path;

      // Record failure
      state.failures[failKey] = {
        path: evt.path,
        stage: evt.stage,
        error: evt.error,
        paper_id: paperId || null,
      };

      // Mark paper failed if we have a paper_id
      if (paperId) {
        const paper = state.papers.get(paperId);
        if (paper) {
          paper.status = 'failed';
          paper.failure_reason = evt.error;
        }
        // Also record by path for lookup
        if (evt.path && evt.path !== paperId) {
          state.failures[evt.path] = state.failures[failKey];
        }
      }

      // Push failure entry to ingestLog for dock mini-list
      if (!state.ingestLog) state.ingestLog = [];
      state.ingestLog.push({
        ok:      false,
        label:   evt.path || paperId || '',
        path:    evt.path || '',
        stage:   evt.stage || '',
        error:   evt.error || '',
        paperId: paperId || null,
        seq:     state.ingestLog.length,
      });

      return ['papers', 'failures', 'ingestLog'];
    }

    case 'ingest_progress': {
      const prevJob = state.jobs.get('ingest');
      // If no prior job (or prior was done), this is a new ingest run — reset log
      if (!prevJob || prevJob.status === 'done') {
        state.ingestLog = [];
      }
      state.jobs.set('ingest', {
        status: 'running',
        done: evt.done,
        total: evt.total,
        current: evt.current || '',
      });
      return ['jobs'];
    }

    case 'job_done': {
      const jobName = evt.job || 'ingest';
      // Mark the job done
      const existing = state.jobs.get(jobName) || {};
      state.jobs.set(jobName, { ...existing, status: 'done' });

      // Transition all 'processing' papers to 'done'
      for (const [pid, paper] of state.papers) {
        if (paper.status === 'processing') {
          paper.status = 'done';
        }
      }
      return ['jobs', 'papers'];
    }

    case 'suggestions_updated': {
      if (!state.suggestionCounts) state.suggestionCounts = { open: 0, by_severity: null };
      state.suggestionCounts.open = evt.open || 0;
      state.suggestionCounts.by_severity = evt.by_severity || null;
      return ['suggestions'];
    }

    case 'draft_version_added': {
      return ['journey'];
    }

    // W3-F5: gaps analysis completed
    case 'gaps_updated': {
      return ['gaps'];
    }

    default:
      return [];
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Extract the basename from a path string (handles / and \ separators).
 * @param {string} p
 * @returns {string}
 */
function _basename(p) {
  if (!p) return '';
  return p.replace(/^.*[/\\]/, '');
}
