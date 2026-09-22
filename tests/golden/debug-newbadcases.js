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

async function runQuestion(dataset, question) {
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

  const csv = fs.readFileSync(path.join(TEST_DIR, dataset + '.csv'), 'utf-8');
  const sample = csv.length > 500000 ? csv.slice(0, 500000) : csv;
  win.Papa.parse(sample, {
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
      win.parsedData = { fileName: dataset + '.csv', fileSize: csv.length, rows, columns: headers, fieldInfo, typeDistribution: [] };
    }
  });
  await new Promise(r => setTimeout(r, 100));

  const a = await win.analyzeQuestion(question);
  console.log('=== Q: ' + question + ' (dataset=' + dataset + ') ===');
  console.log('sql: ' + (a.sql || '').slice(0, 300));
  console.log('intent: ' + (a.intent && a.intent.intent));
  console.log('dim: ' + (a.intent && a.intent.dimension));
  console.log('metric: ' + (a.intent && a.intent.metric));
  console.log('chartType: ' + a.chartType);
  console.log('rows.length: ' + (a.rawResult ? a.rawResult.length : 'null'));
  if (a.rawResult && a.rawResult.length > 0) {
    console.log('rows:');
    a.rawResult.slice(0, 5).forEach((r, i) => console.log('  [' + i + '] ' + JSON.stringify(r)));
  }
  console.log('interpretation: ' + (a.interpretation || '').slice(0, 300));
  console.log('');
}

async function main() {
  await runQuestion('ecommerce_10k', '日均交易笔数是多少');
  await runQuestion('ecommerce_10k', '共有多少种不同的产品');
  await runQuestion('ecommerce_10k', '共有多少种不同的品类');
}
main().catch(e => { console.error('Error:', e.message); process.exit(1); });