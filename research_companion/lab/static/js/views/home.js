/**
 * views/home.js — Home Dashboard placeholder view.
 * F2 replaces this with the real home view.
 * W3-F1.
 */

export function mount(el) {
  el.innerHTML = `
    <div class="stub-view" style="padding:var(--space-5)">
      <div class="stub-icon"><svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M2 7.5L9 2l7 5.5V16a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V7.5z"/><path d="M6.5 17V11h5v6"/></svg></div>
      <div class="stub-label">Home Dashboard</div>
      <div class="stub-sub muted">Coming in the next build — head to <strong>Library</strong> to get started.</div>
    </div>`;
}

export function unmount() {}
