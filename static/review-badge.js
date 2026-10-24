/* One visible, authenticated poll at a time. No browser/session data is logged. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory;
  else root.createReviewBadgePoller = factory;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (options) {
  const doc = options.document;
  const win = options.window;
  const fetcher = options.fetch;
  const later = options.setTimeout || setTimeout;
  const cancel = options.clearTimeout || clearTimeout;
  const Controller = options.AbortController || AbortController;
  const interval = options.interval || 30000;
  const timeout = options.timeout || 10000;
  let timer = null, pending = null, stopped = true, authExpired = false;

  function unschedule() {
    if (timer !== null) cancel(timer);
    timer = null;
  }
  function schedule() {
    unschedule();
    if (!stopped && !authExpired && doc.visibilityState === 'visible') {
      timer = later(refresh, interval);
    }
  }
  async function refresh() {
    unschedule();
    if (stopped || authExpired || pending || doc.visibilityState !== 'visible') return;
    const controller = new Controller();
    pending = controller;
    const deadline = later(() => controller.abort(), timeout);
    try {
      const response = await fetcher('/api/pending-count', {
        credentials: 'same-origin', redirect: 'error', signal: controller.signal,
      });
      if (response.status === 401 || response.status === 403) {
        authExpired = true;
        const badge = doc.getElementById('review-badge');
        if (badge) badge.style.display = 'none';
        return;
      }
      if (!response.ok) return;
      const data = await response.json();
      if (controller.signal.aborted || stopped || doc.visibilityState !== 'visible') return;
      if (!Number.isSafeInteger(data.count) || data.count < 0) return;
      const badge = doc.getElementById('review-badge');
      if (badge) {
        badge.textContent = String(data.count);
        badge.style.display = data.count > 0 ? '' : 'none';
      }
    } catch (_) {
      // Network errors/abort never log cookies, URLs or response bodies.
    } finally {
      cancel(deadline);
      pending = null;
      schedule();
    }
  }
  function visibility() {
    if (doc.visibilityState === 'visible') refresh();
    else { unschedule(); if (pending) pending.abort(); }
  }
  function pageshow(event) {
    // A restored page must get a fresh server decision before displaying a badge.
    // Ordinary visibility changes never restart a rejected session.
    if (event.persisted) authExpired = false;
    refresh();
  }
  function pagehide() { unschedule(); if (pending) pending.abort(); }
  return {
    refresh,
    start() {
      if (!stopped) return;
      stopped = false;
      doc.addEventListener('visibilitychange', visibility);
      win.addEventListener('pageshow', pageshow);
      win.addEventListener('pagehide', pagehide);
      refresh();
    },
    stop() {
      stopped = true;
      unschedule();
      if (pending) pending.abort();
      doc.removeEventListener('visibilitychange', visibility);
      win.removeEventListener('pageshow', pageshow);
      win.removeEventListener('pagehide', pagehide);
    },
  };
});
