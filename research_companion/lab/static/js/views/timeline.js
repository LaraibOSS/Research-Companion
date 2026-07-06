/**
 * views/timeline.js — Timeline placeholder view.
 * F5 replaces this with the real timeline view.
 * W3-F1.
 */

export function mount(el) {
  el.innerHTML = `
    <div class="stub-view" style="padding:var(--space-5)">
      <div class="stub-icon"><svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="9" r="7"/><polyline points="9,5 9,9 12,11"/></svg></div>
      <div class="stub-label">Timeline</div>
      <div class="stub-sub muted">Coming soon — F5 will wire the full timeline view.</div>
    </div>`;
}

export function unmount() {}
