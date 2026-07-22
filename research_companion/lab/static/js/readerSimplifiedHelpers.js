/**
 * Pure model for the Reader's "Simplified" tab: turns a stored extraction
 * (concepts/claims/methods/datasets/results) into ordered plain-English
 * bullet groups, and decides which view the pane shows. DOM-free (node-tested).
 * Display-only aid — never feeds Ask/Draft/citations.
 */

function _bullet(text, section) {
  return { text, sectionId: section || null };
}

export function simplifiedModel(extraction) {
  if (!extraction || typeof extraction !== 'object') return { groups: [] };
  const groups = [];
  const push = (title, bullets) => {
    const kept = bullets.filter(b => b && b.text);
    if (kept.length) groups.push({ title, bullets: kept });
  };
  const arr = (k) => (Array.isArray(extraction[k]) ? extraction[k] : []);

  push('What this paper is about', arr('concepts').map(c =>
    _bullet([c.name, c.definition].filter(Boolean).join(' — '), c.section)));
  push('Key claims', arr('claims').map(c => _bullet(c.text || '', c.section)));
  push('How they did it', [
    ...arr('methods').map(m =>
      _bullet([m.name, m.description].filter(Boolean).join(' — '), m.section)),
    ...arr('datasets').map(d =>
      _bullet('Dataset: ' + [d.name, d.description].filter(Boolean).join(' — '), d.section)),
  ]);
  push('What they found', arr('results').map(r => {
    if (!r.metric && !r.value) return _bullet('', r.section);
    let text = `${r.metric || '?'}: ${r.value || '?'}`;
    if (r.dataset) text += ` (${r.dataset})`;
    return _bullet(text, r.section);
  }));
  return { groups };
}

export function simplifiedDisplayState({ hasExtraction, rewrite, providerConfigured }) {
  const view = rewrite ? 'rewrite' : (hasExtraction ? 'auto' : 'empty');
  return { view, showButton: !!providerConfigured && !!hasExtraction };
}
