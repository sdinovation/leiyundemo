'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.join(__dirname, '..', '..');
const HTML_PATH = path.join(ROOT, 'index.html');

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

  // 构造用户的真实场景：52 行班级数据，学号 202416174 01~52
  const rows = [];
  for (let i = 1; i <= 52; i++) {
    rows.push({ '姓名': '同学' + i, '学号': '202416174 ' + String(i).padStart(2, '0'), '序号': i, '班级': '软件2422', '性别': i % 2 === 0 ? '女' : '男' });
  }
  const headers = ['姓名', '学号', '序号', '班级', '性别'];
  const fieldInfo = headers.map(h => ({ name: h, type: h === '序号' ? 'int' : 'text' }));
  win.parsedData = { fileName: 'class_52.csv', rows, columns: headers, fieldInfo, typeDistribution: [] };

  console.log('=== 用户真实场景：班级 52 人，学号 01-52 ===\n');

  const questions = ['学号前两名的同学', '学号前两个同学', '学号前 2 个同学', '学号在前两名的同学'];
  for (const q of questions) {
    const dim = win.parsedData.columns;
    const rf = win.parseRankFilter(q, dim);
    console.log('Q: ' + q);
    console.log('  parseRankFilter →', rf ? JSON.stringify(rf) : 'null');
    if (rf && rf.desc === 'asc') {
      // ASC → 取最小的 2 个
      const sorted = rows.slice().sort((a, b) => Number(a['序号']) - Number(b['序号']));
      const top2 = sorted.slice(0, rf.n);
      console.log('  → 应返回: ' + top2.map(r => r['姓名'] + '(学号' + r['序号'] + ')').join(', '));
    } else if (rf && rf.desc === 'desc') {
      const sorted = rows.slice().sort((a, b) => Number(b['序号']) - Number(a['序号']));
      const top2 = sorted.slice(0, rf.n);
      console.log('  → 会返回: ' + top2.map(r => r['姓名'] + '(学号' + r['序号'] + ')').join(', ') + ' ← 这就是"最后两个"!');
    }
    console.log('');
  }
}
main().catch(e => { console.error('Error:', e.message); process.exit(1); });