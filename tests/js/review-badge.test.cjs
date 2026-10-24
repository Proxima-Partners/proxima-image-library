const { test } = require('node:test');
const assert = require('node:assert/strict');
const create = require('../../static/review-badge.js');

function fixture(fetcher) {
  const listeners = new Map(), timers = new Map();
  let next = 0;
  const badge = { textContent: '', style: { display: 'none' } };
  const events = {
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: name => listeners.delete(name),
  };
  const doc = { ...events, visibilityState: 'visible', getElementById: () => badge };
  const instance = create({ document: doc, window: events, fetch: fetcher,
    setTimeout: (fn, delay) => { timers.set(++next, { fn, delay }); return next; },
    clearTimeout: id => timers.delete(id),
  });
  return { instance, doc, badge, timers, listeners,
    emit: (name, data = {}) => listeners.get(name)?.(data) };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
const ok = count => ({ status: 200, ok: true, json: async () => ({ count }) });

test('one immediate request; no duplicate start/pageshow/refresh while pending', async () => {
  let calls = 0, finish;
  const f = fixture((url, options) => {
    calls++;
    assert.equal(url, '/api/pending-count');
    assert.equal(options.redirect, 'error');
    return new Promise(resolve => { finish = resolve; });
  });
  f.instance.start(); f.instance.start(); f.emit('pageshow'); f.instance.refresh();
  assert.equal(calls, 1);
  finish(ok(3)); await tick();
  assert.equal(f.badge.textContent, '3');
  assert.deepEqual([...f.timers.values()].map(t => t.delay), [30000]);
  f.instance.stop();
  assert.equal(f.timers.size, 0);
  assert.equal(f.listeners.size, 0);
});

test('hidden tabs do not poll; return to visibility performs one refresh', async () => {
  let calls = 0;
  const f = fixture(async () => { calls++; return ok(0); });
  f.doc.visibilityState = 'hidden'; f.instance.start(); await tick();
  assert.equal(calls, 0); assert.equal(f.timers.size, 0);
  f.doc.visibilityState = 'visible'; f.emit('visibilitychange'); await tick();
  assert.equal(calls, 1);
  f.doc.visibilityState = 'hidden'; f.emit('visibilitychange');
  assert.equal(f.timers.size, 0);
  f.instance.stop();
});

for (const status of [401, 403]) test(`auth ${status} stops polling across focus changes`, async () => {
  let calls = 0;
  const f = fixture(async () => { calls++; return { status, ok: false }; });
  f.instance.start(); await tick();
  f.emit('visibilitychange'); f.emit('pageshow'); await tick();
  assert.equal(calls, 1); assert.equal(f.timers.size, 0);
  assert.equal(f.badge.style.display, 'none');
  f.emit('pageshow', { persisted: true }); await tick();
  assert.equal(calls, 2); // bfcache restore checks the server, never bypasses auth
  assert.equal(f.timers.size, 0);
  f.instance.stop();
});

test('request timeout aborts and schedules a bounded later retry', async () => {
  let signal;
  const f = fixture((url, options) => new Promise((resolve, reject) => {
    signal = options.signal;
    signal.addEventListener('abort', () => reject(new Error('abort')));
  }));
  f.instance.start();
  [...f.timers.values()].find(t => t.delay === 10000).fn(); await tick();
  assert.equal(signal.aborted, true);
  assert.deepEqual([...f.timers.values()].map(t => t.delay), [30000]);
  f.instance.stop();
});

test('late response after hiding/stop never changes the badge', async () => {
  let finish;
  const f = fixture(() => new Promise(resolve => { finish = resolve; }));
  f.instance.start(); f.instance.stop(); finish(ok(99)); await tick();
  assert.equal(f.badge.textContent, ''); assert.equal(f.timers.size, 0);
});

test('malformed count and network failure preserve existing badge', async () => {
  let calls = 0;
  const f = fixture(async () => { if (++calls === 1) return ok('private-data'); throw new Error('secret'); });
  f.instance.start(); await tick();
  assert.equal(f.badge.textContent, '');
  await f.instance.refresh();
  assert.equal(f.badge.textContent, '');
  assert.equal(f.timers.size, 1);
  f.instance.stop();
});
