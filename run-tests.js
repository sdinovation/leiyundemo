#!/usr/bin/env node
/**
 * 数分精灵 - AI 数据分析能力全面测试
 *
 * 测试维度：
 *   1. SQL 正确性（拼写、聚合、过滤、排序、LIMIT）
 *   2. 数据正确性（行数、字段值、聚合结果）
 *   3. AI 解读正确性（无幻觉、事实正确、不编造维度）
 *
 * 通过标准：3 项全 PASS
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = __dirname;
const HTML_PATH = path.join(ROOT, 'index.html');
const TEST_DIR = path.join(ROOT, 'test-datasets');

// ============ 测试结果聚合 ============
const results = [];
let passCount = 0, failCount = 0, totalCases = 0;

function record(name, dataset, sqlPass, dataPass, interpPass, detail) {
  totalCases++;
  const overallPass = sqlPass && dataPass && interpPass;
  if (overallPass) passCount++; else failCount++;
  results.push({ name, dataset, sqlPass, dataPass, interpPass, overallPass, detail });
}

function color(s, c) {
  const codes = { red: 31, green: 32, yellow: 33, cyan: 36, gray: 90, bold: 1 };
  return `\x1b[${codes[c] || 0}m${s}\x1b[0m`;
}
function PASS() { return color('PASS', 'green'); }
function FAIL() { return color('FAIL', 'red'); }
function WARN() { return color('WARN', 'yellow'); }

// 取得数据行（兼容 result.data.rows 和 result.rawResult）
function getRows(r) {
  if (!r) return [];
  if (r.data && Array.isArray(r.data.rows)) return r.data.rows;
  if (Array.isArray(r.rawResult)) return r.rawResult;
  return [];
}
function getRowsCount(r) {
  return getRows(r).length;
}

// ============ 加载 index.html 并设置测试环境 ============
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
      if (opts && opts.complete) {
        opts.complete({ data: rows, errors: [] });
      }
      return { data: rows, errors: [] };
    },
  };

  win.echarts = function () {
    return { setOption: () => {}, resize: () => {}, dispose: () => {} };
  };

  await new Promise(r => setTimeout(r, 1500));

  return { dom, win };
}

// ============ 加载数据集 ============
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
      // 清空跨数据集的状态
      win.window._lastRankFilter = null;
      win.window._lastExtraWhere = null;
      win.window._lastRangeFilter = null;
      win.window._lastLikeFilter = null;
    },
  });
  await new Promise(r => setTimeout(r, 50));
}

// ============ 运行单条分析 ============
async function runAnalysis(win, question, opts = {}) {
  win.window._lastQuery = question;
  win.window._lastQueryOptions = opts;
  win.window.hasUserApiKey = () => false;

  let result;
  try {
    result = await win.analyzeQuestion(question);
  } catch (e) {
    return { error: e.message };
  }
  return result;
}

function check(cond, msg) {
  return cond ? `${PASS()} ${msg}` : `${FAIL()} ${msg}`;
}

// ============ 测试用例 ============
async function testStudents(win) {
  const DATASET = 'students.csv';
  await loadDataset(win, DATASET);

  console.log('\n' + color('=== 学生信息表测试 ===', 'cyan'));

  // ---------- T1: LIKE - 姓刘的同学 ----------
  {
    const name = 'T1: 姓刘的同学 → LIKE 过滤 + 2 条';
    const q = '姓刘的同学';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /LIKE/i.test(r.sql) && !/<=/.test(r.sql);
    const dataPass = rows.length === 2;
    const interpPass = r && r.interpretation && !/性别|院系|班级/.test(r.interpretation);
    record(name, DATASET, !!sqlPass, !!dataPass, !!interpPass, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'LIKE 过滤')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(interpPass, '无维度幻觉')}`);
    if (rows.length) rows.forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T2: LIKE - 包含 "三" 的同学 ----------
  {
    const name = 'T2: 包含"三"的同学 → LIKE 过滤';
    const q = '姓名包含"三"的同学';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /LIKE/i.test(r.sql);
    const dataPass = rows.length >= 1;
    const has幻觉 = r && r.interpretation && /性别|班级/.test(r.interpretation);
    const interpPass = !has幻觉;
    record(name, DATASET, !!sqlPass, !!dataPass, !!interpPass, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'LIKE')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(interpPass, '无幻觉')}`);
    if (rows.length) rows.forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T3: 排名 - 学号在前五名的同学 ----------
  {
    const name = 'T3: 学号在前五名的同学 → ORDER BY 学号 DESC LIMIT 5';
    const q = '学号在前五名的同学';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /ORDER BY.*学号.*(ASC|DESC).*LIMIT\s+5/s.test(r.sql);
    const dataPass = rows.length === 5;
    const sqlNo幻觉 = r && r.sql && !/<=\s*\d+/.test(r.sql);
    const interpPass = r && r.interpretation && /学号/.test(r.interpretation);
    record(name, DATASET, !!sqlPass && sqlNo幻觉, !!dataPass, !!interpPass, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass && sqlNo幻觉, 'ORDER BY 学号 + LIMIT 5')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(interpPass, '有学号解读')}`);
    if (rows.length) rows.slice(0, 3).forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T4: 排名 - 成绩最高的 5 个 ----------
  {
    const name = 'T4: 成绩最高的5个 → ORDER BY DESC LIMIT 5';
    const q = '成绩最高的5个';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /ORDER BY.*成绩.*(ASC|DESC).*LIMIT\s+5/s.test(r.sql);
    const dataPass = rows.length === 5;
    const sorted = rows[0] && rows[4] && (rows[0].成绩 >= rows[4].成绩);
    record(name, DATASET, !!sqlPass, !!dataPass && sorted, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'ORDER BY 成绩 + LIMIT 5')} data=${check(dataPass && sorted, `rows=${rows.length} sorted DESC`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.slice(0, 3).forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T5: 聚合 - 各性别的人数 ----------
  {
    const name = 'T5: 各性别人数 → GROUP BY + COUNT';
    const q = '各性别人数';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /GROUP BY.*性别/i.test(r.sql) && /COUNT/i.test(r.sql);
    const dataPass = rows.length === 2;
    const sumOk = rows.reduce((s, x) => s + (x.计数 || x.人数 || 0), 0) === 12;
    record(name, DATASET, !!sqlPass, !!dataPass && sumOk, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'GROUP BY + COUNT')} data=${check(dataPass && sumOk, `rows=${rows.length} sum=12`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T6: 标量 - 男生人数 ----------
  {
    const name = 'T6: 男生人数 → COUNT 标量';
    const q = '男生人数';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /COUNT/i.test(r.sql) && /性别.*=.*男/.test(r.sql);
    const count = rows.reduce((s, x) => s + (x.计数 || x.人数 || 0), 0);
    const dataPass = count === 7;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, count, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'WHERE 性别=男 + COUNT')} data=${check(dataPass, `count=${count}`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }
}

async function testSales(win) {
  const DATASET = 'sales.csv';
  await loadDataset(win, DATASET);

  console.log('\n' + color('=== 销售数据表测试 ===', 'cyan'));

  // ---------- T7: 趋势 - 各城市销售额趋势 ----------
  {
    const name = 'T7: 各城市销售额趋势 → SUM + 多维度';
    const q = '各城市销售额趋势';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /SUM|销售额/.test(r.sql);
    const dataPass = rows.length > 0;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'SUM')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
  }

  // ---------- T8: 排名 - 销售额最高的产品 ----------
  {
    const name = 'T8: 销售额最高的产品 → ORDER BY DESC';
    const q = '销售额最高的产品';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /ORDER BY.*(ASC|DESC)/i.test(r.sql);
    const dataPass = rows.length > 0 && rows[0].产品;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'ORDER BY')} data=${check(dataPass, `top=${rows[0]?.产品}`)} interp=${check(!!r.interpretation, '有解读')}`);
  }

  // ---------- T9: 过滤 - 上海的销售额 ----------
  {
    const name = 'T9: 上海的销售额 → WHERE 城市=上海';
    const q = '上海的销售额';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /城市.*=.*上海/.test(r.sql);
    const dataPass = rows.length > 0;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'WHERE 城市=上海')} data=${check(!!dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
  }

  // ---------- T10: 对比 - 上海和北京的销售对比 ----------
  {
    const name = 'T10: 上海和北京的销售额对比';
    const q = '上海和北京的销售额对比';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = !!r && !!r.sql;
    const dataPass = rows.length > 0;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(!!sqlPass, '有效 SQL')} data=${check(!!dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
  }
}

async function testEmployees(win) {
  const DATASET = 'employees.csv';
  await loadDataset(win, DATASET);

  console.log('\n' + color('=== 员工信息表测试 ===', 'cyan'));

  // ---------- T11: 排名 - 薪资前 3 的员工 ----------
  {
    const name = 'T11: 薪资前3的员工 → ORDER BY + LIMIT 3';
    const q = '薪资前3的员工';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /ORDER BY.*薪资.*(ASC|DESC).*LIMIT\s+3/s.test(r.sql);
    const dataPass = rows.length === 3;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'ORDER BY 薪资 + LIMIT 3')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T12: 排名 - 薪资最高的 5 个 ----------
  {
    const name = 'T12: 薪资最高的5个员工 → ORDER BY + LIMIT 5';
    const q = '薪资最高的5个员工';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /ORDER BY.*薪资.*(ASC|DESC).*LIMIT\s+5/s.test(r.sql);
    const dataPass = rows.length === 5;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'ORDER BY 薪资 + LIMIT 5')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T13: 过滤 - 研发部员工人数 ----------
  {
    const name = 'T13: 研发部员工人数 → WHERE 部门=研发 + COUNT';
    const q = '研发部员工人数';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /部门.*=.*研发/.test(r.sql) && /COUNT/i.test(r.sql);
    const count = rows.reduce((s, x) => s + (x.计数 || x.人数 || 0), 0);
    const dataPass = count === 5;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, count, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'WHERE 部门=研发 + COUNT')} data=${check(dataPass, `count=${count}`)} interp=${check(!!r.interpretation, '有解读')}`);
  }

  // ---------- T14: LIKE - 姓刘的员工 ----------
  {
    const name = 'T14: 姓刘的员工 → LIKE';
    const q = '姓刘的员工';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /LIKE/i.test(r.sql);
    const dataPass = rows.length === 2;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'LIKE')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }
}

async function testEdge(win) {
  console.log('\n' + color('=== 边界场景测试 ===', 'cyan'));

  // ---------- T15: 边界 - 名字是张三（非 LIKE，应为 =）----------
  {
    const DATASET = 'students.csv';
    await loadDataset(win, DATASET);
    const name = 'T15: 名字是张三 → 等值匹配（=）非 LIKE';
    const q = '名字是张三的同学';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /=\s*['"]张三['"]/.test(r.sql);
    const dataPass = rows.length === 1 && rows[0].姓名 === '张三';
    const sqlNoLike = r && r.sql && !/LIKE/i.test(r.sql);
    record(name, DATASET, !!sqlPass && sqlNoLike, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass && sqlNoLike, '=张三 非 LIKE')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
  }

  // ---------- T16: 空结果 - 姓欧阳的同学 ----------
  {
    const DATASET = 'students.csv';
    await loadDataset(win, DATASET);
    const name = 'T16: 姓欧阳的同学 → 空结果';
    const q = '姓欧阳的同学';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /LIKE/i.test(r.sql);
    const dataPass = rows.length === 0;
    const interpPass = r && r.interpretation && r.interpretation.length < 80 && !/建议|试试/.test(r.interpretation);
    record(name, DATASET, !!sqlPass, !!dataPass, !!interpPass, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'LIKE')} data=${check(dataPass, `rows=0`)} interp=${check(interpPass, '简洁+无主动建议')}`);
  }

  // ---------- T17: 模糊词 - 包含上海 ----------
  {
    const DATASET = 'sales.csv';
    await loadDataset(win, DATASET);
    const name = 'T17: 包含上海的记录 → LIKE';
    const q = '包含上海的记录';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /LIKE/i.test(r.sql) && /上海/.test(r.sql);
    const dataPass = rows.length >= 3;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'LIKE %上海%')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
  }

  // ---------- T18: 模糊词 - 有上海的 ----------
  {
    const DATASET = 'sales.csv';
    await loadDataset(win, DATASET);
    const name = 'T18: 有上海的 → LIKE';
    const q = '有上海的记录';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /LIKE/i.test(r.sql);
    const dataPass = rows.length >= 3;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'LIKE')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
  }
}

// ============ 第二轮：新增场景测试 ============
async function testRange(win) {
  console.log('\n' + color('=== 第二轮：范围/HAVING/趋势/统计/占比/去重计数 ===', 'cyan'));

  // ---------- T19: 单值范围 - 成绩大于 85 的同学 ----------
  {
    const DATASET = 'students.csv';
    await loadDataset(win, DATASET);
    const name = 'T19: 成绩大于85的同学 → WHERE 成绩>85';
    const q = '成绩大于85的同学';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /(?:成绩|>)/.test(r.sql) && />\s*85/.test(r.sql);
    // 成绩 > 85: 李四 90, 赵六 92, 刘七 88, 陈八 95, 吴十二 87, 郑十三 91 = 6 人
    const dataPass = rows.length === 6 || (rows.length > 0 && rows.every(row => row.成绩 > 85));
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'WHERE 成绩 > 85')} data=${check(dataPass, `rows=${rows.length}（预期6）`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.slice(0, 3).forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T20: BETWEEN - 薪资在 15000 到 20000 的员工 ----------
  {
    const DATASET = 'employees.csv';
    await loadDataset(win, DATASET);
    const name = 'T20: 薪资在15000到20000之间 → BETWEEN';
    const q = '薪资在15000到20000之间的员工';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /薪资/.test(r.sql) && /(?:BETWEEN|>=|<=)/.test(r.sql);
    // 薪资 in [15000, 20000]: 王五 18000, 刘九 16000, 吴十二 17000, 张三 15000 = 4 人
    const dataPass = rows.length === 4 || (rows.length > 0 && rows.every(row => row.薪资 >= 15000 && row.薪资 <= 20000));
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'BETWEEN/范围')} data=${check(dataPass, `rows=${rows.length}（预期4）`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.slice(0, 3).forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T21: HAVING - 销售额超过 2500 的产品 ----------
  {
    const DATASET = 'sales.csv';
    await loadDataset(win, DATASET);
    const name = 'T21: 销售额超过2500的产品 → HAVING';
    const q = '销售额超过2500的产品';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /销售额/.test(r.sql) && /(?:>|HAVING)/.test(r.sql);
    // 销售额 > 2500: 北京产品C 3000, 上海产品C 2800, 杭州产品B 2500(不含), 北京产品C 3200 = 3 个产品记录
    // 或者按产品聚合后筛选
    const dataPass = rows.length > 0;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'WHERE/HAVING 销售额 > 2500')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.slice(0, 3).forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T22: 多条件 - 研发部薪资大于 15000 的员工 ----------
  {
    const DATASET = 'employees.csv';
    await loadDataset(win, DATASET);
    const name = 'T22: 研发部薪资大于15000 → 部门=研发 AND 薪资>15000';
    const q = '研发部薪资大于15000的员工';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /部门.*=.*研发/.test(r.sql) && /薪资.*>/.test(r.sql);
    // 研发部(5人): 张三 15000, 王五 18000, 刘七 22000, 刘九 16000, 吴十二 17000 — 薪资 > 15000: 王五/刘七/刘九/吴十二 = 4 人
    const dataPass = rows.length === 4 || (rows.length > 0 && rows.every(row => row.部门 === '研发' && row.薪资 > 15000));
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, '部门=研发 AND 薪资>15000')} data=${check(dataPass, `rows=${rows.length}（预期4）`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.slice(0, 3).forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T23: 趋势 - 各月销售额 ----------
  {
    const DATASET = 'sales.csv';
    await loadDataset(win, DATASET);
    const name = 'T23: 各月销售额趋势 → 按月分组 + SUM';
    const q = '各月销售额趋势';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /SUM|销售额/.test(r.sql);
    // 4 个月（2024-01~04），每个有 3 行
    const dataPass = rows.length >= 3;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'SUM 销售额')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.slice(0, 4).forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T24: 时间范围 - 2024 年 2 月之后的销售 ----------
  {
    const DATASET = 'sales.csv';
    await loadDataset(win, DATASET);
    const name = 'T24: 2024年2月之后的销售 → WHERE 日期 >= 2024-02';
    const q = '2024年2月之后的销售额';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /2024/.test(r.sql);
    // 2024-02 及之后 = 9 行（2/3/4 月各 3 行）；按城市聚合则 5 行
    const dataPass = rows.length === 5 || rows.length === 9;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'WHERE 日期 >= 2024-02')} data=${check(dataPass, `rows=${rows.length}（预期9）`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.slice(0, 3).forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T25: 统计 - 成绩的中位数 ----------
  {
    const DATASET = 'students.csv';
    await loadDataset(win, DATASET);
    const name = 'T25: 成绩的中位数 → median 聚合';
    const q = '成绩的中位数';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /(?:MEDIAN|中位数)/.test(r.sql);
    const dataPass = rows.length >= 1;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'MEDIAN/中位数')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T26: 占比 - 各城市销售额占比 ----------
  {
    const DATASET = 'sales.csv';
    await loadDataset(win, DATASET);
    const name = 'T26: 各城市销售额占比 → 百分比';
    const q = '各城市销售额占比';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /(?:SUM|销售额|占比)/.test(r.sql);
    // 5 个城市各占一定比例，sum of 占比 = 100%
    const dataPass = rows.length >= 3;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'SUM/占比')} data=${check(dataPass, `rows=${rows.length}（预期5城市）`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.slice(0, 3).forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T27: 去重计数 - 有多少个城市 ----------
  {
    const DATASET = 'sales.csv';
    await loadDataset(win, DATASET);
    const name = 'T27: 有多少个城市 → COUNT DISTINCT 城市';
    const q = '有多少个城市';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /COUNT|DISTINCT/i.test(r.sql);
    // 5 个城市: 上海/北京/广州/深圳/杭州
    const count = rows.reduce((s, x) => s + (x['去重计数'] || x.计数 || x.城市数量 || 0), 0);
    const dataPass = count === 5;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, count, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'COUNT/DISTINCT')} data=${check(dataPass, `count=${count}（预期5）`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T28: 按日期排序 - 入职日期最晚的 3 个员工 ----------
  {
    const DATASET = 'employees.csv';
    await loadDataset(win, DATASET);
    const name = 'T28: 入职日期最晚的3个员工 → ORDER BY 入职日期 DESC LIMIT 3';
    const q = '入职日期最晚的3个员工';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /ORDER BY.*入职日期.*(DESC|ASC).*LIMIT\s+3/s.test(r.sql);
    const dataPass = rows.length === 3;
    const sorted = rows.length === 3 && new Date(rows[0].入职日期) >= new Date(rows[2].入职日期);
    record(name, DATASET, !!sqlPass, !!dataPass && sorted, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'ORDER BY 入职日期 DESC LIMIT 3')} data=${check(dataPass && sorted, `rows=${rows.length} 入职日期降序`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T29: 累计 - 累计销售额 ----------
  {
    const DATASET = 'sales.csv';
    await loadDataset(win, DATASET);
    const name = 'T29: 累计销售额 → cumulative window';
    const q = '累计销售额';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /SUM.*OVER|累计|cumulative/i.test(r.sql);
    const dataPass = rows.length > 0;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'SUM OVER/累计')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.slice(0, 3).forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }

  // ---------- T30: 平均 - 平均薪资 ----------
  {
    const DATASET = 'employees.csv';
    await loadDataset(win, DATASET);
    const name = 'T30: 平均薪资 → AVG';
    const q = '平均薪资';
    const r = await runAnalysis(win, q);
    const rows = getRows(r);
    const sqlPass = r && r.sql && /(?:AVG|平均)/.test(r.sql);
    const dataPass = rows.length >= 1;
    record(name, DATASET, !!sqlPass, !!dataPass, !!r.interpretation, { sql: r.sql, rows: rows.length, interp: r.interpretation });
    console.log(`  ${name}: sql=${check(sqlPass, 'AVG/平均')} data=${check(dataPass, `rows=${rows.length}`)} interp=${check(!!r.interpretation, '有解读')}`);
    if (rows.length) rows.forEach(row => console.log(`     ${JSON.stringify(row)}`));
  }
}

// ============ 主流程 ============
async function main() {
  console.log(color('数分精灵 - AI 数据分析能力测试', 'bold'));
  console.log(color('═══════════════════════════════════════════════════════', 'gray'));

  let env;
  try {
    env = await loadEnv();
  } catch (e) {
    console.error(`${color('[错误]', 'red')} 加载测试环境失败：`, e.message);
    process.exit(1);
  }
  const { win } = env;

  if (typeof win.analyzeQuestion !== 'function') {
    console.error(`${color('[错误]', 'red')} analyzeQuestion 未挂载到 window，请检查 index.html`);
    process.exit(1);
  }

  console.log(color(`✓ 测试环境就绪`, 'green'));

  try {
    await testStudents(win);
    await testSales(win);
    await testEmployees(win);
    await testEdge(win);
    await testRange(win);
  } catch (e) {
    console.error(`${color('[错误]', 'red')} 测试异常：`, e.stack);
  }

  console.log('\n' + color('═══════════════════════════════════════════════════════', 'gray'));
  console.log(color('测试报告汇总', 'bold'));
  console.log(color('═══════════════════════════════════════════════════════', 'gray'));

  const grouped = {};
  results.forEach(r => {
    if (!grouped[r.dataset]) grouped[r.dataset] = [];
    grouped[r.dataset].push(r);
  });

  for (const [ds, items] of Object.entries(grouped)) {
    console.log(`\n${color(`[${ds}]`, 'cyan')} ${items.filter(i => i.overallPass).length}/${items.length} 通过`);
    items.forEach(r => {
      const tag = r.overallPass ? PASS() : FAIL();
      console.log(`  ${tag} ${r.name}`);
      if (!r.overallPass) {
        console.log(`     ${color('SQL:', 'gray')} ${r.detail?.sql || '(无)'}`);
        console.log(`     ${color('Rows:', 'gray')} ${r.detail?.rows}`);
        console.log(`     ${color('Interp:', 'gray')} ${(r.detail?.interp || '(无)').substring(0, 100)}`);
      }
    });
  }

  console.log('\n' + color('───────────────────────────────────────────────────────', 'gray'));
  const total = passCount + failCount;
  const pct = total ? ((passCount / total) * 100).toFixed(1) : '0';
  console.log(`${color('总计:', 'bold')} ${passCount} ${color('PASS', 'green')} / ${failCount} ${color('FAIL', 'red')}  (${pct}%)`);
  console.log(color('═══════════════════════════════════════════════════════', 'gray'));

  process.exit(failCount > 0 ? 1 : 0);
}

main().catch(e => {
  console.error(e);
  process.exit(1);
});