'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.join(__dirname, '..', '..');
const HTML_PATH = path.join(ROOT, 'index.html');
const TEST_DIR = path.join(ROOT, 'test-datasets');

function parseCSVLine(line) {
  const result = []; let cur = ''; let inQuote = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') { inQuote = !inQuote; continue; }
    if (ch === ',' && !inQuote) { result.push(cur); cur = ''; continue; }
    cur += ch;
  }
  result.push(cur);
  return result;
}

async function main() {
  const html = fs.readFileSync(HTML_PATH, 'utf-8');
  const patched = html.replace(/let parsedData = \{/, 'var parsedData = {');
  const cleanedHtml = patched
    .replace(/<script src="tailwindcss\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="echarts\.min\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="papaparse\.min\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="lucide\.min\.js"[^>]*><\/script>/g, '');
  const dom = new JSDOM(cleanedHtml, {
    url: 'file:///' + HTML_PATH.replace(/\\/g, '/'),
    runScripts: 'dangerously', pretendToBeVisual: true, resources: 'usable'
  });
  const win = dom.window;
  win.lucide = { createIcons: () => {}, createElement: () => null };
  win.Papa = {
    parse: (text, opts) => {
      const lines = text.trim().split(/\r?\n/);
      const headers = parseCSVLine(lines[0]);
      const data = [headers];
      for (let i = 1; i < lines.length; i++) {
        if (!lines[i].trim()) continue;
        data.push(parseCSVLine(lines[i]));
      }
      if (opts && opts.header === false) { if (opts.complete) opts.complete({ data, errors: [] }); return { data, errors: [] }; }
      const rows = data.slice(1).map(line => { const row = {}; headers.forEach((h, j) => row[h] = line[j] || ''); return row; });
      if (opts && opts.complete) opts.complete({ data: rows, errors: [] });
      return { data: rows, errors: [] };
    }
  };
  win.echarts = function () { return { setOption: () => {}, resize: () => {}, dispose: () => {} }; };
  await new Promise(r => setTimeout(r, 1500));

  const csv = fs.readFileSync(path.join(TEST_DIR, 'students.csv'), 'utf-8');
  win.Papa.parse(csv, {
    header: false, skipEmptyLines: true,
    complete: (results) => {
      const headers = results.data[0];
      const rows = results.data.slice(1).map(line => {
        const row = {}; headers.forEach((h, j) => row[h] = line[j]);
        Object.keys(row).forEach(k => {
          const v = row[k];
          if (v === '' || v == null) return;
          if (/^-?\d+(\.\d+)?$/.test(v)) { const n = Number(v); if (!isNaN(n)) row[k] = n; }
        });
        return row;
      });
      const fieldInfo = headers.map(h => {
        const sample = rows.find(r => r[h] !== '' && r[h] != null);
        const v = sample ? sample[h] : null;
        let type = 'text';
        if (typeof v === 'number') type = Number.isInteger(v) ? 'int' : 'float';
        else if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v)) type = 'date';
        return { name: h, type };
      });
      win.parsedData = { fileName: 'students.csv', fileSize: csv.length, rows, columns: headers, fieldInfo, typeDistribution: [] };
    }
  });
  await new Promise(r => setTimeout(r, 100));

  console.log('=== 排名方向实测 ===\n');
  const questions = [
    { q: '学号前 2 个同学', 期望: 'ASC (学号最小)' },
    { q: '学号在前五名的同学', 期望: 'ASC (T03 期望)' },
    { q: '成绩前 5 名', 期望: 'DESC (成绩最大)' },
    { q: '薪资前 3 个', 期望: 'DESC (薪资最大)' },
  ];
  for (const { q, 期望 } of questions) {
    try {
      // 直接调用 parseRankFilter
      const dimensionFields = win.parsedData.columns || [];
      const rf = win.parseRankFilter(q, dimensionFields);
      console.log('Q: ' + q);
      console.log('  期望: ' + 期望);
      console.log('  parseRankFilter →', rf ? JSON.stringify(rf) : 'null');
      console.log('');
    } catch (e) {
      console.log('Q: ' + q + ' ERROR: ' + e.message + '\n');
    }
  }
}
main().catch(e => { console.error('Error:', e.message); process.exit(1); });