# Security Audit — AbsenzDash

**Date:** 2026-09-12
**Scope:** `wordpress-plugin/` (PHP, internet-facing), `frontend/` (React/TS source), `backend/` (FastAPI + docker-compose), deployment/CI configuration and docs.
**Method:** Read-only static review of the full codebase by component, plus cross-component verification of the trust boundaries. No files were modified. Headline findings were independently spot-verified against the code during synthesis.

---

## 1. Architecture & threat model

- The **WordPress plugin** is the only internet-facing component. It serves the SPA and exposes a generic REST reverse proxy (`absenzdash/v1/api/<path>`) to the backend, attaching trusted identity headers (`X-WordPress-Secret`, `-User`, `-Email`, `-Name`, `-Role`, `-WebUntis-Code`).
- The **backend** (FastAPI, docker-compose) sits on a server without internet access, intended to be reachable only from the webserver IP through two firewalls. It authenticates requests **solely** via the shared secret and blindly trusts the identity headers (by design, TECH-SPEC §3).
- Data at risk: absence records, class-register entries and names of **minors** — a GDPR/DSGVO-reportable breach if compromised.

Threat actors considered: (a) internet attacker reaching the backend through a compromised/misconfigured webserver, (b) malicious or compromised WP admin, (c) authenticated teacher overstepping scope, (d) another container joined to the shared Docker network.

## 2. Executive summary

**4 High · 7 Medium · 13 Low · 10 Info**

The application code is in good shape: authorization coverage on the backend is complete and correct (verified), there is no SQL-injection or XSS surface in the application code, secrets are compared timing-safe, and no secrets are committed to the repo.

The actual risk concentration is the **trust boundary between plugin and backend** and the **deployment hygiene** around it: one static, long-lived secret grants full impersonation of any user in any role (H-1), it travels in cleartext HTTP together with all student PII (H-2), it is silently accepted even when empty or `changeme` (H-3), and the backend port is published on all host interfaces although nothing needs that (H-4). All four are cheap to mitigate — three of them are configuration-only.

## 3. Findings overview

| ID | Severity | Component | Finding |
|----|----------|-----------|---------|
| H-1 | High | backend | Static shared secret is a skeleton key (arbitrary identity/role claims + auto-provisioning) |
| H-2 | High | backend/config | Plugin→backend traffic is plain HTTP; secret and student PII cross the network in cleartext |
| H-3 | High | backend | Empty/weak `WORDPRESS_PROXY_SECRET` accepted — empty secret silently authenticates |
| H-4 | High | config | Backend port 8000 published on `0.0.0.0` although unused by the architecture |
| M-1 | Medium | config | Shared external Docker network `absenzflow-shared` bypasses the firewall trust model |
| M-2 | Medium | backend | No rate limiting / body limits / sync mutex; expensive endpoints unprotected |
| M-3 | Medium | backend | Per-request user upsert + audit row: unbounded growth, write amplification, unique-race 500s |
| M-4 | Medium | config | Hardcoded weak PostgreSQL credentials (`absenzdash:absenzdash`) committed |
| M-5 | Medium | config | Entire backend directory incl. `.env` mounted writable into the container |
| M-6 | Medium | config | Backend container runs as root; dev deps in prod image; no hardening options |
| M-7 | Medium | plugin | Raw non-JSON backend responses echoed into the WP origin without hardening headers |
| L-1 | Low | plugin | `pfad` proxy path can be overridden via request body/query (parameter pollution) |
| L-2 | Low | plugin | Internal backend host/port leaked in 502 error messages |
| L-3 | Low | plugin | Shared secret stored in `wp_options` and rendered as a plaintext form field |
| L-4 | Low | plugin | SSRF/exfil surface via unrestricted `backend_url` setting |
| L-5 | Low | backend | `/docs`, `/redoc`, `/openapi.json` exposed unauthenticated |
| L-6 | Low | backend | Malformed ASV CSV aborts the entire sync pipeline; no size/encoding safeguards |
| L-7 | Low | backend | Several uncaught-exception 500s; admin endpoints echo internal error text |
| L-8 | Low | backend | Email pipeline: no address validation; poisoned names silently disable notifications |
| L-9 | Low | frontend | No session-expiry handling; stale student data stays on screen |
| L-10 | Low | frontend | `sort_by`/`offset` URL params forwarded unvalidated (backend whitelist verified) |
| L-11 | Low | config | No restart policies, no backend healthcheck — silent outage risk |
| L-12 | Low | config | Unpinned base images and dependency ranges; `npm install` instead of `npm ci` in CI |
| L-13 | Low | config/docs | Network hardening, TLS and secret rotation entirely undocumented |
| I-1..I-10 | Info | various | See section 7 |

---

## 4. High findings

### H-1 — Static shared secret is a skeleton key

**Status:** ⚠️ Design bewusst beibehalten (statisches Secret bleibt TECH-SPEC §3-konform), HMAC-Request-Signing als Ausbaustufe zurückgestellt (siehe ROADMAP.md, Abschnitt "Technical debt"); Remediation-Maßnahme 3 ("Log 401s at WARNING and alert on `wordpress_proxy_created` events") wurde ebenfalls nicht umgesetzt.

- **Location:** `backend/app/api/deps.py:38-89`
- **Description:** The entire plugin→backend trust boundary is one static header, `X-WordPress-Secret` (compared with `hmac.compare_digest` — timing-safe, good). Whoever presents the secret may set `X-WordPress-User` / `-Role` / `-Email` / `-Name` to **arbitrary values**; the dependency get-or-creates a `nutzer` row on the spot (`deps.py:59-67`). An attacker holding the secret can mint a brand-new `schulleitung` account in a single request and read every student's absence records, class-register entries and PDF exports. There is no per-request signature, nonce, expiry or rotation mechanism; the secret is long-lived and identical for all requests. This matches the intended design (TECH-SPEC §3), so it is a **design risk**, not an implementation bug. Spot-verified during synthesis.
- **Impact:** Secret compromise (sniffed per H-2, leaked from the WP options table per L-3, copied `.env`, any WP plugin vulnerability with option-read) = complete, undetectable breach of all student PII with full admin rights. Successful impersonation produces only routine `wordpress_proxy_created/updated` audit rows; there is no alerting.
- **Remediation:**
  1. Terminate TLS for plugin→backend traffic (see H-2) so the secret never crosses the wire in cleartext.
  2. Consider upgrading to HMAC request signing (HMAC over method+path+body+timestamp, secret as key) — the secret then never crosses the wire at all and replay windows are bounded.
  3. Document and script a secret-rotation procedure.
  4. Log 401s at WARNING and alert on `wordpress_proxy_created` events for unexpected `wp_user_id`s.

### H-2 — Plugin→backend traffic is plain HTTP

**Status:** ⚠️ Accepted Risk (2026-09-14, siehe docs/ADMIN.md, Abschnitt "Netzwerk & Absicherung") — nicht behoben, bewusst akzeptiert.

- **Location:** `docs/deployment.md:93`, `docs/ADMIN.md:38` (documented `http://absenzdash-backend:8000` URLs), `backend/Dockerfile:20` (bare uvicorn); no TLS/reverse-proxy configuration exists in the repo.
- **Description:** The backend is served by uvicorn directly over plain HTTP. The `X-WordPress-Secret` header, all identity headers and all response data (student PII incl. §90-relevant records) cross the network unencrypted — either on the shared Docker bridge `absenzflow-shared` (sniffable by any co-tenant container) or, in the two-server topology, across the school intranet between the firewalls. No document states this as an explicitly accepted risk.
- **Impact:** Anyone able to sniff the path obtains the skeleton key (H-1) plus live student PII. GDPR-reportable.
- **Remediation:** Put a small TLS-terminating reverse proxy (nginx/Traefik sidecar, internal CA or school-issued cert) in front of uvicorn and configure the plugin's backend URL as `https://…` (`wp_remote_request()` supports this without code changes). If the risk is consciously accepted (isolated wire, trusted hypervisor), document that decision and its rationale in `docs/ADMIN.md`.

### H-3 — Empty/weak `WORDPRESS_PROXY_SECRET` silently authenticates

**Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)

- **Location:** `backend/app/core/config.py:8` (plain `str`, no validator), `backend/app/api/deps.py:47`, `backend/.env.example:2` (`WORDPRESS_PROXY_SECRET=changeme`). Spot-verified.
- **Description:** Pydantic accepts any string, including the empty string. With `WORDPRESS_PROXY_SECRET=` empty, `hmac.compare_digest("", "")` is `True` for a request with an **empty** header — authentication is effectively disabled while appearing configured. A verbatim copy of `.env.example` yields the publicly known secret `changeme`. There is no startup-time strength check.
- **Impact:** Anyone who can reach the backend port (see H-4, M-1) gets full unauthenticated access under a misconfiguration the application never warns about.
- **Remediation:** Add a pydantic field validator on `Settings`: reject empty, reject known placeholders (`changeme`, `test-*`), require ≥ 32 high-entropy characters; fail fast so the container refuses to start.

### H-4 — Backend port published on `0.0.0.0`

**Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)

- **Location:** `backend/docker-compose.yml:23-24` (`"8000:8000"`). Spot-verified.
- **Description:** The compose file — the documented production deployment artifact — publishes the backend on all host interfaces. The WP plugin does not need this published port at all: it reaches the backend via the `absenzflow-shared` Docker network by service name. Docker additionally inserts its own iptables NAT/FORWARD rules that frequently bypass host-level firewalls like ufw, so the effective exposure rests entirely on the (unverifiable from this repo) perimeter firewalls.
- **Impact:** Any firewall gap or unexpected interface makes the skeleton-key backend (H-1) reachable to hosts that were never meant to see it — combined with H-3, a weak/empty secret then equals a public data breach. Severity assumes the two-firewall premise could fail or be misconfigured; if the ruleset is verified correct, this downgrades to Medium.
- **Remediation:** Drop the `ports:` mapping entirely (preferred), or bind to the specific interface facing the webserver (`"10.x.x.x:8000:8000"`, or `127.0.0.1:8000:8000` in same-host topologies). Verify actual exposure with an external port scan.

---

## 5. Medium findings

### M-1 — Shared external Docker network bypasses the firewall trust model
**Status:** ✅ dokumentiert / soweit im Repo möglich behoben (2026-09-14) — kein struktureller Fix möglich (`absenzflow-shared` ist `external: true`, wird vom Schwesterprojekt `wp-test` verwaltet), siehe docs/ADMIN.md, Abschnitt "Netzwerk & Absicherung", und ROADMAP.md, Abschnitt "Technical debt".
- **Location:** `backend/docker-compose.yml:31-41`, `docs/deployment.md:173-179`
- The backend joins `absenzflow-shared` (`external: true`), shared with the sister project's WordPress staging stack. Every container ever joined to that network — including WordPress with its large plugin/PHP attack surface — can reach `absenzdash-backend:8000` directly, bypassing both firewalls, and can brute-force the secret at LAN speed. The app has no 401 logging, no lockout, no rate limit.
- **Remediation:** Dedicated network containing only the WP container and absenzdash-backend; log 401s with source; rate limiting (M-2); document that joining `absenzflow-shared` grants attack surface on AbsenzDash.

### M-2 — No rate limiting / body limits / sync mutex
**Status:** ✅ erledigt für den Sync-Mutex-Anteil (2026-09-14, siehe ROADMAP.md); generisches Rate-Limiting/Body-Limits ⏸ zurückgestellt (siehe ROADMAP.md, Abschnitt "Technical debt").
- **Location:** `backend/app/main.py:39-42`, `backend/app/api/routes/admin.py:131-168` (`/admin/sync-now`, synchronous full sync), `backend/app/api/routes/students.py:301-352` (WeasyPrint PDF render per request)
- No request rate limiting, no body-size limit, no concurrency guard. A request-triggered sync and a cron-triggered sync can run concurrently (unique violations → 500s, wasted work); PDF export is CPU/RAM-heavy per request; large JSON bodies (e.g. `PUT /admin/bereiche` with thousands of entries) are unbounded. DoS of backend (and co-located Postgres) by anyone with valid credentials or the secret.
- **Remediation:** `slowapi` or reverse-proxy limits; reject oversized bodies; guard sync with an asyncio lock (skip if already running); cost-limit the PDF export.

### M-3 — Per-request user upsert + audit row
**Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)
- **Location:** `backend/app/api/deps.py:56-88`
- Every authenticated API call performs SELECT → UPDATE `nutzer` → INSERT `audit_log` (`wordpress_proxy_created/updated`) → COMMIT. Consequences: `audit_log` grows by one row per HTTP request forever (thousands/day of pure noise, eventually filling disk); every read-only GET becomes a write transaction; two concurrent first-time requests race on the unique index → uncaught `IntegrityError` → 500; GDPR-wise this is a permanent per-user access log of named teachers with no retention concept. Real admin-action audit entries drown in the noise.
- **Remediation:** Write the audit row only when the nutzer row is actually created or materially changed; define a retention/archival job; catch the unique-violation race and re-select.

### M-4 — Hardcoded weak PostgreSQL credentials
**Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)
- **Location:** `backend/docker-compose.yml:6-8` (`absenzdash:absenzdash`), mirrored in `backend/.env.example:1`
- The production compose hardcodes username-as-password; a by-the-book install keeps it. Mitigating: postgres is bound to `127.0.0.1` only. The loopback port publish itself is unnecessary (documented maintenance uses `docker exec`).
- **Remediation:** Random per-deployment password via env (`POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}`); drop the host port publish (use `expose:` if documentation is desired).

### M-5 — Entire backend directory incl. `.env` mounted writable into the container
**Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)
- **Location:** `backend/docker-compose.yml:28-30` (`- .:/app`)
- The production compose mounts the whole working tree over `/app`: the plaintext `.env` (WebUntis, SMTP, proxy secret, DB URL) sits inside the container, application code is writable from inside it, and the running production code is whatever the host checkout currently contains (uncontrolled by the image build). A development convenience used as the production configuration.
- **Remediation:** Drop the mount in production (the image already contains the code); if the email-template override must remain host-editable, mount just that file read-only; move the full-source mount to `docker-compose.override.yml` for development.

### M-6 — Backend container runs as root; no hardening
**Status:** ⏸ zurückgestellt (siehe ROADMAP.md, Abschnitt "Technical debt")
- **Location:** `backend/Dockerfile` (no `USER`; installs `requirements-dev.txt` into the prod image), `backend/docker-compose.yml` (no `user:`, `security_opt`, `cap_drop`, `read_only`, resource limits)
- Root in the container plus the writable source mount (M-5) makes code tampering and lateral movement easier after a compromise; dev packages enlarge the attack surface; missing limits let a runaway sync/PDF job starve the host.
- **Remediation:** Non-root `USER` in the Dockerfile; `security_opt: ["no-new-privileges:true"]`, `cap_drop: ["ALL"]`, `read_only: true` (after M-5) with tmpfs for `/tmp`; resource limits; prod-only requirements in the image.

### M-7 — Raw non-JSON backend responses echoed into the WP origin without hardening headers
**Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)
- **Location:** `wordpress-plugin/absenzdash/includes/class-proxy.php:95-113`
- If the backend response is not `application/json`, the plugin echoes the body verbatim with the backend's Content-Type — no `X-Content-Type-Options: nosniff`, no `Content-Disposition`, no CSP. Any current or future backend endpoint returning HTML/SVG/XML with user-influenced data becomes XSS **in the WordPress origin** (session riding via WP nonces; auth cookies are HttpOnly). **Cross-verified:** the only current non-JSON endpoint is the PDF export (Jinja2 `autoescape=True`, ASCII-sanitized filename — safe), so this is a hardening gap for future endpoints plus a MIME-sniffing concern, not a live XSS today.
- **Remediation:** Allowlist passthrough types (e.g. `application/pdf` only) with forced `Content-Disposition: attachment`; always send `X-Content-Type-Options: nosniff`; reject or JSON-wrap anything else.

---

## 6. Low findings

### WordPress plugin

**L-1 — `pfad` parameter pollution** — `includes/class-proxy.php:40`: `WP_REST_Request::get_param()` merges JSON→POST→GET→URL, so a body/query `pfad` key overrides the URL path actually proxied (`PUT /api/students/1` with `{"pfad":"admin/threshold-rules"}` proxies to the latter). No privilege escalation (backend enforces roles — verified), but breaks log/WAF path semantics and would subvert any future webserver-level path allowlisting. **Fix:** read the path from `$request->get_url_params()` only; reject requests carrying a body/query `pfad` key. **Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)

**L-2 — Internal backend host/port leaked in 502s** — `includes/class-proxy.php:87-89`: raw cURL error messages ("Failed to connect to absenzdash-backend port 8000") returned to any authenticated user. Discloses internal infrastructure details of the deliberately firewalled system. **Fix:** generic client message; `error_log()` the detail server-side. **Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)

**L-3 — Shared secret in `wp_options`, rendered as plaintext input** — `includes/class-optionen.php:24-27, 107-108`: the skeleton key (H-1) sits plaintext in the DB and is re-rendered into the settings page HTML for every `manage_options` visit (shoulder-surfing, screen shares, malicious wp-admin JS). Any DB read (other plugin's SQLi, leaked backup) yields full impersonation. **Fix:** prefer a `wp-config.php` constant with the option as fallback; render `type="password"` or write-only; document rotation. (Storage in `wp_options` is normal WP practice; the cleartext re-display is the avoidable part.) **Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)

**L-4 — SSRF/exfil surface via `backend_url`** — `includes/class-optionen.php:80`, `class-proxy.php:53-85`: the backend URL is admin-configurable with only `esc_url_raw()` sanitization (broad scheme whitelist, no host pinning); every proxied request carries the secret and caller identity there. Requires `manage_options` (admin takeover → silent exfil channel for the secret + student data). **Fix:** restrict scheme to `https?`; support a `wp-config.php` constant that takes precedence over the DB option; optionally pin the host. **Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)

### Backend

**L-5 — FastAPI docs exposed unauthenticated** — `backend/app/main.py:39`: `/docs`, `/redoc`, `/openapi.json` serve the full schema (routes, parameter and header names incl. `X-WordPress-Secret`) without the secret. Accelerates reconnaissance for anyone reaching the port. **Fix:** `FastAPI(..., docs_url=None, redoc_url=None, openapi_url=None)` in production. **Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)

**L-6 — Malformed ASV CSV aborts the entire sync** — `backend/app/services/asv_csv_import.py:31,48-54`, `sync_orchestrator.py:130,154-164`: a renamed column (`KeyError`), malformed date (`ValueError`) or Latin-1 encoding (`UnicodeDecodeError`) is not caught by the retry logic (only `WebUntisError`/`OSError` are), so one bad export silently stops **all** sync (absences, class register, escalations) until manual intervention. No size guard; over-long names hit `String(100)` → truncation error → same abort (the fehlzeit sync has a 500-char guard; the CSV import has none). **Fix:** validate the header row up front, skip+count+log malformed rows, cap file size, catch decode errors with a clear message. **Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)

**L-7 — Uncaught-exception 500s; admin endpoints echo internal error text** — `deps.py:53` (`int(X-WordPress-WebUntis-Code)` on non-numeric → 500), `deps.py:47` (non-ASCII secret in env → `TypeError` → 500 on every request), `admin.py:108-112,131-156` (only `WebUntisError`/`OSError` caught; `httpx.HTTPStatusError`/`TransportError` propagate), `admin.py:112,156,196` (exception text — can include internal WebUntis/SMTP host details — returned to schulleitung clients), `webuntis_fehlzeit_sync.py:216,221` / `webuntis_klassenbuch_sync.py:38,59` (missing keys in malformed WebUntis rows → `KeyError` → sync abort). Stack traces are **not** leaked (no debug mode — positive). **Fix:** catch `ValueError` around `int()` (→ 400), validate secret ASCII-ness at startup, catch `httpx.HTTPError`, return sanitized 502 messages, parse WebUntis rows defensively. **Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md) — nur der L-7-Teilfix aus Plan 15 (`int()`-Validierung in `deps.py`, sanitized 502 in `admin.py`/`mailer.py`-Pfaden); die defensive Behandlung malformter WebUntis-Zeilen in `webuntis_fehlzeit_sync.py`/`webuntis_klassenbuch_sync.py` war nicht Teil des Scopes.

**L-8 — Email pipeline weaknesses** — `backend/app/services/mailer.py:17-29`: header injection is **not exploitable** (CPython `EmailMessage` rejects CR/LF in header values — empirically verified on 3.12.3; image runs 3.11, same behavior). Residual: a student name containing `\n` (possible via quoted CSV field or WebUntis freetext) silently disables that notification (caught as generic failure); `/admin/test-email` lets the `ValueError` escape as 500; addresses never validated (`str`, not `EmailStr`) so garbage fails at SMTP time; all recipients are joined into one visible `To:` header (mutual PII exposure between notified teachers). **Fix:** `EmailStr` validation on intake, strip CR/LF from template values, catch `ValueError` in test-email, consider BCC/individual mails. **Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)

### Frontend

**L-9 — No session-expiry handling; stale data stays visible** — `frontend/src/api/client.ts:24-26`: all non-2xx become a generic `ApiError`; 401/403 (expired WP session/nonce — WP nonces live 12–24h) never clear the React Query caches (up to 5 min staleTime, `Infinity` for admin catalogs). On a shared computer, previously loaded student data remains on screen after the underlying session died. **Fix:** detect 401/403 in the client, `queryClient.clear()`, redirect to WP login with an explicit "Sitzung abgelaufen" state. **Status:** — nicht Teil dieser Remediation (siehe ROADMAP.md, Abschnitt "Technical debt")

**L-10 — Unvalidated `sort_by`/`offset` URL params** — `frontend/src/pages/StudentList/StudentList.tsx:41,45`: cast-only (`as StudentSortField`, `Number(...)` can be `NaN`) and forwarded. No injection sink client-side (`URLSearchParams` encodes) and the backend whitelist is **verified present** (`student_query.py:29,53-54`, `Literal` sort direction) — hygiene issue only. **Fix:** client-side whitelist + `Number.isFinite` guards. **Status:** — nicht Teil dieser Remediation (siehe ROADMAP.md, Abschnitt "Technical debt")

### Config / operations

**L-11 — No restart policies, no backend healthcheck** — `backend/docker-compose.yml`: after a daemon/host reboot or uvicorn crash the service stays down silently; for a tool sending time-sensitive absence escalations, unnoticed outage is a real operational-security issue. The app already exposes `GET /health`. **Fix:** `restart: unless-stopped` on both services + a backend healthcheck (`python -c "import urllib.request;…"`). **Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)

**L-12 — Unpinned images and dependency ranges** — mutable base tags (`postgres:15-alpine`, `python:3.11-slim`, `node:18-slim`), Python range pins without a lock file, and `npm install` instead of `npm ci` in CI (`.gitlab-ci.yml:54`) despite a committed lockfile. Two builds of the same commit can differ; complicates rollback and vulnerability attribution. **Fix:** digest pins, `pip-compile`-generated locked requirements, `npm ci`. **Status:** ⏸ zurückgestellt (siehe ROADMAP.md, Abschnitt "Technical debt")

**L-13 — Network hardening entirely undocumented** — `docs/`: no document mentions the two-firewall architecture, allowed source IPs, interface binding, TLS, or secret rotation; `docs/ADMIN.md:69` only states "Kein Internet-Zugriff auf das Backend". A by-the-book install yields 0.0.0.0 + HTTP + `absenzdash:absenzdash` + `changeme`. Any change of operator/host risks silently losing the compensating controls this audit's ratings assume. **Fix:** add a "Netzwerk & Absicherung" section to `docs/ADMIN.md` (firewall rules, interface binding, TLS recommendation or explicit accepted-risk statement, secret generation/rotation, DB credential guidance). **Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md)

---

## 7. Informational findings

- **I-1 (plugin):** Every WP account with `manage_options` is implicitly granted the `schulleitung` backend role for `/admin/*` paths (`class-proxy.php:42-45`) — an intentional anti-lockout mechanism. Consequence: external IT/webmaster WP accounts automatically get full access to minors' data without an explicit AbsenzDash role assignment. Confirm the WP-admin group equals the intended population and document this prominently. **Status:** — nicht Teil dieser Remediation
- **I-2 (plugin):** `ABSENZDASH_VITE_DEV_SERVER` (`class-shortcode.php:50-59`) loads the SPA from an arbitrary origin if ever left defined in production (supply-chain XSS). Ensure unset in prod; optionally gate behind `WP_ENVIRONMENT_TYPE === 'development'`. **Status:** — nicht Teil dieser Remediation
- **I-3 (frontend):** Client-side role gating (`RequireSchulleitung`, admin UI hiding) is UX-only — acceptable, and backend enforcement is **verified** (see §8). **Status:** — nicht Teil dieser Remediation
- **I-4 (frontend):** No runtime validation of API responses (`as T` casts, `client.ts:27`) — worst case is client-side render exceptions, not code execution (React escapes). Optional: zod validation of critical payloads. **Status:** — nicht Teil dieser Remediation
- **I-5 (frontend):** PDF filename taken from the backend `Content-Disposition` header (`client.ts:67-85`) — browsers sanitize `download` attributes and the backend strictly ASCII-sanitizes the filename; minimal risk. **Status:** — nicht Teil dieser Remediation
- **I-6 (deps):** Frontend deps are reasonably current at face value (react 18.3.1, react-router 6.30.4, vite 5.4.21, recharts 2.15.4; lockfile committed; no axios). Backend uses open ranges without a lock file — jinja2/starlette CVE exposure depends on build date (autoescape is on and no sandbox is used, limiting jinja2 impact). **Needs confirmation on the deployed artifacts:** `npm audit --omit=dev`, `pip-audit`, `pip freeze` in the running image. **Status:** — nicht Teil dieser Remediation
- **I-7 (backend/GDPR):** The audit trail is a plain mutable table (no tamper evidence) and there is no retention/erasure concept for audit logs, notification history or student data (right to erasure, school-year rollover). Compliance gap, not an exploit. Define retention periods and an erasure/anonymization procedure. **Status:** — nicht Teil dieser Remediation
- **I-8 (backend):** Cron syntax is validated but `* * * * *` is accepted (`sync_settings_service.py:39-56`) — a schulleitung user can self-DoS via overlapping ~2h sync tasks. Enforce a minimum interval; the M-2 sync mutex also covers this. **Status:** ✅ erledigt (2026-09-14, siehe ROADMAP.md) — durch den Sync-Mutex abgedeckt (die Minimum-Intervall-Validierung selbst wurde nicht ergänzt)
- **I-9 (config):** `.gitlab-ci.yml` contains **test jobs only** — no build/deploy steps, no real secrets (all test dummies). Deployment is manual (checkout + `npm run build` + volume mount) — an integrity/traceability gap rather than a vulnerability. Optional: CI build job producing a versioned plugin zip. **Status:** ⏸ zurückgestellt (siehe ROADMAP.md, Abschnitt "Technical debt")
- **I-10 (backend):** `GET /students/{id}` exposes `benachrichtigung.empfaenger` (internal user IDs + roles) to any scoped teacher — low sensitivity, worth knowing. **Status:** — nicht Teil dieser Remediation

---

## 8. Cross-component verification results

Each component audit flagged assumptions that another component's audit then verified:

| Assumption flagged | Result |
|---|---|
| Backend rejects wrong/missing secret fail-closed, timing-safe | ✅ Confirmed — `hmac.compare_digest` before any other header validation (`deps.py:47`) |
| Backend enforces `schulleitung`-only on all `/admin/*` regardless of path spelling | ✅ Confirmed — router-level `require_schulleitung` (`admin.py:42`) |
| Per-student scoping for teachers; no existence oracle | ✅ Confirmed — `get_scoped_schueler` returns 404 for both missing and out-of-scope; verified across list, detail, measures, exemptions, PDF export, dashboard |
| `sort_by`/`sort_dir` whitelisted server-side | ✅ Confirmed (`student_query.py:29,53-54`, `Literal`) |
| WP REST proxy requires login + valid cookie nonce + assigned role | ✅ Confirmed (`class-proxy.php:26,47-49` + WP core `rest_cookie_check_errors`) |
| Only non-JSON backend endpoint is the PDF export; template-injection safe | ✅ Confirmed (Jinja2 `autoescape=True`, no `\| safe`, ASCII-sanitized filename) |
| Email header injection via CR/LF in names | ✅ Not exploitable — CPython blocks it (empirically verified); residual issues tracked as L-8 |
| No secrets committed to the repo | ✅ Confirmed — git history path-filter + repo-wide pattern search; only placeholders exist |

## 9. Positive observations

- **Plugin:** identity headers are built strictly server-side from `wp_get_current_user()`/user meta — no client-supplied headers are forwarded, so roles cannot be spoofed from the browser. Consistent `esc_*` escaping; JSON-safe `wp_localize_script`; strict allowlist/`ctype_digit` validation of role/WebUntis-code inputs; `check_admin_referer` + capability checks on state-changing actions; `wp_safe_redirect` throughout; no `$wpdb`, `unserialize`, `exec`, or user-controlled file access; ABSPATH guards everywhere; no secret exposed to the browser.
- **Frontend:** zero XSS sinks (no `dangerouslySetInnerHTML`/`innerHTML`/`eval`/`document.write` — WebUntis freetext like `grund_text`/`eintrag.text` is rendered only through React escaping); no tokens in `localStorage`/`sessionStorage` (WP cookie + `X-WP-Nonce`); same-origin `fetch` with `credentials: "same-origin"`; all query strings via `URLSearchParams`; no secrets in `VITE_*`; no sourcemaps in the build.
- **Backend:** complete authorization coverage with 404-no-oracle scoping; 100% SQLAlchemy expression API (no raw SQL anywhere); no CORS middleware (correct for the proxy model); secrets required from the environment with no code defaults; outbound TLS intact (WebUntis forced HTTPS with verification, SMTP STARTTLS by default); no pickle/subprocess/eval; no stack traces leaked; admin actions broadly audit-logged; `/health` discloses nothing.
- **Config:** no committed secrets (history-checked); PostgreSQL bound to loopback; the student CSV mount is read-only; postgres healthcheck + `depends_on: service_healthy` ordering; frontend lockfile committed; `.env` files properly gitignored.

## 10. Recommended remediation order

**Step 1 — configuration only, no code changes, do first:**
1. Generate a real secret (`openssl rand -hex 32`) on both sides; never ship `.env.example` values (H-3 trigger).
2. Drop or re-bind the `8000:8000` publish (H-4); verify with an external port scan.
3. Move WP↔backend traffic to a dedicated Docker network (M-1).
4. Randomize the Postgres password via env; drop the loopback port publish (M-4).
5. Remove the `.:/app` mount from production (M-5); add `restart: unless-stopped` + backend healthcheck (L-11).

**Step 2 — small code changes, high value:**
6. Startup validator rejecting empty/placeholder/short secrets (H-3 fix).
7. TLS termination for plugin→backend, or an explicit documented accepted-risk decision (H-2); consider HMAC request signing (H-1).
8. Disable `/docs`/`/openapi.json` in production (L-5); log 401s (M-1); sync mutex + rate limits (M-2, I-8).
9. Audit-write only on actual create/change (M-3).
10. Plugin hardening: `get_url_params()` for `pfad` (L-1), generic 502 message (L-2), password-type secret field + `wp-config.php` constant support (L-3, L-4), passthrough allowlist + `nosniff` (M-7).
11. Sanitized error handling in admin routes and sync (L-6, L-7); email validation + CR/LF stripping (L-8).

**Step 3 — hardening & process:**
12. Container hardening: non-root user, `cap_drop`, `read_only`, resource limits, prod-only deps (M-6); pinned images + locked requirements + `npm ci` (L-12); `pip-audit`/`npm audit` in CI (I-6).
13. Frontend session-expiry handling (L-9).
14. Docs: "Netzwerk & Absicherung" section (L-13), document the WP-admin→schulleitung override (I-1), secret rotation (H-1).
15. GDPR retention/erasure concept for audit logs, notifications and student data (I-7, M-3).

## 11. Items to verify on the live systems (not assessable from the repo)

- Actual firewall ruleset on the backend host and perimeter (the two-firewall premise) — plus an external port scan confirming port 8000 is filtered.
- `docker network inspect absenzflow-shared` — which containers are actually joined.
- `pip freeze` in the deployed backend image vs. current CVEs; `npm audit --omit=dev` on the frontend lockfile.
- Whether production deployment actually matches `backend/docker-compose.yml` as committed.
- `.env` file permissions (`chmod 600`, ownership) on both hosts; WP options table access controls.
- Whether the WP administrator group (implicit `schulleitung`, I-1) matches the intended population.

---

*Methodology note: four parallel component audits (plugin, frontend, backend, config) were synthesized into this report; all High findings and the trust-boundary mechanics were independently spot-verified against the source during synthesis. Duplicate findings across component reports were merged.*
