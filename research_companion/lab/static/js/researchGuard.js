/**
 * researchGuard.js — ensureActiveResearch(): the "Name your research" gate
 * for the empty (activeId === null) landing state.
 *
 * Pure decision lives in workspaceHelpers.decideResearchGuard(); this module
 * is the thin async glue: prompt -> validate -> create -> activate ->
 * refresh the workspaces snapshot -> run the originally-requested action.
 * Never throws — a cancelled prompt, a duplicate/invalid name, or a failed
 * create/activate resolves to null and shows a toast instead.
 */
import * as store from './store.js';
import * as api from './api.js';
import { showToast } from './components/toast.js';
import { promptDialog } from './components/confirmDialog.js';
import { decideResearchGuard, validateWorkspaceName } from './workspaceHelpers.js';

// showToast touches document; guard it so a DOM-less caller (e.g. the node
// test environment, which doesn't inject a toast dependency) can never turn
// this module's "never throws" promise into a thrown error.
function _safeToast(message, type) {
  try {
    showToast(message, type);
  } catch (_err) {
    // no-op — best-effort UX only, never fatal
  }
}

/**
 * @param {() => any} action — invoked immediately when a research is active
 * @param {{storeRef?: object, apiRef?: object, promptFn?: Function}} [deps]
 *   — injected for testability
 * @returns {Promise<any|null>} the action's return value, or null when
 *   cancelled / invalid / the create+activate failed
 */
export async function ensureActiveResearch(action, deps = {}) {
  const storeRef = deps.storeRef || store;
  const apiRef = deps.apiRef || api;
  const promptFn = deps.promptFn || promptDialog;

  const { workspaces } = storeRef.getState();
  const { decision } = decideResearchGuard(workspaces);
  if (decision === 'passthrough') {
    return action();
  }

  const rawName = await promptFn({
    title: 'Name your research',
    message: 'Give this research a name — you can rename it anytime.',
    placeholder: 'e.g. LLM Safety',
    confirmLabel: 'Create',
  });
  if (!rawName) return null;

  const existingNames = (workspaces.list || []).map(w => w.name || w.id);
  const check = validateWorkspaceName(rawName, existingNames);
  if (!check.ok) {
    _safeToast(check.error, 'error');
    return null;
  }

  try {
    const record = await apiRef.createWorkspace(check.name);
    await apiRef.activateWorkspace(record.id);
    const data = await apiRef.getWorkspaces();
    storeRef.setWorkspaces(data);
  } catch (err) {
    _safeToast(err.message || 'Failed to create research', 'error');
    return null;
  }

  return action();
}
