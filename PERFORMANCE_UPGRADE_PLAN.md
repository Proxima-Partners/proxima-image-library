# Image Library performance and maintenance plan

Assessment date: 2026-10-22. Priority: speed and reliability over minimum spend.

## Approved first release

- Pin and audit runtime dependencies; security updates to dotenv, Pillow, MCP 1.x and cryptography, with the MSAL update required by cryptography. Keep the Anthropic runtime SDK/model and Gunicorn concurrency unchanged for this release.
- Add privacy-filtered request/dependency, AI, image-processing and startup tracing to the existing Application Insights component.
- Make the complete Python 3.12 regression suite and vulnerability audit prerequisites for deployment. Remove the redundant vendored dependency install and per-release settings rewrite/restart. Deploy a small source-only ZIP, build once using Azure Oryx, and verify immutable commit identity before and after swap.
- Enable local liveness/warm-up probes and preserve deployment serialization. No backfills, data mutations, tier changes, scheduled write jobs or scale-out are included.

## Evidence and remaining bottlenecks

The audit found production and staging sharing `proxima-plan-s1` (S1, one instance, West US 2) with `PP-MCP-Server`. Plan daily average CPU was about 39–43%, memory 72–75%, and hourly CPU maxima repeatedly reached 100%. These are plan-level observations, not proof that Image Library alone caused saturation. In the sampled day production had 1,181 requests, about 3.44 seconds average response time, and staging consumed almost as much CPU as production.

Run [39838709947](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/39838709947) took about 14 minutes: staging deploy 7m41s, swap 5m13s, dependency install 12s and settings/restart wait 36s. Source packaging and eliminating restarts address unnecessary work; they do not guarantee a five-minute deployment on the current shared plan.

One synchronous Gunicorn worker serializes user requests while Graph, AI or SSE work is running. The 6,000-line Flask module, repeated Graph calls, process-local caches/state and expensive PNG encoding are follow-on targets. A larger Azure plan alone cannot remove this serialization.

## Next release: dedicated performance-first Azure plan (separate change approval)

1. Reconfirm subscription, target, both slots, authentication, app-setting slot stickiness, runtime, DNS, available SKUs and rollback identities. Collect CPU, memory, response percentiles and dependency timing under comparable workload.
2. Assess a **dedicated P2v3, one instance** for Image Library and its staging slot in West US 2. Do not resize or move other applications. Verify same resource group/region/OS and App Service webspace compatibility before creating or changing anything; regional SKU availability alone does not prove an in-place move is possible.
3. If a compatible same-webspace move is supported, plan a bounded maintenance window, preserve the old plan, move only `PP-App-Serv`, and validate both slots and the custom domain. Otherwise prepare a parallel app with staged configuration/auth/domain migration and an explicit cutover plan; do not improvise a DNS change.
4. Verify production reads, authentication and an explicitly approved canary upload; compare measured latency/deployment time. Roll back to the old plan/host if agreed acceptance thresholds fail. Do not remove the old plan until the acceptance window closes.
5. Keep one instance initially: upload sessions, preview tokens, rate limits, caches and maintenance locks need shared state before safe scale-out. Evaluate two instances only after that work.

## Following releases

| Order | Work | Acceptance gate |
| --- | --- | --- |
| 3 | One Gunicorn process with a tested threaded worker; reusable HTTP sessions; bounded retries only for safe/idempotent requests; cache coalescing and fewer Graph list fetches | Concurrent browse during SSE/upload; no duplicate writes or state races; tenant throttling respected |
| 4 | Isolate image/background work; defer or queue expensive derivatives where user experience permits; optional Blob/CDN delivery | Equivalent rights/originals/metadata; complete derivative links; measured grid and upload improvement |
| 5 | Shared job/session state and distributed leases, then evaluate two instances | Restart/scale/retry tests without lost jobs or double processing |
| 6 | Upgrade remaining SDKs/actions in small batches and split the Flask module by feature | Full regression and protocol/auth contract tests per batch |

Initial targets, to validate rather than claim as achieved: warm read API p95 below 500ms; grid usable below 1.5s; deployment below 5 minutes; swap below 2 minutes. Report AI processing separately from local app latency. Measure identical sample sizes, cache states, regions and request types; low usage is not evidence of spare capacity when latency suppresses usage.

## Unattended maintenance operating model

- **Now:** unattended CI tests/audits, source packaging, gated staging deploy, exact-release verification and serialized swap. A failed gate stops; no autonomous retry of uploads or destructive maintenance.
- **Daily read-only job, after provisioning approval:** inventory integrity, missing derivative counts, broken links, dependency failures, latency and failed-job summaries. Bound page count, concurrency, timeout and API quota. Store a durable run ID/report; alert only on actionable change.
- **Weekly:** dependency proposal with a fresh resolver/audit report and full tests; small compatible groups. Patch changes may enter an approved PR pipeline; major SDK/auth/protocol upgrades require explicit review. Retain known-good artifacts and release metrics.
- **Writes later:** durable queue plus lease, idempotency key, checkpoint/resume, retry budget, dry-run preview, row/asset limit and cancellation. Use a separately provisioned job runner (for example Container Apps Jobs), not a browser-held SSE connection or web-worker cron loop.
- **Always separately governed:** deletions, catalog-wide retagging, migrations, backfills, credential/access changes and DNS/tier changes. Approve exact dataset and pilot first, verify, then authorize the full run. Reports must distinguish attempted, succeeded, skipped and failed records.

Implementation model recommendation from the assessment: GPT-6 Astra at maximum reasoning for cross-cutting architecture, state/concurrency and release-risk review; use the same model for this first safety-critical implementation if available. Model choice does not replace test, audit or live release gates.
