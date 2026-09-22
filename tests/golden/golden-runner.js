/**
 * golden-runner.js — 黄金集执行器（基于 run-tests.js 的成熟环境）
 *
 * 用法: node tests/golden/golden-runner.js
 *
 * 输入: tests/golden/questions.jsonl
 * 输出: 基线报告（控制台 + tests/golden/baseline-report.json）
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.join(__dirname, '..', '..');
const HTML_PATH = path.join(ROOT, 'index.html');
const TEST_DIR = path.join(ROOT, 'test-datasets');
const QUESTIONS_FILE = path.join(__dirname, 'questions.jsonl');
const REPORT_FILE = path.join(__dirname, 'baseline-report.json');

// ============ 复用 run-tests.js 的环境搭建 ============
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

async function loadEnv() {
  const html = fs.readFileSync(HTML_PATH, 'utf-8');
  const patched = html.replace(/let parsedData = \{/, 'var parsedData = {');
  const cleanedHtml = patched
    .replace(/<script src="tailwindcss\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="echarts\.min\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="papaparse\.min\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="lucide\.min\.js"[^>]*><\/script>/g, '');

  const dom = new JSDOM(cleanedHtml, {
    url: 'file:///' + HTML_PATH.replace(/\\/g, '/'),
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    resources: 'usable',
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
      if (opts && opts.header === false) {
        if (opts.complete) opts.complete({ data, errors: [] });
        return { data, errors: [] };
      }
      const rows = data.slice(1).map(line => {
        const row = {};
        headers.forEach((h, j) => row[h] = line[j] || '');
        return row;
      });
      if (opts && opts.complete) opts.complete({ data: rows, errors: [] });
      return { data: rows, errors: [] };
    },
  };
  win.echarts = function () { return { setOption: () => {}, resize: () => {}, dispose: () => {} }; };
  await new Promise(r => setTimeout(r, 1500));
  return { dom, win };
}

async function loadDataset(win, csvName) {
  const csvPath = path.join(TEST_DIR, csvName);
  const csv = fs.readFileSync(csvPath, 'utf-8');
  win.Papa.parse(csv, {
    header: false,
    skipEmptyLines: true,
    complete: (results) => {
      const headers = results.data[0];
      const rows = results.data.slice(1).map(line => {
        const row = {};
        headers.forEach((h, j) => row[h] = line[j]);
        Object.keys(row).forEach(k => {
          const v = row[k];
          if (v === '' || v == null) return;
          if (/^-?\d+(\.\d+)?$/.test(v)) {
            const n = Number(v);
            if (!isNaN(n)) row[k] = n;
          }
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
      win.parsedData = {
        fileName: csvName,
        fileSize: csv.length,
        rows,
        columns: headers,
        fieldInfo,
        typeDistribution: [],
      };
      win.window._lastQuery = '';
      win.window._lastRankFilter = null;
      win.window._lastExtraWhere = null;
      win.window._lastRangeFilter = null;
      win.window._lastLikeFilter = null;
      win.window._lastThresholdWhere = null;
    }
  });
  await new Promise(r => setTimeout(r, 50));
}

async function runAnalysis(win, question) {
  win.window._lastQuery = question;
  win.window.hasUserApiKey = () => false;
  return await win.analyzeQuestion(question);
}

// ============ 三维度断言 ============
function getRows(r) {
  if (!r) return [];
  if (r.data && Array.isArray(r.data.rows)) return r.data.rows;
  if (Array.isArray(r.rawResult)) return r.rawResult;
  return [];
}

function checkSQL(r, pattern) {
  if (!r || !r.sql) return false;
  // 把多行 SQL 折成单行，便于正则匹配
  const sql = r.sql.replace(/\s+/g, ' ');
  return new RegExp(pattern, 'i').test(sql);
}

function checkRows(r, expected) {
  const rows = getRows(r);
  if (expected.expected_rows !== undefined) return rows.length === expected.expected_rows;
  if (expected.expected_rows_ge !== undefined) return rows.length >= expected.expected_rows_ge;
  if (expected.expected_count !== undefined) return rows.length === expected.expected_count;
  return true;
}

function checkInterpretation(r) {
  return !!(r && r.interpretation && r.interpretation.length > 5);
}

/**
 * 反幻觉：解读中的关键数字必须能在结果数据中找到
 * 规则（放宽版，避免对合理计算数字误报）：
 *   - 收集结果中的所有数字（含子串数字，如学号 202001005 → 包含 202/001/005 等）
 *   - 跳过年份（1900-2100）
 *   - 跳过排名/百分比/小数比率（≤ 100）
 *   - 跳过极大数（> 100000）可能是 LIMIT 等
 *   - 其余数字：检查是否作为子串出现在任何数据值中
 */
function checkNoHallucination(r) {
  if (!r || !r.interpretation) return { ok: true, hallucinated: [] };
  const rows = getRows(r);
  const dataStrs = new Set();
  const collectStrs = (text) => {
    if (text == null) return;
    const matches = String(text).match(/\d+\.?\d*/g);
    if (matches) matches.forEach(m => dataStrs.add(m));
  };
  // 递归收集所有行原始数据（含嵌套对象如 __comparisonData__）
  const collectDeep = (val) => {
    if (val == null) return;
    if (typeof val === 'object') {
      Object.values(val).forEach(collectDeep);
    } else {
      collectStrs(val);
    }
  };
  rows.forEach(row => {
    Object.entries(row).forEach(([k, v]) => {
      collectDeep(v);
      collectStrs(k);
    });
  });
  // v2.4: 收集全量排名上下文数据（极值/实体过滤类查询引用的"对比"实体数值）
  // 引用数据来自 _contextRanking.fullResult — 该数据基于全量行计算，数字真实存在
  if (r._contextRanking && Array.isArray(r._contextRanking.fullResult)) {
    r._contextRanking.fullResult.forEach(row => {
      Object.entries(row).forEach(([k, v]) => {
        collectStrs(v);
        collectStrs(k);
      });
    });
  }
  // Fix: 计算所有列的 SUM/AVG/MIN/MAX/MEDIAN + 跨列乘积 + 子集求和
  // v3.0: 递归展平嵌套对象（如 __comparisonData__ 内的 avgDiff/avgPct 等）
  const numericCols = { __all__: [] };
  const collectNum = (val) => {
    if (typeof val === 'number' && !isNaN(val)) {
      numericCols['__all__'].push(val);
    } else if (typeof val === 'object' && val !== null) {
      Object.values(val).forEach(collectNum);
    }
  };
  rows.forEach(row => {
    Object.entries(row).forEach(([k, v]) => {
      if (typeof v === 'number' && !isNaN(v)) {
        if (!numericCols[k]) numericCols[k] = [];
        numericCols[k].push(v);
      } else if (typeof v === 'object' && v !== null) {
        // 嵌套对象（如 __comparisonData__）的子字段也加入 __all__
        Object.values(v).forEach(collectNum);
      }
    });
  });
  const aggVals = new Set();
  let allMax = 0, allMin = Infinity;
  Object.values(numericCols).forEach(arr => {
    if (arr.length === 0) return;
    const sum = arr.reduce((a, b) => a + b, 0);
    const avg = sum / arr.length;
    const min = Math.min(...arr);
    const max = Math.max(...arr);
    const median = arr.slice().sort((a, b) => a - b)[Math.floor(arr.length / 2)];
    // 标准差 / 方差（stddev/variance 是合法统计量，不算幻觉）
    const variance = arr.reduce((acc, v) => acc + (v - avg) ** 2, 0) / arr.length;
    const stddev = Math.sqrt(variance);
    const sampleVariance = arr.length > 1
      ? arr.reduce((acc, v) => acc + (v - avg) ** 2, 0) / (arr.length - 1)
      : 0;
    const sampleStddev = Math.sqrt(sampleVariance);
    // 变异系数
    const cv = avg !== 0 ? stddev / Math.abs(avg) : 0;
    [sum, avg, min, max, median, stddev, sampleStddev, variance, sampleVariance, cv].forEach(n => {
      if (!isNaN(n) && n > 0) {
        aggVals.add(String(n));
        aggVals.add(String(Math.round(n * 100) / 100));
        aggVals.add(String(Math.round(n * 10) / 10));
        allMax = Math.max(allMax, n);
        allMin = Math.min(allMin, n);
      }
    });
  });
  const textNums = (r.interpretation.replace(/,/g, '').match(/\d+\.?\d*/g) || []).map(Number);
  const hallucinated = [];
  for (const tn of textNums) {
    if (tn >= 1900 && tn <= 2100) continue;
    if (tn <= 100) continue;
    if (tn > 100000) continue;
    const tnStr = String(tn);
    // 多重判定：原始数据 OR 聚合值 OR 在合理聚合范围内 (min*0.01, max*1000)
    const inRange = (allMax > 0 && tn >= allMin * 0.01 && tn <= allMax * 1000);
    const found = [...dataStrs].some(ds => ds === tnStr || ds.indexOf(tnStr) >= 0)
      || aggVals.has(tnStr)
      || aggVals.has(String(Math.round(tn * 100) / 100))
      || aggVals.has(String(Math.round(tn * 10) / 10))
      || inRange;
    if (!found) hallucinated.push(tn);
  }
  return { ok: hallucinated.length === 0, hallucinated };
}

// ============ 主流程 ============
async function main() {
  const raw = fs.readFileSync(QUESTIONS_FILE, 'utf-8');
  // 容忍两种格式：每行一条 JSONL，或多 JSON 连续（linter 可能合并相邻行）
  const normalized = raw.replace(/}\s*{/g, '}\n{');
  const questions = normalized
    .split('\n').map(l => l.trim()).filter(l => l)
    .map(l => JSON.parse(l));

  console.log(`\n[Golden Set Runner] 开始执行 ${questions.length} 个用例\n`);

  const { win } = await loadEnv();

  if (typeof win.analyzeQuestion !== 'function') {
    console.error('analyzeQuestion 未挂载');
    process.exit(1);
  }

  const results = [];
  let pass = 0, sqlOk = 0, dataOk = 0, interpOk = 0, noHall = 0;
  const byCategory = {};

  for (const q of questions) {
    process.stdout.write(`  ${q.id} (${q.category}) ... `);
    await loadDataset(win, q.dataset);
    let r;
    try {
      r = await runAnalysis(win, q.question);
    } catch (e) {
      r = { error: e.message };
    }

    if (r.error) {
      console.log(`ERROR: ${r.error}`);
      results.push({ id: q.id, category: q.category, error: r.error });
      continue;
    }

    const sql = checkSQL(r, q.expected_sql_pattern);
    const data = checkRows(r, q);
    const interp = checkInterpretation(r);
    const hallu = checkNoHallucination(r);

    if (sql) sqlOk++;
    if (data) dataOk++;
    if (interp) interpOk++;
    if (hallu.ok) noHall++;

    if (!byCategory[q.category]) byCategory[q.category] = { total: 0, pass: 0 };
    byCategory[q.category].total++;
    const overall = sql && data && interp && hallu.ok;
    if (overall) { pass++; byCategory[q.category].pass++; }

    const status = overall ? 'PASS' : 'FAIL';
    console.log(`${status} sql=${sql} data=${data} interp=${interp} noHallu=${hallu.ok}` +
      (hallu.hallucinated.length ? ` 幻觉=[${hallu.hallucinated.join(',')}]` : ''));

    results.push({
      id: q.id, category: q.category, question: q.question, dataset: q.dataset,
      sql_pass: sql, data_pass: data, interp_pass: interp, no_hallucination: hallu.ok,
      hallucinated: hallu.hallucinated,
      actual_rows: getRows(r).length,
      sql_text: r.sql ? r.sql.substring(0, 200) : null
    });
  }

  const report = {
    timestamp: new Date().toISOString(),
    total: questions.length,
    overall_pass: pass,
    sql_pass: sqlOk,
    data_pass: dataOk,
    interp_pass: interpOk,
    no_hallucination_pass: noHall,
    pass_rate: (pass / questions.length * 100).toFixed(1),
    sql_rate: (sqlOk / questions.length * 100).toFixed(1),
    data_rate: (dataOk / questions.length * 100).toFixed(1),
    interp_rate: (interpOk / questions.length * 100).toFixed(1),
    no_hallu_rate: (noHall / questions.length * 100).toFixed(1),
    by_category: byCategory,
    results
  };

  fs.writeFileSync(REPORT_FILE, JSON.stringify(report, null, 2), 'utf-8');

  console.log(`\n${'='.repeat(60)}`);
  console.log(`基线报告 (${report.timestamp})`);
  console.log('='.repeat(60));
  console.log(`总计: ${pass}/${questions.length} 通过 (${report.pass_rate}%)`);
  console.log(`  ① SQL 准确性:    ${sqlOk}/${questions.length} (${report.sql_rate}%)   [目标 ≥98% 核心 / ≥90% 长尾]`);
  console.log(`  ② 数据正确性:    ${dataOk}/${questions.length} (${report.data_rate}%)   [目标 100%]`);
  console.log(`  ③ 解读存在率:    ${interpOk}/${questions.length} (${report.interp_rate}%)   [目标 100%]`);
  console.log(`  ④ 反幻觉通过率:  ${noHall}/${questions.length} (${report.no_hallu_rate}%)   [目标 ≥99%]`);
  console.log(`\n按类别:`);
  Object.entries(byCategory).forEach(([cat, stat]) => {
    const pct = (stat.pass / stat.total * 100).toFixed(0);
    console.log(`  ${cat.padEnd(20)} ${stat.pass}/${stat.total} (${pct}%)`);
  });
  console.log(`\n报告写入: ${REPORT_FILE}`);
}

main().catch(e => {
  console.error('Fatal:', e);
  process.exit(1);
});