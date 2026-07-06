/**
 * api.js — Fetch wrappers for every Research Lab endpoint.
 * JSON errors are thrown as Error with server "detail" when present.
 */

// ---------------------------------------------------------------------------
// Core fetch helper
// ---------------------------------------------------------------------------

async function _fetch(method, path, body) {
  const opts = {
    method,
    headers: {},
  };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }

  const res = await fetch(path, opts);
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

/** POST /api/papers/{id}/retry */
export const retryPaper = (paperId) => post(`/api/papers/${encodeURIComponent(paperId)}/retry`);

/** DELETE /api/papers/{id} */
export const deletePaper = (paperId) => del(`/api/papers/${encodeURIComponent(paperId)}`);

/** GET /api/draft — returns { draft_paper_id } */
export const getDraft = () => get('/api/draft');

/** POST /api/draft — set draft. body: { paper_id: string|null } */
export const setDraft = (paperId) => post('/api/draft', { paper_id: paperId });

/** GET /api/sections — returns section array */
export const getSections = () => get('/api/sections');

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

/** POST /api/ingest — body: { folder: string } */
export const ingest = (folder) => post('/api/ingest', { folder });

/** POST /api/align — body: { paper_id, against?, force? } */
export const align = (paperId, against, force = false) =>
  post('/api/align', { paper_id: paperId, against: against || null, force });

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
