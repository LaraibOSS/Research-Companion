/**
 * tests/js/researchGuard.test.mjs — ensureActiveResearch() decision + glue.
 * Run: node --test tests/js/researchGuard.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { ensureActiveResearch } from '../../research_companion/lab/static/js/researchGuard.js';

function fakeStore(activeId) {
  return {
    getState: () => ({ workspaces: { list: activeId ? [{ id: activeId, name: 'Main' }] : [], activeId } }),
    setWorkspaces: () => {},
  };
}

function fakeApi({ createOk = true, activateOk = true } = {}) {
  return {
    createWorkspace: async (name) => {
      if (!createOk) throw new Error('create failed');
      return { id: name.toLowerCase().replace(/\s+/g, '-'), name };
    },
    activateWorkspace: async () => {
      if (!activateOk) throw new Error('activate failed');
      return { active: true, reload: false };
    },
    getWorkspaces: async () => ({ active: 'brand-new', workspaces: [{ id: 'brand-new', name: 'Brand New' }] }),
  };
}

test('ensureActiveResearch: passthrough runs the action immediately when active', async () => {
  let ran = false;
  const result = await ensureActiveResearch(() => { ran = true; return 'ok'; }, {
    storeRef: fakeStore('main'),
    apiRef: fakeApi(),
    promptFn: async () => { throw new Error('must not prompt when active'); },
  });
  assert.equal(ran, true);
  assert.equal(result, 'ok');
});

test('ensureActiveResearch: prompts, creates, activates, then runs the action when none active', async () => {
  let ran = false;
  const result = await ensureActiveResearch(() => { ran = true; return 'ok'; }, {
    storeRef: fakeStore(null),
    apiRef: fakeApi(),
    promptFn: async () => 'Brand New',
  });
  assert.equal(ran, true);
  assert.equal(result, 'ok');
});

test('ensureActiveResearch: cancelled prompt resolves to null without running the action', async () => {
  let ran = false;
  const result = await ensureActiveResearch(() => { ran = true; }, {
    storeRef: fakeStore(null),
    apiRef: fakeApi(),
    promptFn: async () => null,
  });
  assert.equal(ran, false);
  assert.equal(result, null);
});

test('ensureActiveResearch: a failed create never throws, resolves null', async () => {
  let ran = false;
  const result = await ensureActiveResearch(() => { ran = true; }, {
    storeRef: fakeStore(null),
    apiRef: fakeApi({ createOk: false }),
    promptFn: async () => 'Brand New',
  });
  assert.equal(ran, false);
  assert.equal(result, null);
});

test('ensureActiveResearch: a failed activate never throws, resolves null', async () => {
  let ran = false;
  const result = await ensureActiveResearch(() => { ran = true; }, {
    storeRef: fakeStore(null),
    apiRef: fakeApi({ activateOk: false }),
    promptFn: async () => 'Brand New',
  });
  assert.equal(ran, false);
  assert.equal(result, null);
});

test('ensureActiveResearch: duplicate name is rejected before any API call', async () => {
  let created = false;
  const api = fakeApi();
  const wrappedApi = { ...api, createWorkspace: async (n) => { created = true; return api.createWorkspace(n); } };
  const store = {
    getState: () => ({ workspaces: { list: [{ id: 'main', name: 'Main' }], activeId: null } }),
    setWorkspaces: () => {},
  };
  const result = await ensureActiveResearch(() => 'ok', {
    storeRef: store,
    apiRef: wrappedApi,
    promptFn: async () => 'main',
  });
  assert.equal(created, false);
  assert.equal(result, null);
});
