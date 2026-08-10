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
 *   ingestManifest: Array<{path, name, relPath, status, reason}>
 *              Ordered per-file status list for a folder ingest, keyed by
 *              absolute path. Seeded client-side by store.startIngestManifest;
 *              reconciled here from ingest_progress/paper_added/ingest_failed/
 *              ingest_skipped/job_done. Rows are matched by exact `path`;
 *              events with no matching row (e.g. single-add, phase-notes) are
 *              silently no-ops.
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

/**
 * Find a row in state.ingestManifest by absolute path and mutate its status
 * (and optionally its reason). Returns true if a row was found and mutated.
 * @param {object} state
 * @param {string} path
 * @param {string} status
 * @param {string} [reason]
 * @returns {boolean}
 */
function _setManifestStatus(state, path, status, reason) {
  if (!path || !Array.isArray(state.ingestManifest)) return false;
  const row = state.ingestManifest.find(r => r.path === path);
  if (!row) return false;
  row.status = status;
  if (reason !== undefined) row.reason = reason;
  return true;
}

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
      const topics = ['papers'];
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
        topics.push('ingestLog');
      }

      if (_setManifestStatus(state, evt.path, 'done')) {
        topics.push('ingestManifest');
      }

      return topics;
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

      const failedTopics = ['papers', 'failures', 'ingestLog'];
      if (_setManifestStatus(state, evt.path, 'failed', evt.error || '')) {
        failedTopics.push('ingestManifest');
      }
      return failedTopics;
    }

    case 'ingest_skipped': {
      if (_setManifestStatus(state, evt.path, 'skipped', evt.reason || 'already in library')) {
        return ['ingestManifest'];
      }
      return [];
    }

    case 'ingest_progress': {
      const prevJob = state.jobs.get('ingest');
      const isPhaseNote = (evt.total || 0) === 0 && !!evt.current;

      // A phase-note (e.g. "OCR-ing scanned PDF…") is a mid-file status with no
      // file counts. It must NOT zero an in-progress folder bar, and must not
      // create a lingering empty job when there is no folder run at all.
      if (isPhaseNote) {
        const topics = [];
        // Ride on top of an active folder-ingest bar: keep done/total, update only current.
        if (prevJob && prevJob.status === 'running') {
          state.jobs.set('ingest', { ...prevJob, current: evt.current });
          topics.push('jobs');
        }
        // Surface the phase on any active add/retry job so a single-paper add
        // (no folder bar) still shows the OCR state in the top-bar indicator.
        // Self-clears when the add job's JobFinished removes it from activeJobs.
        if (state.activeJobs) {
          let touched = false;
          for (const [id, job] of state.activeJobs) {
            if (job.kind === 'add' || job.kind === 'retry') {
              state.activeJobs.set(id, { ...job, label: evt.current });
              touched = true;
            }
          }
          if (touched) topics.push('activity');
        }
        return topics;
      }

      // Normal per-file progress.
      // If no prior job (or prior was done), this is a new ingest run — reset log.
      const progressTopics = ['jobs'];
      if (!prevJob || prevJob.status === 'done') {
        state.ingestLog = [];
        // Drop a STALE manifest left over from a prior run that this run did
        // not seed — e.g. an ingest started outside this UI (CLI / another
        // tab). If the incoming file isn't in the manifest, it can't be ours,
        // so clear it and fall back to the flat ingestLog view. A manifest this
        // UI just seeded always contains the current run's files, so it stays.
        if (Array.isArray(state.ingestManifest) && state.ingestManifest.length
            && !state.ingestManifest.some(r => r.path === evt.current)) {
          state.ingestManifest = [];
          progressTopics.push('ingestManifest');
        }
      }
      state.jobs.set('ingest', {
        status: 'running',
        done: evt.done,
        total: evt.total,
        current: evt.current || '',
      });
      if (_setManifestStatus(state, evt.current, 'processing')
          && !progressTopics.includes('ingestManifest')) {
        progressTopics.push('ingestManifest');
      }
      return progressTopics;
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

      // Sweep the manifest: nothing should be left stuck spinning.
      const doneTopics = ['jobs', 'papers'];
      if (Array.isArray(state.ingestManifest)) {
        let manifestChanged = false;
        for (const row of state.ingestManifest) {
          if (row.status === 'queued' || row.status === 'processing') {
            row.status = 'done';
            manifestChanged = true;
          }
        }
        if (manifestChanged) doneTopics.push('ingestManifest');
      }
      return doneTopics;
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

    // Deep-Research Report completed (Phase 2, slice 2e-1)
    case 'report_updated': {
      return ['report'];
    }

    // W5-ACT: background job started
    case 'job_started': {
      if (!state.activeJobs) state.activeJobs = new Map();
      state.activeJobs.set(evt.job_id, {
        kind:   evt.kind   || '',
        label:  evt.label  || '',
        target: evt.target || '',
      });
      return ['activity'];
    }

    // W5-ACT: background job finished
    case 'job_finished': {
      if (!state.activeJobs) state.activeJobs = new Map();
      state.activeJobs.delete(evt.job_id);
      return ['activity'];
    }

    // W5-C3: citation coverage SSE push (counts-only, marks stale for refetch)
    case 'citation_coverage_updated': {
      if (!state.citationCoverage) state.citationCoverage = {};
      state.citationCoverage = {
        ...state.citationCoverage,
        draft_paper_id: evt.draft_paper_id || null,
        counts: {
          total:      evt.total      || 0,
          in_library: evt.in_library || 0,
          available:  evt.available  || 0,
          unchecked:  evt.unchecked  || 0,
          unresolved: evt.unresolved || 0,
          usable:     (evt.usable !== undefined && evt.usable !== null) ? evt.usable : (evt.in_library || 0),
        },
        stale: true,
      };
      return ['citations'];
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
