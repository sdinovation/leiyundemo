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

  const csv = fs.readFileSync(path.join(TEST_DIR, 'leap_year.csv'), 'utf-8');
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
      win.parsedData = { fileName: 'leap_year.csv', fileSize: csv.length, rows, columns: headers, fieldInfo, typeDistribution: [] };
    }
  });
  await new Promise(r => setTimeout(r, 100));

  // Direct test of parseTimeRange
  const dimFields = win.parsedData.fieldInfo.filter(f => f.type === 'text').map(f => f.name);
  const dateField = '日期';

  console.log('=== parseTimeRange 直接测试 ===');
  for (const q of ["2024-02-29这条记录", "2024-02-28这条记录", "2024-02-29", "2024年2月29日"]) {
    const tr = win.parseTimeRange(q, dateField, win.parsedData.rows);
    console.log(`  Q="${q}" → ${JSON.stringify(tr)}`);
  }

  console.log('\n=== parseDate 测试 ===');
  for (const v of ['2024-02-29', '2024-02-28', '2024-02-01']) {
    const d = win.parseDate(v);
    console.log(`  parseDate("${v}") = ${d ? d.toISOString() : 'null'}`);
  }

  console.log('\n=== executeQuery 直接测试 ===');
  for (const q of ["2024-02-29这条记录", "2024-02-28这条记录"]) {
    const tr = win.parseTimeRange(q, dateField, win.parsedData.rows);
    const r = win.executeQuery(win.parsedData.rows, tr, null, null, null, null, null);
    console.log(`  Q="${q}" → ${r.length} rows`);
    if (r.length > 0 && r.length <= 5) console.log('    ', r);
  }
}
main().catch(e => { console.error('Error:', e.message); process.exit(1); });