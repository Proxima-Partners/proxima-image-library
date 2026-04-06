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

- T1 local validation is complete.
- T1 production validation is still pending because Azure App Service is not deployed yet.
- Remaining T1 production checks:
  - Live health endpoints in Azure
  - Production redirect URI validation
  - Live SharePoint schema and read/write verification

## 7) Next logical step

- If Azure is still not deployed: begin T2 security audit work.
- If Azure is deployed: complete T1 production checks and close T1.
