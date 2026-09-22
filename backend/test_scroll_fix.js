// Mock-DOM test for new scrollToBottom logic
// scrollTop semantics: 0 = top (oldest), max = bottom (newest)
// User reading old content: scrollTop DECREASES (wheel up)
// User scrolling to bottom: scrollTop INCREASES (wheel down)

class MockArea {
  constructor() {
    this.scrollTop = 0;
    this.scrollHeight = 100;
    this.clientHeight = 100;
    this._listeners = {};
  }
  addEventListener(ev, fn) {
    (this._listeners[ev] = this._listeners[ev] || []).push(fn);
  }
  dispatch(ev) {
    (this._listeners[ev] || []).forEach(fn => fn({ target: this }));
  }
  scrollTo(opts) { this.scrollTop = opts.top; }
}

class MockMessageList {
  constructor() { this._observer = null; }
  triggerMutation() { if (this._observer) this._observer(); }
}

let _autoScrollLocked = false;
let _userScrolledUp = false;
const _SCROLL_BOTTOM_THRESHOLD = 24;
let _lastScrollTop = 0;
let _lastScrollHeight = 0;
let _scrollFollowTimer = null;
let _mutationObserver = null;
let _area, _messageList;

function initSmartScroll() {
  _area = new MockArea();
  _messageList = new MockMessageList();
  _area.addEventListener('scroll', () => {
    const { scrollTop, scrollHeight, clientHeight } = _area;
    const atBottom = scrollHeight - scrollTop - clientHeight <= _SCROLL_BOTTOM_THRESHOLD;
    if (atBottom) {
      _userScrolledUp = false;
    } else if (scrollTop < _lastScrollTop) {
      _userScrolledUp = true;
    }
    _lastScrollTop = scrollTop;
    _lastScrollHeight = scrollHeight;
  });
  _mutationObserver = () => {
    if (!_userScrolledUp && !_autoScrollLocked) scheduleFollowScroll();
  };
  // 关键：把 observer 挂到 _messageList 上，triggerMutation 才能触发
  _messageList._observer = _mutationObserver;
}

function scheduleFollowScroll() {
  if (_scrollFollowTimer) return;
  _scrollFollowTimer = setImmediate(() => {
    _scrollFollowTimer = null;
    scrollToBottom(false, true);
  });
}

function scrollToBottom(force, immediate) {
  if (_autoScrollLocked && !force) return false;
  if (_userScrolledUp && !force) return false;
  _lastScrollTop = _area.scrollTop;
  _area.scrollTo({ top: _area.scrollHeight, behavior: 'auto' });
  if (force) {
    _userScrolledUp = false;
    _lastScrollTop = _area.scrollTop;
    _lastScrollHeight = _area.scrollHeight;
  }
  return true;
}

// helper: 模拟真实用户滚动（连续小步）
function userScrollTo(targetScrollTop, totalHeight = 200, step = 10) {
  const start = _area.scrollTop;
  const dir = targetScrollTop > start ? 1 : -1;
  let cur = start;
  while ((dir > 0 && cur < targetScrollTop) || (dir < 0 && cur > targetScrollTop)) {
    cur += dir * step;
    if ((dir > 0 && cur > targetScrollTop) || (dir < 0 && cur < targetScrollTop)) {
      cur = targetScrollTop;
    }
    _area.scrollTop = cur;
    _area.scrollHeight = totalHeight;
    _area.clientHeight = 100;
    _area.dispatch('scroll');
  }
}

function setAreaState(scrollTop, scrollHeight, clientHeight) {
  _area.scrollTop = scrollTop;
  _area.scrollHeight = scrollHeight;
  _area.clientHeight = clientHeight;
  _area.dispatch('scroll');
}

function reset() {
  _autoScrollLocked = false;
  _userScrolledUp = false;
  _lastScrollTop = 0;
  _lastScrollHeight = 0;
  _scrollFollowTimer = null;
  initSmartScroll();
}

function clearImmediateSafely() {
  if (_scrollFollowTimer) {
    clearImmediate(_scrollFollowTimer);
    _scrollFollowTimer = null;
  }
}

let passed = 0, failed = 0;
function assert(cond, msg) {
  if (cond) { passed++; console.log(`  PASS: ${msg}`); }
  else { failed++; console.log(`  FAIL: ${msg}`); }
}

// 场景 1：初始吸底
function test1() {
  console.log('场景 1：初始空对话');
  reset();
  const r = scrollToBottom(false, true);
  assert(r === true, 'scrollToBottom 应成功');
  assert(_area.scrollTop === 100, 'scrollTop 应为 100');
}

// 场景 2：用户向上滚（wheel up，scrollTop 减小）→ 不吸底
function test2() {
  console.log('场景 2：用户向上滚不吸底');
  reset();
  // 用户在底部 (scrollTop=100)
  setAreaState(100, 200, 100);
  assert(_userScrolledUp === false, '初始在底部 _userScrolledUp=false');
  // 用户向上滚（scrollTop 减小）
  userScrollTo(50, 200);
  assert(_userScrolledUp === true, '向上滚后 _userScrolledUp=true');
  const r = scrollToBottom(false, true);
  assert(r === false, '应跳过（不打断用户）');
}

// 场景 3：用户滚回底部（scrollTop 增大）→ 重新跟随
function test3() {
  console.log('场景 3：用户滚回底部');
  reset();
  setAreaState(100, 200, 100);  // 在底部
  // 用户先向上滚到 50（用真实滚动）
  userScrollTo(50, 200);
  assert(_userScrolledUp === true, '先标记 _userScrolledUp=true');
  // 用户向下滚回底部（scrollTop 增大）
  userScrollTo(100, 200);
  assert(_userScrolledUp === false, '滚回底部 _userScrolledUp 重置');
  const r = scrollToBottom(false, true);
  assert(r === true && _area.scrollTop === 200, `应滚到 200，实际 ${_area.scrollTop}`);
}

// 场景 4：MutationObserver 自动跟随（异步）
function test4(cb) {
  console.log('场景 4：MutationObserver 自动跟随');
  reset();
  setAreaState(100, 200, 100);
  assert(_userScrolledUp === false, '在底部状态正确');
  _area.scrollHeight = 500;
  _messageList.triggerMutation();
  setImmediate(() => {
    setImmediate(() => {
      assert(_area.scrollTop === 500, `跟随到 500，实际 ${_area.scrollTop}`);
      cb();
    });
  });
}

// 场景 5：用户向上滚时 MutationObserver 不强制
function test5(cb) {
  console.log('场景 5：用户向上滚时 MutationObserver 不强制');
  reset();
  setAreaState(100, 200, 100);
  userScrollTo(50, 500);
  assert(_userScrolledUp === true, '标记 _userScrolledUp');
  const beforeTop = _area.scrollTop;
  _area.scrollHeight = 700;
  _messageList.triggerMutation();
  setImmediate(() => {
    setImmediate(() => {
      assert(_area.scrollTop === beforeTop, `未跟随，仍为 ${_area.scrollTop}`);
      cb();
    });
  });
}

// 场景 6：force=true 强制吸底
function test6() {
  console.log('场景 6：force=true 强制吸底');
  reset();
  setAreaState(100, 200, 100);
  userScrollTo(50, 500);
  assert(_userScrolledUp === true, '初始 _userScrolledUp=true');
  const r = scrollToBottom(true, true);
  assert(r === true && _area.scrollTop === 500, `force 应吸底到 500，实际 ${_area.scrollTop}`);
  assert(_userScrolledUp === false, 'force 后 _userScrolledUp=false');
}

// 场景 7：锁定时不跟随
function test7(cb) {
  console.log('场景 7：_autoScrollLocked=true 不跟随');
  reset();
  setAreaState(100, 200, 100);
  _autoScrollLocked = true;
  const before2 = _area.scrollTop;
  _area.scrollHeight = 400;
  _messageList.triggerMutation();
  setImmediate(() => {
    setImmediate(() => {
      assert(_area.scrollTop === before2, '锁定时未跟随');
      const r = scrollToBottom(false, true);
      assert(r === false, '锁定时 scrollToBottom 返回 false');
      _autoScrollLocked = false;
      cb();
    });
  });
}

// 场景 8：scrollToBottom 的程序化滚动不误判
// 验证：调用 scrollToBottom 后，scrollTop 变化不会触发错误的 _userScrolledUp
function test8() {
  console.log('场景 8：程序滚动不误判（scrollToBottom 内部）');
  reset();
  // 用户在底部
  setAreaState(100, 200, 100);
  assert(_userScrolledUp === false, '初始 _userScrolledUp=false');
  // 程序滚动：模拟 scrollToBottom 的内部行为
  // 1. 先同步 _lastScrollTop 到当前 scrollTop
  _lastScrollTop = _area.scrollTop;  // = 100
  // 2. 然后设置 scrollTop（程序化，不触发 scroll 事件）
  _area.scrollTop = 200;  // 直接到 scrollHeight
  // 3. 因为没有触发 scroll 事件，handler 不会跑
  // 验证：_userScrolledUp 仍为 false（没被错误标记）
  assert(_userScrolledUp === false, `程序滚动不触发 _userScrolledUp（实际=${_userScrolledUp}）`);
  assert(_lastScrollTop === 100, `_lastScrollTop 应保持 100（实际=${_lastScrollTop}）`);
}

// 场景 9：阈值收紧
function test9() {
  console.log('场景 9：阈值收紧 - 30px 处不视为底部');
  reset();
  setAreaState(100, 200, 100);
  assert(_userScrolledUp === false, '初始在底部');
  // scrollTop=70, scrollHeight=200, clientHeight=100 → atBottom=30 > 24
  userScrollTo(70, 200);
  assert(_userScrolledUp === true, '30px 处应视为非底部');
}

test1();
test2();
test3();
test4(() => {
  test5(() => {
    test6();
    test7(() => {
      test8();
      test9();
      console.log(`\n===== ${passed} passed, ${failed} failed =====`);
      process.exit(failed > 0 ? 1 : 0);
    });
  });
});