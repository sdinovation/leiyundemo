'use strict';
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf-8');
const start = html.indexOf('function analyzeQuestion');
let depth = 0; let i = start; let inStr = null; let esc = false; let inLineComment = false; let inBlockComment = false;
while (i < html.length) {
  const c = html[i];
  const n = html[i+1];
  if (inLineComment) { if (c === '\n') inLineComment = false; i++; continue; }
  if (inBlockComment) { if (c === '*' && n === '/') { inBlockComment = false; i += 2; continue; } i++; continue; }
  if (inStr) {
    if (esc) { esc = false; i++; continue; }
    if (c === '\\') { esc = true; i++; continue; }
    if (c === inStr) inStr = null;
    i++; continue;
  }
  if (c === '/' && n === '/') { inLineComment = true; i += 2; continue; }
  if (c === '/' && n === '*') { inBlockComment = true; i += 2; continue; }
  if (c === '"' || c === "'" || c === '`') { inStr = c; i++; continue; }
  if (c === '{') depth++;
  else if (c === '}') { depth--; if (depth === 0) { i++; break; } }
  i++;
}
const body = html.substring(start, i);
console.log('--- last 1800 chars of analyzeQuestion ---');
console.log(body.slice(-1800));