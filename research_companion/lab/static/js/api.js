/**
 * api.js — Fetch wrappers for every Research Lab endpoint.
 * JSON errors are thrown as Error with server "detail" when present.
 */

// ---------------------------------------------------------------------------
// Core fetch helper
// ---------------------------------------------------------------------------

async function _handleResponse(res) {
  if (!res.ok) {
    let detail;
    try {
      const json = await res.json();
      detail = json.detail || JSON.stringify(json);
    } catch {
      detail = await res.text().catch(() => res.statusText);
    }
    const err = new Error(detail || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  // No content responses (DELETE returning 204, etc.)
  if (res.status === 204) return null;
  return res.json();
}

async function _fetch(method, path, body) {
  const opts = {
    method,
    headers: {},
  };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }

  return _handleResponse(await fetch(path, opts));
}

const get  = (path)        => _fetch('GET',    path);
const post = (path, body)  => _fetch('POST',   path, body);
const del  = (path)        => _fetch('DELETE', path);

// ---------------------------------------------------------------------------
// Endpoint registry
// ---------------------------------------------------------------------------

/** GET /api/lab — returns { draft_id, paper_count, node_count, edge_count, active_jobs } */
export const getLab = () => get('/api/lab');

/** GET /api/papers — returns paper array */
export const getPapers = () => get('/api/papers');

/** POST /api/papers — add a paper. body: { target: string } */
export const addPaper = (target) => post('/api/papers', { target });

/** POST /api/papers/upload — raw PDF body. file: File/Blob, setDraft: boolean.
 *  Returns { job_id, paper_id, duplicate, draft_set }. */
export async function uploadPaper(file, setDraft = false) {
  const url = `/api/papers/upload?filename=${encodeURIComponent(file.name || '')}`
    + `&set_draft=${setDraft ? 'true' : 'false'}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/pdf' },
    body: file,
  });
  return _handleResponse(res);
}

/** POST /api/papers/{id}/retry */
export const retryPaper = (paperId) => post(`/api/papers/${encodeURIComponent(paperId)}/retry`);

/**
 * POST /api/papers/{id}/pdf — upload a replacement PDF for an EXISTING
 * (usually failed, "no PDF on disk") paper. Raw body, same convention as
 * uploadPaper above. Returns { job_id, paper_id }. 404 unknown paper,
 * 400 non-PDF body, 415 wrong content type, 413 oversize.
 */
export async function uploadPaperPdf(paperId, file) {
  const res = await fetch(`/api/papers/${encodeURIComponent(paperId)}/pdf`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/pdf' },
    body: file,
  });
  return _handleResponse(res);
}

/**
 * POST /api/papers/{id}/find-pdf — search open-access sources for a PDF for
 * a paper whose ingest failed with a missing-PDF reason. Returns {job_id}.
 * 404 no failure record for this paper, 409 failure is not a missing-PDF one.
 * A miss still completes the job ("done") and updates the summary's oa_links.
 */
export const findPdf = (paperId) =>
  post(`/api/papers/${encodeURIComponent(paperId)}/find-pdf`);

/**
 * POST /api/papers/find-pdfs — sweep every missing-PDF failure. Returns
 * 202 {job_id, count} when there's work to do, or 200 {count: 0} when there
 * are no missing-PDF failures. 409 when a sweep is already running.
 */
export const findAllPdfs = () => post('/api/papers/find-pdfs');

/** DELETE /api/papers/{id} */
export const deletePaper = (paperId) => del(`/api/papers/${encodeURIComponent(paperId)}`);

/**
 * PATCH /api/papers/{id} — manual metadata edit. body: { title?, authors?, year? }
 * (only sent fields applied). Returns the FULL per-paper dict.
 * Rules: authors:[] clears; year:null clears; never send title:null/authors:null.
 */
export const patchPaper = (id, body) =>
  _fetch('PATCH', `/api/papers/${encodeURIComponent(id)}`, body);

/** GET /api/draft — returns { draft_paper_id } */
export const getDraft = () => get('/api/draft');

/** POST /api/draft — set draft. body: { paper_id: string|null } */
export const setDraft = (paperId) => post('/api/draft', { paper_id: paperId });

/** GET /api/sections — returns section array */
export const getSections = () => get('/api/sections');

/**
 * GET /api/papers/{id}/text[?q=<quote>] — full text + sections for the reader.
 * Returns { paper_id, title, full_text, has_pdf, sections, quote_range }.
 * 404 when the paper has no readable text.
 */
export const getPaperText = (id, q) =>
  get(`/api/papers/${encodeURIComponent(id)}/text${q ? `?q=${encodeURIComponent(q)}` : ''}`);

/** URL for the inline original PDF of a paper (GET /api/papers/{id}/pdf). */
export const paperPdfUrl = (id) => `/api/papers/${encodeURIComponent(id)}/pdf`;

/**
 * GET /api/papers/{id}/simplified — reader "Simplified" tab payload.
 * Returns { extraction: dict|null, rewrite: {provider,model,created_at,groups}|null,
 * has_extraction, provider_configured }. 404 unknown paper.
 */
export const getSimplified = (id) =>
  get(`/api/papers/${encodeURIComponent(id)}/simplified`);

/**
 * POST /api/papers/{id}/simplify — kick off an on-demand LLM "Simplify
 * further" rewrite job. Returns 202 {job_id}. 409 when the paper has no
 * stored text to simplify.
 */
export const postSimplify = (id) =>
  post(`/api/papers/${encodeURIComponent(id)}/simplify`);

/** GET /api/draft/alignment */
export const getDraftAlignment = () => get('/api/draft/alignment');

/** GET /api/papers/{id}/alignment */
export const getPaperAlignment = (paperId) =>
  get(`/api/papers/${encodeURIComponent(paperId)}/alignment`);

/** GET /api/graph?section=... */
export const getGraph = (sectionId) => {
  const url = sectionId
    ? `/api/graph?section=${encodeURIComponent(sectionId)}`
    : '/api/graph';
  return get(url);
};

/** GET /api/failures */
export const getFailures = () => get('/api/failures');

/** GET /api/jobs/{id} */
export const getJob = (jobId) => get(`/api/jobs/${encodeURIComponent(jobId)}`);

/** POST /api/ingest — body: { folder: string, paths?: string[] } */
export const ingest = (folder, paths) => post('/api/ingest', paths ? { folder, paths } : { folder });

/**
 * POST /api/ingest/scan — body: { folder: string }
 * Returns { discovered, already, files:[{name, path, rel_path, already_in_library}] }.
 * 400 on empty/invalid folder.
 */
export const scanFolder = (folder) => post('/api/ingest/scan', { folder });

/** POST /api/align — body: { paper_id, against?, force? } */
export const align = (paperId, against, force = false) =>
  post('/api/align', { paper_id: paperId, against: against || null, force });

/**
 * POST /api/draft/analyze — "Analyze this draft": bulk-align every analyzed
 * library paper against the current draft as a background job. Returns
 * { ok: true, job_id, total } on start, or { ok: false, error } when there is
 * no draft / no model / nothing to analyze (never a 500).
 */
export const analyzeDraft = (force = false) =>
  post('/api/draft/analyze', { force });

/** POST /api/ask — body: { question, section_id? } */
export const ask = (question, sectionId) =>
  post('/api/ask', { question, section_id: sectionId || null });

/** POST /api/compare — body: { paper_a, paper_b } */
export const compare = (paperA, paperB) =>
  post('/api/compare', { paper_a: paperA, paper_b: paperB });

/** GET /api/settings — returns settings with keys block (masked) */
export const getSettings = () => get('/api/settings');

/** PUT /api/settings — partial update; returns updated settings */
export const putSettings = (patch) => _fetch('PUT', '/api/settings', patch);

// ---------------------------------------------------------------------------
// Saved-views endpoints (W3-F6)
// ---------------------------------------------------------------------------

/** GET /api/views — returns { views: [{view_id, name, created_at, source, node_ids, pinned}] } */
export const getViews = () => get('/api/views');

/** POST /api/views — body: { name, source?, node_ids? }; returns 201 with view object */
export const createView = (body) => post('/api/views', body);

/** PATCH /api/views/{id} — body: { name?, pinned? }; returns updated view */
export const patchView = (id, body) => _fetch('PATCH', `/api/views/${encodeURIComponent(id)}`, body);

/** DELETE /api/views/{id} — returns { removed: true } */
export const deleteView = (id) => del(`/api/views/${encodeURIComponent(id)}`);

/** GET /api/views/{id}/graph — returns serialize_graph shape + { view, missing_node_ids } */
export const getViewGraph = (id) => get(`/api/views/${encodeURIComponent(id)}/graph`);

// ---------------------------------------------------------------------------
// Suggestions endpoints (W3-F3)
// ---------------------------------------------------------------------------

/** GET /api/suggestions[?status=] — returns { draft_paper_id, suggestions, counts } */
export const getSuggestions = (status) => {
  const url = status ? `/api/suggestions?status=${encodeURIComponent(status)}` : '/api/suggestions';
  return get(url);
};

/** POST /api/suggestions/{id}/dismiss */
export const dismissSuggestion = (id) =>
  post(`/api/suggestions/${encodeURIComponent(id)}/dismiss`);

/** POST /api/suggestions/regenerate — body: { include_llm } */
export const regenerateSuggestions = (includeLlm = false) =>
  post('/api/suggestions/regenerate', { include_llm: includeLlm });

/** GET /api/journey — returns { versions, events, counts_over_time, current } */
export const getJourney = () => get('/api/journey');

// ---------------------------------------------------------------------------
// Converse endpoints (W3-F4)
// ---------------------------------------------------------------------------

/**
 * POST /api/converse — body: { context, message, conversation_id? }
 * Returns { answer, citations, unverified_quotes, conversation_id }
 */
export const converse = (body) => post('/api/converse', body);

/**
 * GET /api/conversations/{id} — returns { meta, turns }
 * 404 for unknown conversation.
 */
export const getConversation = (id) =>
  get(`/api/conversations/${encodeURIComponent(id)}`);

/**
 * DELETE /api/conversations/{id} — returns { removed: true }.
 * 404 for unknown conversation.
 */
export const deleteConversation = (id) =>
  del(`/api/conversations/${encodeURIComponent(id)}`);

// ---------------------------------------------------------------------------
// Temporal + Gaps endpoints (W3-F5)
// ---------------------------------------------------------------------------

/**
 * GET /api/temporal — returns { years, papers_per_year, tracks,
 *   skipped_papers_without_year, truncated_tracks }
 */
export const getTemporal = () => get('/api/temporal');

/**
 * GET /api/gaps — returns { papers, draft_addresses, stale }
 */
export const getGaps = () => get('/api/gaps');

/**
 * POST /api/gaps/refresh — triggers gap re-analysis job
 */
export const refreshGaps = () => post('/api/gaps/refresh');

// ---------------------------------------------------------------------------
// Deep-Research Report endpoints (Phase 2, slice 2e-1)
// ---------------------------------------------------------------------------

/**
 * GET /api/report — returns { topic, sections, question_count, stale, plan }
 */
export const getReport = () => get('/api/report');

/**
 * GET /api/report/export — returns { markdown } (Deep-Research Report
 * export, 2e-5). Unguarded, read-only — mirrors exportNotes.
 */
export const exportReport = () => get('/api/report/export');

/**
 * POST /api/report/plan { topic } — Editable Research Plan (2e-4).
 * MUTATING (saves a draft plan) + guarded (409 with no active workspace,
 * like refreshReport) but SYNCHRONOUS -- one LLM call, like
 * POST /api/directions -- returns the result directly, no job_id/poll. A
 * generation failure comes back as 200 {ok:false, error} rather than an
 * HTTP error (never 500), so callers must check `data.ok` in addition to
 * catching network rejections. Returns { ok, plan?: {topic, questions,
 * status}, error? }.
 */
export function reportPlan(params = {}) {
  const { topic } = params;
  return post('/api/report/plan', { topic: topic || '' });
}

/**
 * POST /api/report/refresh { topic, questions? } — triggers report-generation
 * job. MUTATING + guarded (409 with no active workspace, like
 * POST /api/directions/draft). `questions` is optional (Editable Research
 * Plan, 2e-4): when it is a non-empty array, the server answers EXACTLY
 * those questions and skips its own question-generation LLM call;
 * omitted/empty preserves the original one-shot behavior (2e-1) unchanged.
 * Returns { job_id }.
 */
export function refreshReport(params = {}) {
  const { topic, questions } = params;
  const body = { topic: topic || '' };
  if (Array.isArray(questions) && questions.length > 0) {
    body.questions = questions;
  }
  return post('/api/report/refresh', body);
}

// ---------------------------------------------------------------------------
// Report Evidence Scoring (RCS) endpoint (Phase 2, slice 2e-2)
// ---------------------------------------------------------------------------

/**
 * POST /api/report/score-evidence — triggers an RCS evidence-scoring job
 * over the currently saved report. MUTATING + guarded (409 with no active
 * workspace, like refreshReport). No body. Returns { job_id }.
 */
export const scoreEvidence = () => post('/api/report/score-evidence');

// ---------------------------------------------------------------------------
// Workspace endpoints (W4-F1)
// ---------------------------------------------------------------------------

/** GET /api/workspaces — returns { active, workspaces: [{id, name, created_at, archived, stats}] } */
export const getWorkspaces = () => get('/api/workspaces');

/** POST /api/workspaces — body: { name }; 201 record (409 duplicate, 422 invalid) */
export const createWorkspace = (name) => post('/api/workspaces', { name });

/** PATCH /api/workspaces/{id} — body: { name?, archived? }; returns updated record */
export const patchWorkspace = (id, body) =>
  _fetch('PATCH', `/api/workspaces/${encodeURIComponent(id)}`, body);

/** DELETE /api/workspaces/{id} — returns { removed, active, switched } (404 unknown, 409 job running) */
export const deleteWorkspace = (id) => del(`/api/workspaces/${encodeURIComponent(id)}`);

/** POST /api/workspaces/{id}/activate — returns { active, reload } (409 archived/job running) */
export const activateWorkspace = (id) =>
  post(`/api/workspaces/${encodeURIComponent(id)}/activate`);

// ---------------------------------------------------------------------------
// Citation coverage endpoints (W5-C3)
// ---------------------------------------------------------------------------

/**
 * GET /api/draft/citations — returns citation coverage for the current draft.
 * Always returns 200 (no draft: empty counts).
 */
export const getDraftCitations = () => get('/api/draft/citations');

/**
 * GET /api/draft/placement — citation-placement check for the current draft.
 * Always returns 200 (no draft / not applicable: empty placements).
 */
export const getDraftPlacement = () => get('/api/draft/placement');

/**
 * POST /api/draft/citations/resolve — kick off background resolution job.
 * Returns 202 {job_id} | 400 no draft | 409 already running.
 */
export const resolveCitations = () => post('/api/draft/citations/resolve');

/**
 * POST /api/draft/citations/link — manually link a cited reference to a library
 * paper. body: { index, paper_id }. Returns the full updated coverage payload
 * (same shape as GET /api/draft/citations).
 * 400 no-draft / index out of range | 404 unknown paper.
 */
export const linkCitation = (index, paperId) =>
  post('/api/draft/citations/link', { index, paper_id: paperId });

/**
 * POST /api/draft/citations/unlink — undo a manual link created by
 * linkCitation. body: { index }. Returns the full updated coverage payload
 * (same shape as GET /api/draft/citations).
 * 400 no-draft / index out of range / ref is not a manual link.
 */
export const unlinkCitation = (index) =>
  post('/api/draft/citations/unlink', { index });

// ---------------------------------------------------------------------------
// Background-activity endpoints (W5-ACT)
// ---------------------------------------------------------------------------

/**
 * GET /api/jobs — returns { jobs: [{job_id, kind, label, target, status}] } (RUNNING only).
 * Used at boot for hydration. Non-fatal when 404 (older server).
 */
export const getJobs = () => get('/api/jobs');

// ---------------------------------------------------------------------------
// Draft opportunities + revision notes endpoints (uncited-paper opportunities)
// ---------------------------------------------------------------------------

/**
 * GET /api/draft/opportunities — uncited library papers that would
 * strengthen/challenge/offer alternatives to draft sections. Returns
 * { draft_id, sections: [{section_id, section_title, suggestions}] }.
 * Always 200 (no draft: { draft_id: null, sections: [] }).
 */
export const getOpportunities = () => get('/api/draft/opportunities');

/** GET /api/notes — returns { notes: [...] } (workspace-scoped revision notes). */
export const getNotes = () => get('/api/notes');

/**
 * POST /api/notes — record a note captured from an opportunity suggestion.
 * body: { draft_section_id, draft_section_title, paper_id, paper_title,
 *   relation, relevance, rationale, evidence_quote, evidence_section_id, comment }.
 * Dedupes in place against an existing OPEN note for the same
 * (paper_id, draft_section_id). Returns the saved note record.
 */
export const saveNote = (record) => post('/api/notes', record);

/**
 * PATCH /api/notes/{id} — body: { status?, comment? }. Returns the updated
 * note record. 404 unknown note.
 */
export const updateNote = (id, patch) =>
  _fetch('PATCH', `/api/notes/${encodeURIComponent(id)}`, patch);

/** DELETE /api/notes/{id} — returns { deleted: id }. 404 unknown note. */
export const deleteNote = (id) => del(`/api/notes/${encodeURIComponent(id)}`);

/**
 * GET /api/notes/export?group_by=<paper|section> — returns { markdown }
 * (Revision notes doc). Defaults to grouping by section.
 */
export const exportNotes = (groupBy = 'section') =>
  get('/api/notes/export?group_by=' + encodeURIComponent(groupBy));

// ---------------------------------------------------------------------------
// Discover / Brainstorm endpoint (feat/brainstorm-discover)
// ---------------------------------------------------------------------------

/**
 * GET /api/discover?q=&year_min=&year_max=&limit=&expand=
 * Read-only topic search. Always 200 — a search/LLM failure server-side
 * comes back as {results:[], error:"..."} rather than an HTTP error, so
 * callers should check `data.error` in addition to catching network
 * rejections. Returns { results, queries_used, expanded, error? }.
 *
 * @param {{q?:string, yearMin?:number|string, yearMax?:number|string,
 *   limit?:number, expand?:boolean, rank?:'balanced'|'citations'|'venue'}} params
 */
export function discover(params = {}) {
  const { q, yearMin, yearMax, limit, expand, rank } = params;
  const usp = new URLSearchParams();
  if (q) usp.set('q', q);
  if (yearMin) usp.set('year_min', String(yearMin));
  if (yearMax) usp.set('year_max', String(yearMax));
  if (limit) usp.set('limit', String(limit));
  if (expand) usp.set('expand', '1');
  if (rank) usp.set('rank', String(rank));
  return get(`/api/discover?${usp.toString()}`);
}

// ---------------------------------------------------------------------------
// Research Directions endpoint (feat/brainstorm-directions, Brainstorm 2b)
// ---------------------------------------------------------------------------

/**
 * POST /api/directions { topic, year_min?, year_max?, seeds? }
 * Research Directions (Brainstorm 2b) -- a synchronous, ephemeral endpoint
 * like GET /api/discover. Always 200 -- a search/LLM failure server-side
 * comes back as {directions:[], error:"..."} rather than an HTTP error, so
 * callers should check `data.error` in addition to catching network
 * rejections. Returns { directions, topic, error? }.
 *
 * @param {{topic?:string, yearMin?:number|string, yearMax?:number|string,
 *   seeds?:object[]}} params
 */
export function directions(params = {}) {
  const { topic, yearMin, yearMax, seeds } = params;
  const body = {
    topic: topic || '',
    year_min: yearMin ? Number(yearMin) : null,
    year_max: yearMax ? Number(yearMax) : null,
    seeds: Array.isArray(seeds) ? seeds : [],
  };
  return post('/api/directions', body);
}

// ---------------------------------------------------------------------------
// Brainstorm session persistence (per research; survives revisits/reloads)
// ---------------------------------------------------------------------------

/**
 * POST /api/brief { topic, direction?, session_paper_ids? } — Brainstorm Brief:
 * grounded, cited bullet outline from the topic + this session's papers. Always
 * 200 like /api/directions: returns { ok, brief:{brief_id, topic, sections}, error? }.
 */
export const brief = (params = {}) =>
  post('/api/brief', {
    topic: params.topic || '',
    direction: params.direction || null,
    session_paper_ids: Array.isArray(params.sessionPaperIds) ? params.sessionPaperIds : [],
  });

/**
 * POST /api/claim-audit { target } — audit whether each cited source actually
 * supports the claim citing it. Opt-in and advisory; returns
 * { ok, job_id, target } or { ok: false, error }.
 */
export const runClaimAudit = (target = 'report') =>
  post('/api/claim-audit', { target });

/** GET /api/claim-audit?target= -> { target, audit: {...}|null }. */
export const getClaimAudit = (target = 'report') =>
  get(`/api/claim-audit?target=${encodeURIComponent(target)}`);

/** GET /api/brainstorm/session -> { session: <blob>|null }. Never errors. */
export const getBrainstormSession = () => get('/api/brainstorm/session');

/** PUT /api/brainstorm/session { session } -> { ok }. Guarded (needs an active research). */
export const putBrainstormSession = (session) =>
  _fetch('PUT', '/api/brainstorm/session', { session });

// ---------------------------------------------------------------------------
// Novelty Gate endpoint (feat/brainstorm-novelty, Brainstorm 2c)
// ---------------------------------------------------------------------------

/**
 * POST /api/novelty { title, rationale, year_min?, year_max? }
 * Novelty Gate (Brainstorm 2c) -- checks one research direction's
 * title+rationale against real, freshly-searched prior work. Synchronous,
 * ephemeral, like GET /api/discover and POST /api/directions. Always 200 --
 * a search/LLM failure server-side comes back as
 * {verdict:null, prior_works:[], error:"..."} rather than an HTTP error, so
 * callers should check `data.error` in addition to catching network
 * rejections. Returns { verdict, confidence, rationale, closest_prior,
 * prior_works, query, error? }.
 *
 * @param {{title?:string, rationale?:string, yearMin?:number|string,
 *   yearMax?:number|string}} params
 */
export function checkNovelty(params = {}) {
  const { title, rationale, yearMin, yearMax } = params;
  const body = {
    title: title || '',
    rationale: rationale || '',
    year_min: yearMin ? Number(yearMin) : null,
    year_max: yearMax ? Number(yearMax) : null,
  };
  return post('/api/novelty', body);
}

// ---------------------------------------------------------------------------
// Draft scaffolding endpoint (feat/brainstorm-scaffold, Brainstorm 2d)
// ---------------------------------------------------------------------------

/**
 * POST /api/directions/draft { title, rationale?, direction_type?, citations? }
 * "Draft this direction" (Brainstorm 2d) -- MUTATING: creates a real draft
 * in the active research from one chosen direction's outline. Guarded
 * (409 with no active workspace, unlike discover/directions/novelty) and
 * atomic-on-success server-side: a failure returns 200 {ok:false, error}
 * and creates nothing. Returns { ok, paper_id?, draft_paper_id?,
 * section_count?, replaced_draft?, error? }.
 *
 * @param {{title?:string, rationale?:string, directionType?:string,
 *   citations?:object[]}} direction
 */
export function scaffoldDraft(direction = {}) {
  const { title, rationale, directionType, citations } = direction;
  const body = {
    title: title || '',
    rationale: rationale || '',
    direction_type: directionType || '',
    citations: Array.isArray(citations) ? citations : [],
  };
  return post('/api/directions/draft', body);
}
