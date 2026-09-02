/**
 * views/settings.js — Settings view (route /settings).
 * W3-F1.
 *
 * Sections:
 *  1. Model provider (provider, model, API keys)
 *  2. Semantic search (HF token)
 *  2c. Downloads folder (downloads_dir — the click-armed watcher)
 *  3. Appearance (theme, accent, density)
 *  4. Retrieval (k_sections, char_budget)
 *  5. About/Help (links, replay intro)
 *
 * Security: every server string through escapeHtml; secrets never rendered as
 * values; empty secret fields never sent (settingsHelpers.buildSettingsPatch).
 */

import * as api from '../api.js';
import * as store from '../store.js';
import { navigateBack } from '../router.js';
import { themeVars, applyTheme } from '../theme.js';
import { buildSettingsPatch, validateSettings, buildConnectorsPatch } from '../settingsHelpers.js';
import { showToast } from '../components/toast.js';
import { escapeHtml } from '../format.js';
import { tip } from '../glossary.js';

let _el = null;
let _settings = null; // last loaded settings snapshot
let _onKeydown = null; // Escape handler, removed on unmount

// ---------------------------------------------------------------------------
// mount / unmount
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _settings = null;
  el.innerHTML = `<div class="settings-view"><p class="muted" style="padding:var(--space-4)">Loading settings…</p></div>`;
  // Escape closes Settings, matching the drawer/modal convention.
  _onKeydown = (e) => { if (e.key === 'Escape') navigateBack(); };
  document.addEventListener('keydown', _onKeydown);
  _load();
}

export function unmount() {
  if (_onKeydown) {
    document.removeEventListener('keydown', _onKeydown);
    _onKeydown = null;
  }
  _el = null;
  _settings = null;
}

// ---------------------------------------------------------------------------
// Load
// ---------------------------------------------------------------------------

async function _load() {
  try {
    const settings = await api.getSettings();
    store.setSettings(settings);
    _settings = settings;
    if (_el) _render(settings);
  } catch (err) {
    if (_el) {
      _el.innerHTML = `<div class="settings-view"><p style="color:var(--color-fail);padding:var(--space-4)">Failed to load settings: ${escapeHtml(String(err.message || err))}</p></div>`;
    }
  }
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _render(s) {
  if (!_el) return;

  const keyInfo = s.keys || {};
  const anthropicInfo = keyInfo.anthropic_api_key || { set: false, masked: null };
  const openaiInfo    = keyInfo.openai_api_key    || { set: false, masked: null };
  const hfInfo        = keyInfo.hf_token          || { set: false, masked: null };

  _el.innerHTML = `
<div class="settings-view">
  <div class="settings-header">
    <h1>Settings</h1>
    <button class="drawer-close settings-close" id="settings-close" aria-label="Close settings" title="Close">&times;</button>
  </div>

  <!-- 1. Model provider -->
  <div class="settings-card" id="sc-model">
    <div class="settings-card-title">Model Provider</div>
    <div class="settings-field">
      <label class="settings-label">Provider</label>
      <select class="settings-select" id="s-provider">
        <option value="anthropic" ${escapeHtml(s.provider) === 'anthropic' ? 'selected' : ''}>Anthropic</option>
        <option value="openai"    ${escapeHtml(s.provider) === 'openai'    ? 'selected' : ''}>OpenAI</option>
      </select>
    </div>
    <div class="settings-field">
      <label class="settings-label">Model name (optional override)</label>
      <input type="text" class="settings-input" id="s-model" value="${escapeHtml(s.model || '')}" placeholder="e.g. claude-3-5-sonnet-20241022">
    </div>
    <div class="settings-field">
      <label class="settings-label">Anthropic API key</label>
      <input type="password" class="settings-input" id="s-anthropic-key" autocomplete="new-password"
        placeholder="${anthropicInfo.set ? 'Saved: ' + escapeHtml(anthropicInfo.masked || '****') + ' — type to replace' : 'sk-ant-…'}">
    </div>
    <div class="settings-field">
      <label class="settings-label">OpenAI API key</label>
      <input type="password" class="settings-input" id="s-openai-key" autocomplete="new-password"
        placeholder="${openaiInfo.set ? 'Saved: ' + escapeHtml(openaiInfo.masked || '****') + ' — type to replace' : 'sk-…'}">
    </div>
    <div class="settings-section-actions">
      <button class="btn btn-accent btn-sm" id="save-model">Save</button>
    </div>
  </div>

  <!-- 2. Semantic search -->
  <div class="settings-card" id="sc-search">
    <div class="settings-card-title">Semantic Search</div>
    <div class="settings-field">
      <label class="settings-label">Hugging Face token</label>
      <input type="password" class="settings-input" id="s-hf-token" autocomplete="new-password"
        placeholder="${hfInfo.set ? 'Saved: ' + escapeHtml(hfInfo.masked || '****') + ' — type to replace' : 'hf_…'}">
      <span class="settings-hint"${tip('hybrid')}>Optional. Enables hybrid semantic search; without it, keyword search (BM25) is used.</span>
    </div>
    <div class="settings-section-actions">
      <button class="btn btn-accent btn-sm" id="save-search">Save</button>
    </div>
  </div>

  <!-- 2b. Open-access lookups -->
  <div class="settings-card" id="sc-oa-lookups">
    <div class="settings-card-title">Open-Access Lookups</div>
    <div class="settings-field">
      <label class="settings-label">Contact email (open-access lookups)</label>
      <input type="text" class="settings-input" id="s-contact-email"
        value="${escapeHtml(s.contact_email || '')}" placeholder="you@example.com">
      <span class="settings-hint">Optional. Sent to Unpaywall when searching for a free PDF of a
        failed paper — it identifies you as a polite API user and can unlock lookups that would
        otherwise be skipped. Never shared beyond that request.</span>
    </div>
    <div class="settings-section-actions">
      <button class="btn btn-accent btn-sm" id="save-oa-lookups">Save</button>
    </div>
  </div>

  <!-- 2c. Downloads folder (the click-to-download watcher, spec 7.6) -->
  <div class="settings-card" id="sc-downloads">
    <div class="settings-card-title">Downloads Folder</div>
    <div class="settings-field">
      <label class="settings-label">Downloads folder</label>
      <input type="text" class="settings-input" id="s-downloads-dir"
        value="${escapeHtml(s.downloads_dir || '')}"
        placeholder="${escapeHtml(s.downloads_dir_detected || 'no folder detected — type one')}">
      <span class="settings-hint">Where your browser saves files. When a paper can only be
        fetched by you, Research Companion watches this folder — <strong>only</strong> for the
        ten minutes after you click <em>Open at publisher</em>, only for new <code>.pdf</code>
        files, and only to read page one for an identifier. Leave it blank to use the detected
        folder${s.downloads_dir_detected ? ' (' + escapeHtml(s.downloads_dir_detected) + ')' : ''}.
        ${s.downloads_dir_detected ? '' : 'Nothing was detected on this machine, so watching stays off until you set one.'}</span>
    </div>
    <div class="settings-section-actions">
      <button class="btn btn-accent btn-sm" id="save-downloads">Save</button>
    </div>
  </div>

  <!-- 3. Appearance -->
  <div class="settings-card" id="sc-appearance">
    <div class="settings-card-title">Appearance</div>
    <div class="settings-field">
      <label class="settings-label">Theme</label>
      <div class="settings-theme-cards">
        <button class="settings-theme-card ${s.theme === 'dark' ? 'selected' : ''}" data-theme-pick="dark">
          <div class="settings-theme-swatches">
            <div class="settings-theme-swatch" style="background:#0d1117"></div>
            <div class="settings-theme-swatch" style="background:#161b22"></div>
            <div class="settings-theme-swatch" style="background:#58a6ff"></div>
          </div>
          Dark
        </button>
        <button class="settings-theme-card ${s.theme === 'light' ? 'selected' : ''}" data-theme-pick="light">
          <div class="settings-theme-swatches">
            <div class="settings-theme-swatch" style="background:#ffffff;border-color:#d0d7de"></div>
            <div class="settings-theme-swatch" style="background:#f6f8fa;border-color:#d0d7de"></div>
            <div class="settings-theme-swatch" style="background:#58a6ff"></div>
          </div>
          Light
        </button>
      </div>
    </div>
    <div class="settings-field">
      <label class="settings-label">Accent color</label>
      <div class="settings-accent-row">
        <button class="settings-accent-swatch ${s.accent === 'blue' ? 'selected' : ''}" data-accent-pick="blue" style="background:#58a6ff" title="Blue" aria-label="Blue accent"></button>
        <button class="settings-accent-swatch ${s.accent === 'teal' ? 'selected' : ''}" data-accent-pick="teal" style="background:#3fb6a8" title="Teal" aria-label="Teal accent"></button>
        <button class="settings-accent-swatch ${s.accent === 'violet' ? 'selected' : ''}" data-accent-pick="violet" style="background:#a78bfa" title="Violet" aria-label="Violet accent"></button>
      </div>
    </div>
    <div class="settings-field">
      <label class="settings-label">Density</label>
      <div class="settings-density-row">
        <button class="settings-density-btn ${s.density === 'comfortable' ? 'selected' : ''}" data-density-pick="comfortable">Comfortable</button>
        <button class="settings-density-btn ${s.density === 'compact' ? 'selected' : ''}" data-density-pick="compact">Compact</button>
      </div>
    </div>
    <div class="settings-section-actions">
      <button class="btn btn-accent btn-sm" id="save-appearance">Save</button>
    </div>
  </div>

  <!-- 4. Retrieval -->
  <div class="settings-card" id="sc-retrieval">
    <div class="settings-card-title">Retrieval</div>
    <div class="settings-retrieval-row">
      <div class="settings-field">
        <label class="settings-label">Sections retrieved (k_sections)</label>
        <input type="number" class="settings-input" id="s-k-sections" value="${escapeHtml(String(s.k_sections || 6))}" min="1" max="20">
        <span class="settings-hint">Default: 6 &nbsp;&middot;&nbsp; Range: 1–20</span>
      </div>
      <button class="settings-reset-link" id="reset-k" title="Reset to default">Reset</button>
      <div class="settings-field">
        <label class="settings-label">Character budget (char_budget)</label>
        <input type="number" class="settings-input" id="s-char-budget" value="${escapeHtml(String(s.char_budget || 8000))}" min="1000" max="50000">
        <span class="settings-hint">Default: 8000 &nbsp;&middot;&nbsp; Range: 1000–50000</span>
      </div>
      <button class="settings-reset-link" id="reset-budget" title="Reset to default">Reset</button>
    </div>
    <div class="settings-section-actions">
      <button class="btn btn-accent btn-sm" id="save-retrieval">Save</button>
    </div>
  </div>

  <!-- 4b. Citations -->
  <div class="settings-card" id="sc-citations">
    <div class="settings-card-title">Citations</div>
    <label class="settings-label" style="display:flex;align-items:center;gap:8px;cursor:pointer">
      <input type="checkbox" id="s-auto-add-citations" ${s.auto_add_citations !== false ? 'checked' : ''}>
      Automatically download papers cited by your draft
    </label>
    <span class="settings-hint">Each downloaded paper costs one model extraction call
      (~$0.02&ndash;$0.10). Anything that cannot be fetched stays listed in the
      Citations panel.</span>
    <label class="settings-label" style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-top:12px">
      <input type="checkbox" id="s-claim-audit" ${s.claim_audit === true ? 'checked' : ''}>
      Check whether cited sources actually support the claim
    </label>
    <span class="settings-hint">Fetches the passage each citation points at and judges
      whether it supports the claim citing it &mdash; the failure a verbatim quote check
      cannot catch. Costs one model call per citation, so it runs only when you press
      <strong>Check citations</strong> in the Report. Advisory: it never blocks or edits
      anything, and &ldquo;could not check&rdquo; is reported separately from
      &ldquo;not supported&rdquo;.</span>
  </div>

  <!-- 4c. Connectors -->
  <div class="settings-card" id="sc-connectors">
    <div class="settings-card-title">Biomedical Connectors</div>
    <label class="settings-label" style="display:flex;align-items:center;gap:8px;cursor:pointer">
      <input type="checkbox" id="s-connectors" ${(s.connectors || []).length ? 'checked' : ''}>
      Verify and search biomedical sources (PubMed / Europe PMC)
    </label>
    <span class="settings-hint">Off by default. When on, citation checks and prior-art
      also query PubMed and Europe PMC, and you can add papers by PMID. Nothing changes
      for non-biomedical work.</span>
  </div>

  <!-- 5. About -->
  <div class="settings-card" id="sc-about">
    <div class="settings-card-title">About / Help</div>
    <div style="display:flex;flex-direction:column;gap:var(--space-2)">
      <a href="https://github.com/LaraibOSS/Research-Companion/blob/main/docs/USER_MANUAL.md" target="_blank" rel="noopener" class="settings-label" style="color:var(--color-accent)">User Manual &#8599;</a>
      <a href="https://github.com/LaraibOSS/Research-Companion" target="_blank" rel="noopener" class="settings-label" style="color:var(--color-accent)">GitHub Repository &#8599;</a>
      <button class="btn btn-secondary btn-sm" id="replay-intro" style="align-self:flex-start;margin-top:var(--space-2)">Replay intro tour</button>
    </div>
  </div>
</div>`;

  _wireEvents(s);
}

// ---------------------------------------------------------------------------
// Event wiring
// ---------------------------------------------------------------------------

function _wireEvents(s) {
  // Close button — return to the previous view (full-page view has no backdrop)
  const closeBtn = _el.querySelector('#settings-close');
  if (closeBtn) closeBtn.addEventListener('click', () => navigateBack());

  // Track local appearance state for instant apply
  const localAppearance = {
    theme: s.theme || 'dark',
    accent: s.accent || 'blue',
    density: s.density || 'comfortable',
  };

  // Theme pick
  _el.querySelectorAll('[data-theme-pick]').forEach(btn => {
    btn.addEventListener('click', () => {
      localAppearance.theme = btn.dataset.themePick;
      _el.querySelectorAll('[data-theme-pick]').forEach(b => b.classList.toggle('selected', b === btn));
      applyTheme(localAppearance);
    });
  });

  // Accent pick
  _el.querySelectorAll('[data-accent-pick]').forEach(btn => {
    btn.addEventListener('click', () => {
      localAppearance.accent = btn.dataset.accentPick;
      _el.querySelectorAll('[data-accent-pick]').forEach(b => b.classList.toggle('selected', b === btn));
      applyTheme(localAppearance);
    });
  });

  // Density pick
  _el.querySelectorAll('[data-density-pick]').forEach(btn => {
    btn.addEventListener('click', () => {
      localAppearance.density = btn.dataset.densityPick;
      _el.querySelectorAll('[data-density-pick]').forEach(b => b.classList.toggle('selected', b === btn));
      applyTheme(localAppearance);
    });
  });

  // Save model section
  const saveModel = _el.querySelector('#save-model');
  if (saveModel) {
    saveModel.addEventListener('click', async () => {
      const provider = _el.querySelector('#s-provider').value;
      const model = _el.querySelector('#s-model').value.trim() || null;
      const anthropicKey = _el.querySelector('#s-anthropic-key').value;
      const openaiKey = _el.querySelector('#s-openai-key').value;
      const formState = {
        provider, model,
        theme: s.theme, accent: s.accent, density: s.density,
        k_sections: s.k_sections, char_budget: s.char_budget,
        anthropic_api_key: anthropicKey,
        openai_api_key: openaiKey,
        hf_token: '',
      };
      await _savePatch(formState, s, saveModel);
    });
  }

  // Save search section
  const saveSearch = _el.querySelector('#save-search');
  if (saveSearch) {
    saveSearch.addEventListener('click', async () => {
      const hfToken = _el.querySelector('#s-hf-token').value;
      const formState = {
        provider: s.provider, model: s.model,
        theme: s.theme, accent: s.accent, density: s.density,
        k_sections: s.k_sections, char_budget: s.char_budget,
        anthropic_api_key: '',
        openai_api_key: '',
        hf_token: hfToken,
      };
      await _savePatch(formState, s, saveSearch);
    });
  }

  // Save open-access lookups section
  const saveOaLookups = _el.querySelector('#save-oa-lookups');
  if (saveOaLookups) {
    saveOaLookups.addEventListener('click', async () => {
      const contactEmail = _el.querySelector('#s-contact-email').value.trim();
      const formState = {
        provider: s.provider, model: s.model,
        theme: s.theme, accent: s.accent, density: s.density,
        k_sections: s.k_sections, char_budget: s.char_budget,
        contact_email: contactEmail,
        anthropic_api_key: '', openai_api_key: '', hf_token: '',
      };
      await _savePatch(formState, s, saveOaLookups);
    });
  }

  // Save downloads folder
  const saveDownloads = _el.querySelector('#save-downloads');
  if (saveDownloads) {
    saveDownloads.addEventListener('click', async () => {
      const downloadsDir = _el.querySelector('#s-downloads-dir').value.trim();
      const formState = {
        provider: s.provider, model: s.model,
        theme: s.theme, accent: s.accent, density: s.density,
        k_sections: s.k_sections, char_budget: s.char_budget,
        downloads_dir: downloadsDir,
        anthropic_api_key: '', openai_api_key: '', hf_token: '',
      };
      await _savePatch(formState, s, saveDownloads);
    });
  }

  // Save appearance section
  const saveAppearance = _el.querySelector('#save-appearance');
  if (saveAppearance) {
    saveAppearance.addEventListener('click', async () => {
      const formState = {
        provider: s.provider, model: s.model,
        theme: localAppearance.theme,
        accent: localAppearance.accent,
        density: localAppearance.density,
        k_sections: s.k_sections, char_budget: s.char_budget,
        anthropic_api_key: '', openai_api_key: '', hf_token: '',
      };
      await _savePatch(formState, s, saveAppearance);
    });
  }

  // Save retrieval section
  const saveRetrieval = _el.querySelector('#save-retrieval');
  if (saveRetrieval) {
    saveRetrieval.addEventListener('click', async () => {
      const kSections = parseInt(_el.querySelector('#s-k-sections').value, 10);
      const charBudget = parseInt(_el.querySelector('#s-char-budget').value, 10);
      const formState = {
        provider: s.provider, model: s.model,
        theme: s.theme, accent: s.accent, density: s.density,
        k_sections: kSections, char_budget: charBudget,
        anthropic_api_key: '', openai_api_key: '', hf_token: '',
      };
      const errors = validateSettings({ k_sections: kSections, char_budget: charBudget });
      if (errors.length) { showToast(errors[0], 'error'); return; }
      await _savePatch(formState, s, saveRetrieval);
    });
  }

  // Claim-audit toggle — saves immediately on change
  const claimAudit = _el.querySelector('#s-claim-audit');
  if (claimAudit) {
    claimAudit.addEventListener('change', async () => {
      try {
        const updated = await api.putSettings({ claim_audit: claimAudit.checked });
        store.setSettings(updated);
        showToast(claimAudit.checked
          ? 'Citation claim checks on — run them from the Report'
          : 'Citation claim checks off', 'info');
      } catch (err) {
        claimAudit.checked = !claimAudit.checked;
        showToast(`Save failed: ${err.message}`, 'error');
      }
    });
  }

  // Citations auto-download toggle — saves immediately on change
  const autoAdd = _el.querySelector('#s-auto-add-citations');
  if (autoAdd) {
    autoAdd.addEventListener('change', async () => {
      try {
        const updated = await api.putSettings({ auto_add_citations: autoAdd.checked });
        store.setSettings(updated);
        showToast(autoAdd.checked
          ? 'Cited papers will download automatically'
          : 'Automatic citation downloads off', 'info');
      } catch (err) {
        autoAdd.checked = !autoAdd.checked;
        showToast(`Save failed: ${err.message}`, 'error');
      }
    });
  }

  // Biomedical connectors toggle — saves immediately on change
  const connectorsToggle = _el.querySelector('#s-connectors');
  if (connectorsToggle) {
    connectorsToggle.addEventListener('change', async () => {
      try {
        const updated = await api.putSettings(buildConnectorsPatch(connectorsToggle.checked));
        store.setSettings(updated);
        showToast(connectorsToggle.checked
          ? 'Biomedical connectors enabled'
          : 'Biomedical connectors off', 'info');
      } catch (err) {
        connectorsToggle.checked = !connectorsToggle.checked;
        showToast(`Save failed: ${err.message}`, 'error');
      }
    });
  }

  // Reset links
  const resetK = _el.querySelector('#reset-k');
  if (resetK) {
    resetK.addEventListener('click', () => {
      const inp = _el.querySelector('#s-k-sections');
      if (inp) inp.value = '6';
    });
  }
  const resetBudget = _el.querySelector('#reset-budget');
  if (resetBudget) {
    resetBudget.addEventListener('click', () => {
      const inp = _el.querySelector('#s-char-budget');
      if (inp) inp.value = '8000';
    });
  }

  // Replay intro
  const replayBtn = _el.querySelector('#replay-intro');
  if (replayBtn) {
    replayBtn.addEventListener('click', () => {
      // Clear tour localStorage keys; F2 wires the actual tour
      for (const key of Object.keys(localStorage).filter(k => k.startsWith('rc.tour'))) {
        localStorage.removeItem(key);
      }
      window.location.hash = '#/home';
    });
  }
}

// ---------------------------------------------------------------------------
// Save helper
// ---------------------------------------------------------------------------

async function _savePatch(formState, original, btn) {
  const patch = buildSettingsPatch(formState, original);
  if (Object.keys(patch).length === 0) {
    showToast('No changes to save.', 'info');
    return;
  }
  btn.disabled = true;
  try {
    const updated = await api.putSettings(patch);
    store.setSettings(updated);
    _settings = updated;
    showToast('Settings saved.', 'info');
    // Refresh masked placeholders by re-rendering
    if (_el) _render(updated);
  } catch (err) {
    showToast(`Save failed: ${escapeHtml(String(err.message || err))}`, 'error');
  } finally {
    btn.disabled = false;
  }
}
