/**
 * components/researchPath.js — renders the Home research path: a five-stage
 * strip and one "Next step" card. Markup only; what is done and what comes
 * next is decided in pathHelpers.js, and home.js wires the button.
 *
 * Accessibility: the stages are an ordered list, the current one carries
 * aria-current="step", and every status is written out in words (with a
 * glyph) so nothing is carried by colour alone. The button is a real <button>
 * whose label names where it goes.
 */

import { escapeHtml } from '../format.js';

const GLYPH = { done: '✓', current: '●', not_started: '○' };

function _stageHtml(stage, index) {
  const cur = stage.status === 'current' ? ' aria-current="step"' : '';
  return `
      <li class="home-path-stage is-${escapeHtml(stage.status)}"${cur}>
        <span class="home-path-glyph" aria-hidden="true">${escapeHtml(GLYPH[stage.status] || '')}</span>
        <span class="home-path-text">
          <span class="home-path-name">${escapeHtml(`${index + 1}. ${stage.title}`)}</span>
          <span class="home-path-status">${escapeHtml(stage.statusText)}</span>
          <span class="home-path-reason">${escapeHtml(stage.reason)}</span>
        </span>
      </li>`;
}

/**
 * @param {{stages: Array, next: object}} path — researchPath() output
 * @returns {string} HTML
 */
export function researchPathHtml(path) {
  if (!path || !Array.isArray(path.stages) || !path.next) return '';
  const next = path.next;
  const target = next.route
    ? `data-path-route="${escapeHtml(next.route)}"`
    : `data-path-action="${escapeHtml(next.action || '')}"`;
  const withModel = next.withModel
    ? `<p class="home-next-model">${escapeHtml(next.withModel)}</p>` : '';
  return `
    <section class="home-path" aria-labelledby="home-path-heading">
      <h2 class="home-path-heading" id="home-path-heading">Your research path</h2>
      <ol class="home-path-stages">${path.stages.map(_stageHtml).join('')}
      </ol>
      <div class="home-next" role="group" aria-labelledby="home-next-heading">
        <h3 class="home-next-heading" id="home-next-heading">Next step: ${escapeHtml(next.title)}</h3>
        <p class="home-next-what">${escapeHtml(next.what)}</p>
        <p class="home-next-cost">
          <span class="home-next-cost-badge is-${escapeHtml(next.cost)}">${escapeHtml(next.costLabel)}</span>
          <span>${escapeHtml(next.costText)}</span>
        </p>
        ${withModel}
        <button type="button" class="btn btn-accent home-next-go" ${target}>${escapeHtml(next.button)}</button>
      </div>
    </section>`;
}
