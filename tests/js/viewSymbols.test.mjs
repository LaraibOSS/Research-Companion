/**
 * viewSymbols.test.mjs — guards against a class of bug that shipped twice:
 * a patch adds code using a module-scoped `_name` but its `let _name = …`
 * declaration silently fails to apply. The view then throws
 * "ReferenceError: _name is not defined" the moment it mounts, while
 * string-grep static tests still pass because the symbol *is* present in the
 * file.
 *
 * Every `_identifier` referenced in a static JS module must be bound in that
 * same module.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const JS_DIR = path.join(repoRoot, 'research_companion', 'lab', 'static', 'js');

function jsFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return jsFiles(p);
    return e.name.endsWith('.js') ? [p] : [];
  });
}

/**
 * Is the `/` about to be read a regex literal rather than a division sign?
 *
 * The usual heuristic: division can only follow a value, so if the last thing
 * emitted was an identifier, a number, or a closing bracket, `/` divides.
 * `out` is the already-stripped output, which is enough context here.
 */
function isRegexStart(out) {
  const prev = out.replace(/\s+$/, '').slice(-1);
  if (!prev) return true;
  if (/[A-Za-z0-9_$)\]]/.test(prev)) return false;
  return true;
}

// Remove comments, regex literals and string/template literals so their
// contents are never mistaken for code.
function stripLiterals(src) {
  let out = '';
  let i = 0;
  const n = src.length;
  while (i < n) {
    const c = src[i];
    const next = src[i + 1];
    if (c === '/' && next === '*') {
      const end = src.indexOf('*/', i + 2);
      i = end === -1 ? n : end + 2;
      out += ' ';
    } else if (c === '/' && next === '/') {
      const end = src.indexOf('\n', i);
      i = end === -1 ? n : end;
      out += ' ';
    } else if (c === '/' && isRegexStart(out)) {
      // A regex literal, not division. Its body must be skipped like a string:
      // a backtick inside one (e.g. /`([^`]+)`/) would otherwise be read as the
      // start of a template literal and swallow the rest of the file, silently
      // hiding every declaration after it.
      i += 1;
      let inClass = false;
      while (i < n) {
        const ch = src[i];
        if (ch === '\\') { i += 2; continue; }
        if (ch === '[') inClass = true;
        else if (ch === ']') inClass = false;
        else if (ch === '/' && !inClass) { i += 1; break; }
        else if (ch === '\n') break;   // unterminated: not a regex after all
        i += 1;
      }
      out += ' ';
    } else if (c === '"' || c === "'" || c === '`') {
      const quote = c;
      i += 1;
      while (i < n) {
        if (src[i] === '\\') { i += 2; continue; }
        if (src[i] === quote) { i += 1; break; }
        // keep ${...} contents in templates: they are real code
        if (quote === '`' && src[i] === '$' && src[i + 1] === '{') {
          let depth = 1;
          i += 2;
          const start = i;
          while (i < n && depth > 0) {
            if (src[i] === '{') depth += 1;
            else if (src[i] === '}') depth -= 1;
            i += 1;
          }
          out += ' ' + src.slice(start, Math.max(start, i - 1)) + ' ';
          continue;
        }
        i += 1;
      }
      out += ' ';
    } else {
      out += c;
      i += 1;
    }
  }
  return out;
}

function declaredNames(src) {
  const declared = new Set();
  const add = (blob) => {
    for (const part of String(blob).split(/[^A-Za-z0-9_$]+/)) {
      if (part.startsWith('_')) declared.add(part);
    }
  };
  const patterns = [
    /\b(?:let|const|var)\s+([^=;\n]+)/g,   // incl. destructuring targets
    /\bfunction\s*\*?\s*([A-Za-z0-9_$]+)/g,
    /\bclass\s+([A-Za-z0-9_$]+)/g,
    /\bimport\s*\{([^}]*)\}/g,
    /\bimport\s+([A-Za-z0-9_$]+)\s+from/g,
    /\bcatch\s*\(([^)]*)\)/g,
    /\(([^()]*)\)\s*=>/g,                  // arrow params
    /\bfunction\s*[A-Za-z0-9_$]*\s*\(([^()]*)\)/g,
    /([A-Za-z0-9_$]+)\s*\(([^()]*)\)\s*\{/g, // method/function params
  ];
  for (const re of patterns) {
    let m;
    while ((m = re.exec(src)) !== null) {
      add(m[1]);
      if (m[2]) add(m[2]);
    }
  }
  return declared;
}

test('every module-scoped _identifier used in a JS module is declared there', () => {
  const problems = [];
  for (const file of jsFiles(JS_DIR)) {
    if (file.includes(`${path.sep}vendor${path.sep}`)) continue;
    const src = stripLiterals(fs.readFileSync(file, 'utf8'));
    const declared = declaredNames(src);

    // Not identifiers: HTML link targets that survive attribute parsing.
    const IGNORE = new Set(['_blank', '_self', '_parent', '_top']);

    const used = new Set();
    let m;
    // a bare _name not preceded by '.' (property) or word char
    const useRe = /(?<![.\w$])_[A-Za-z0-9_$]+/g;
    while ((m = useRe.exec(src)) !== null) used.add(m[0]);

    for (const name of used) {
      if (IGNORE.has(name)) continue;
      if (!declared.has(name)) {
        problems.push(`${path.relative(repoRoot, file).replace(/\\/g, '/')}: ${name}`);
      }
    }
  }
  assert.deepEqual(
    problems, [],
    `undeclared module-scoped identifiers (a view using these throws on mount):\n`
    + problems.join('\n'),
  );
});
