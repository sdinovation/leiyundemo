class MockArea {
  constructor() { this.scrollTop = 0; this.scrollHeight = 100; this.clientHeight = 100; this._listeners = {}; }
  addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); }
  dispatch(ev) { (this._listeners[ev] || []).forEach(fn => fn({ target: this })); }
  scrollTo(opts) { this.scrollTop = opts.top; }
}
class MockMessageList { constructor() { this._observer = null; } triggerMutation() { if (this._observer) this._observer(); } }

let _autoScrollLocked = false, _userScrolledUp = false;
const _SCROLL_BOTTOM_THRESHOLD = 24;
let _lastScrollTop = 0, _scrollFollowTimer = null, _area, _messageList;

function initSmartScroll() {
  _area = new MockArea();
  _messageList = new MockMessageList();
  _area.addEventListener('scroll', () => {
    const { scrollTop, scrollHeight, clientHeight } = _area;
    const atBottom = scrollHeight - scrollTop - clientHeight <= _SCROLL_BOTTOM_THRESHOLD;
    if (atBottom) _userScrolledUp = false;
    else if (scrollTop < _lastScrollTop) _userScrolledUp = true;
    _lastScrollTop = scrollTop;
  });
  _messageList._observer = () => {
    console.log('  [observer fired] _userScrolledUp=', _userScrolledUp, '_autoScrollLocked=', _autoScrollLocked, 'scrollHeight=', _area.scrollHeight);
    if (!_userScrolledUp && !_autoScrollLocked) scheduleFollowScroll();
  };
}
function scheduleFollowScroll() {
  if (_scrollFollowTimer) { console.log('  [schedule] skipped (timer pending)'); return; }
  _scrollFollowTimer = setImmediate(() => {
    console.log('  [setImmediate fires]');
    _scrollFollowTimer = null;
    scrollToBottom(false, true);
  });
}
function scrollToBottom(force) {
  if (_autoScrollLocked && !force) { console.log('  [scrollToBottom] blocked by lock'); return; }
  if (_userScrolledUp && !force) { console.log('  [scrollToBottom] blocked by userScrolledUp'); return; }
  console.log('  [scrollToBottom] scrolling to', _area.scrollHeight, 'from', _area.scrollTop);
  _lastScrollTop = _area.scrollTop;
  _area.scrollTo({ top: _area.scrollHeight });
}

initSmartScroll();
console.log('Step 1: setAreaState(100, 200, 100)');
_area.scrollTop = 100; _area.scrollHeight = 200; _area.clientHeight = 100; _area.dispatch('scroll');
console.log('  scrollTop=', _area.scrollTop, '_userScrolledUp=', _userScrolledUp);

console.log('Step 2: scrollHeight=500');
_area.scrollHeight = 500;

console.log('Step 3: triggerMutation');
_messageList.triggerMutation();
console.log('  scrollTop=', _area.scrollTop);

setImmediate(() => {
  console.log('Step 4 (setImmediate): scrollTop=', _area.scrollTop);
});