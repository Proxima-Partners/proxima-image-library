# Next Time Start Guide

Use this checklist to resume work quickly in this repo.

## 1) Open project and environment

```bash
cd /Users/mike-j4c/Projects/proxima-image-library
source .venv/bin/activate
```

## 2) Optional: free port 5000

```bash
pids=$(lsof -tiTCP:5000 -sTCP:LISTEN)
[[ -n "$pids" ]] && kill $pids
```

## 3) Choose run mode

### Fast local dev (no Microsoft login)

```bash
TEST_MODE=true STORAGE_MODE=local DEV_AUTH_BYPASS=true .venv/bin/python3 -m flask --app src.app run --port 5000 --debug
```

### Local auth testing (Microsoft login required)

```bash
TEST_MODE=true STORAGE_MODE=local DEV_AUTH_BYPASS=false .venv/bin/python3 -m flask --app src.app run --port 5000
```

Important:
- Use http://localhost:5000 consistently for login and callback.
- Do not mix localhost and 127.0.0.1 during one auth flow.

## 4) Validation commands

Run all tests:

```bash
.venv/bin/python3 -m pytest -v
```

Run automated T1 suite:

```bash
.venv/bin/python3 scripts/run_t1_suite.py
```

## 5) Auth expiry test (TEST_MODE only)

While logged in on localhost, run this in browser console:

```javascript
await fetch('/auth/test-expire-session', { method: 'POST', credentials: 'include' })
```

Expected result:
- Session is marked expired.
- Protected API requests return 401 until re-auth.
- App redirects to login on protected page refresh.

## 6) Current project checkpoint

- Automated tests pass: `29 passed` via `pytest -v`.
- Automated T1 regression suite passes (`overall_ok: true`).
- Manual auth checks completed locally:
  - Valid user session can call `/api/images` (200).
  - Non-admin access to `/api/maintenance/health-snapshot` is blocked (403).
  - Forced expiry (`/auth/test-expire-session`) returns expected 401 behavior.
  - Natural token/session expiry also observed (401 `Session expired`).
- Production app remains live at `https://library.liveproxima.org`.
- Shutterstock quota counter file currently: `proxima_ss_counter.json` -> `{"month":"2026-04","count":1}`.
- **T1 CLOSED** (2026-04-15): live Azure + SharePoint upload validated end-to-end.
  - Health endpoints 200, auth redirect chain correct, security headers present.
  - SharePoint list schema 8/8 columns matched (Source column added).
  - Upload pipeline: test JPEG → Claude AI metadata → SP file upload → SP list record — all verified.
  - SharePoint list record count: 3 (2 prior + 1 test upload).
- **T2 CLOSED** (2026-04-15): security audit complete.
  - pip-audit: 0 vulnerabilities (cryptography, pytest, python-multipart, pip all upgraded).
  - Error detail suppression: all API/SSE responses return generic messages.
  - Secrets, CORS, XSS, logging all verified clean.
- **T3 CLOSED** (2026-04-15): comprehensive code audit complete.
  - 13 `json.dumps` calls fixed with `ensure_ascii=False`.
  - 11 unused imports removed, 3 f-string fixes, 4 import-line splits.
  - MCP error handling hardened (structured errors, no `str(e)` leaks).
  - 6 env var reads centralized into Config class.
  - specification.md and development.md updated.
  - Ruff pyflakes: 0 errors.

## 7) Next logical step

- **T2 CLOSED** (2026-04-15): dependency CVEs fixed (0 remaining), error detail suppression applied, secrets/CORS/XSS all verified.
- **T3 CLOSED** (2026-04-15): code audit complete, lint clean, docs updated.
- All three pre-production gates (T1, T2, T3) are now closed.
- Clean up test upload record from SharePoint list if desired.

## 8) Recent changes (2026-04-30)

- Tag Manager embedded in Maintenance Console (`maintenance.html`), always visible across all workstream tabs (`data-workstream="always"`), starts collapsed.
- Tags Pending Review hub-metric CTA uses `openTagManager()` onclick — opens and scrolls to Tag Manager panel.
- **Approve All Recommended** in Tag Manager now also strips `?` prefix from matching records (via `bulk_patch_fields`), so the suggestions list correctly clears after bulk approval.
- M14 Apply Normalization button starts disabled; only enables after a successful M14 Category Preview run (shows candidate count in green).
- Hub-metric hover styles restored with teal background tint + shadow.
