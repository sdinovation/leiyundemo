'use strict';
/**
 * 验证深色模式为默认主题
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const HTML_PATH = path.join(__dirname, '..', '..', 'index.html');

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

(async () => {
  const html = fs.readFileSync(HTML_PATH, 'utf-8');
  // Strip external scripts that won't work in jsdom
  const patched = html.replace(/let parsedData = \{/, 'var parsedData = {');
  const cleaned = patched
    .replace(/<script src="tailwindcss\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="echarts\.min\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="papaparse\.min\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="lucide\.min\.js"[^>]*><\/script>/g, '');

  let passed = 0, failed = 0;
  function assert(cond, msg) {
    if (cond) { console.log('  ✓ ' + msg); passed++; }
    else { console.log('  ✗ ' + msg); failed++; }
  }

  // Test 1: <html> 标签默认 class="dark"
  const htmlClassMatch = cleaned.match(/<html[^>]*class="([^"]*)"/);
  assert(htmlClassMatch && htmlClassMatch[1] === 'dark',
    '<html> 默认 class="dark"（实际: ' + (htmlClassMatch ? htmlClassMatch[1] : 'none') + ')');

  // Test 2: :root 选择器包含深色变量
  assert(/:root\s*\{[^}]*--color-bg:\s*#0a0a0f/.test(cleaned),
    ':root 包含深色背景色 #0a0a0f');
  assert(/:root\s*\{[^}]*--color-text-primary:\s*#f1f1f4/.test(cleaned),
    ':root 包含深色文字色 #f1f1f4');

  // Test 3: .light 选择器（保留但禁用）含浅色变量
  assert(/\.light\s*\{[^}]*--color-bg:\s*#fafaf9/.test(cleaned),
    '.light 包含浅色背景色 #fafaf9（保留但禁用）');

  // Test 4: initTheme 强制 dark
  assert(/function initTheme\(\)\s*\{[^}]*setTheme\(['"]dark['"]\)/.test(cleaned),
    'initTheme 强制调用 setTheme("dark")');

  // Test 5: setTheme 强制添加 dark class
  assert(/function setTheme\([^)]*\)\s*\{[^}]*document\.documentElement\.classList\.add\(['"]dark['"]\)/.test(cleaned),
    'setTheme 强制添加 dark class');

  // Test 6: setTheme 强制移除 light class
  assert(/function setTheme\([^)]*\)\s*\{[^}]*document\.documentElement\.classList\.remove\(['"]light['"]\)/.test(cleaned),
    'setTheme 强制移除 light class');

  // Test 7: toggleTheme 不切换（浅色已禁用）
  assert(/function toggleTheme\(\)\s*\{[^}]*浅色模式已禁用/.test(cleaned),
    'toggleTheme 显示"浅色模式已禁用"提示');

  // Test 8: 主题设置菜单项显示禁用状态
  assert(/主题设置[\s\S]*深色（默认）/.test(cleaned),
    '主题设置菜单显示"深色（默认）"标签');

  // Test 9: 通过 jsdom 加载后 html.classList 实际包含 dark
  const dom = new JSDOM(cleaned, {
    url: 'http://localhost/',
    runScripts: 'outside-only',
    pretendToBeVisual: true,
    resources: 'usable'
  });
  const win = dom.window;
  // Mock dependencies before evaluating scripts
  win.tailwind = { config: {} };
  win.lucide = { createIcons: () => {}, createElement: () => null };
  win.Papa = { parse: () => ({ data: [], errors: [] }) };
  win.echarts = function () { return { setOption: () => {}, resize: () => {}, dispose: () => {}, on: () => {} }; };
  win.fetch = () => Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  // Now evaluate the script content manually
  const scriptMatches = cleaned.match(/<script>([\s\S]*?)<\/script>/g) || [];
  for (const sm of scriptMatches) {
    const code = sm.replace(/^<script>/, '').replace(/<\/script>$/, '');
    try { win.eval(code); } catch(e) { /* ignore errors from missing deps */ }
  }
  assert(win.document.documentElement.classList.contains('dark'),
    'jsdom 加载后 <html> 含 dark class');
  assert(!win.document.documentElement.classList.contains('light'),
    'jsdom 加载后 <html> 不含 light class');

  // Test 10: localStorage shufen-theme 强制为 dark
  const stored = win.localStorage.getItem('shufen-theme');
  assert(stored === 'dark',
    'localStorage shufen-theme = "dark"（实际: ' + (stored || 'null') + ')');

  // Test 11: 即使调用 toggleTheme 也不能切换到 light
  if (typeof win.toggleTheme === 'function') {
    win.toggleTheme();
    assert(win.document.documentElement.classList.contains('dark'),
      'toggleTheme 后仍保持 dark');
  }

  console.log('\n===== 汇总 =====');
  console.log('通过: ' + passed + ' / ' + (passed + failed));
  process.exit(failed > 0 ? 1 : 0);
})().catch(e => { console.error('Error:', e.message); process.exit(1); });
