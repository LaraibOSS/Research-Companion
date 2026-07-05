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
    throw new Error(detail || `HTTP ${res.status}`);
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
