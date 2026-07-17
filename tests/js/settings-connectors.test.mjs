import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildConnectorsPatch } from '../../research_companion/lab/static/js/settingsHelpers.js';

test('checked -> both connectors', () => {
  assert.deepEqual(buildConnectorsPatch(true), { connectors: ['europepmc', 'pubmed'] });
});

test('unchecked -> empty list', () => {
  assert.deepEqual(buildConnectorsPatch(false), { connectors: [] });
});
