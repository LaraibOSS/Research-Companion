/**
 * draftHelpers.js — pure model helpers for the Draft alignment view.
 *
 * Dependency-free and node-testable (no DOM, no store). Returns RAW strings —
 * the caller (views/draft.js) escapeHtml's them at the interpolation site, per
 * that view's convention.
 */

/**
 * Decide what the Draft view's section list should show.
 *
 * The Draft view normally renders per-paper alignment (`alignmentSections`).
 * When a draft has no alignment yet — e.g. one just created by "Draft this
 * direction", or any draft set after its library was ingested — that list is
 * empty and the view would show "No sections found." even though the draft has
 * a real outline. In that case we fall back to the draft's OWN outline
 * (`outlineSections`, from GET /api/sections) so the user sees their sections
 * immediately, each with an empty `alignments` list.
 *
 * @param {Array} alignmentSections — [{section_id, title, alignments:[...]}]
 * @param {Array} outlineSections — [{section_id, title, level, ...}] (raw /api/sections)
 * @returns {{ sections: Array, fromOutline: boolean }} — `fromOutline` is true
 *   only when the fallback outline is used (so the view can show the
 *   "not analyzed yet" affordance). Never throws.
 */
export function draftSectionModel(alignmentSections, outlineSections) {
  const aligned = Array.isArray(alignmentSections) ? alignmentSections : [];
  if (aligned.length > 0) {
    return { sections: aligned, fromOutline: false };
  }

  const outline = Array.isArray(outlineSections) ? outlineSections : [];
  if (outline.length === 0) {
    return { sections: [], fromOutline: false };
  }

  const sections = outline.map(s => ({
    section_id: (s && s.section_id) || '',
    title: (s && s.title) || (s && s.section_id) || '',
    level: (s && s.level) || 1,
    alignments: [],
  }));
  return { sections, fromOutline: true };
}
