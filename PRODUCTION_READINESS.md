# Production Readiness Roadmap

Status: **not production ready**. This document tracks what stands between the
current code and a deployment that can be trusted with real links.

**Progress:** Phases 1-4 complete (21/30). Phases 5-6 open, 9 items remaining.
The service is correct, tested and hardened; what is left is running it
somewhere (Phase 5) and describing it accurately (Phase 6).

- **Baseline:** commit `7d2c0a1` — the last state before hardening began.
  `git checkout 7d2c0a1` restores it at any time. The annotated tag
  `v0.1.0-baseline` marks it; if your clone does not have the tag, recreate and
  publish it with
  `git tag -a v0.1.0-baseline 7d2c0a1 -m "Baseline before production hardening" && git push origin v0.1.0-baseline`.
- **Target tag:** `v1.0.0` — every P0 and P1 item below checked off.
- **Analysed:** 2026-09-12, against a live run of the app on Python 3.11 with
  FastAPI 0.141. Every behaviour marked *verified* was reproduced by request,
  not inferred from reading the code.

Work the phases in order. Phase 1 is a prerequisite for the rest: until the
repository stops shipping a broken virtualenv, nobody else can reliably run the
project to review the later changes.

---

## Phase 1 — Repository hygiene (P0)

Nothing here changes behaviour, and all of it blocks collaboration.

- [x] **Untrack `.venv/`.** 1,681 of the 1,691 tracked files are a committed
      virtualenv, and it does not work anywhere but the machine that made it:
      `.venv/pyvenv.cfg` declares `home = /Library/Developer/CommandLineTools`
      and `version = 3.9.6`, while `.venv/bin/python3.12` symlinks to
      `/opt/anaconda3/bin/python3.12` and `site-packages` holds 3.12 wheels.
      *Verified:* every `.venv/bin/*` entry point fails on a clean checkout.
      `git rm -r --cached .venv`
- [x] **Fix `.gitignore`.** Two entries are wrong:
      - line 3 reads `**pycache**/` (markdown mangling) and matches nothing —
        it must be `__pycache__/`
      - line 8 reads `venv/`, which never matched the actual `.venv/` directory
      Add `.env` and `*.db` is already present.
- [x] **Untrack `.env`, add `.env.example`.** The committed `.env` holds only
      localhost development values today, so nothing is currently leaked — but
      `requirements.txt` already carries `psycopg2-binary`, and the first real
      `DATABASE_URL` written to that file would be committed with it.
- [x] **Delete `package-lock.json`.** An empty stub (`"packages": {}`) with no
      Node tooling anywhere in the project.
- [x] **Rename `Execution steps /`.** The directory name carries a trailing
      space and holds a PDF; neither is scriptable. Convert the command list to
      markdown at `docs/commands.md`.
- [x] **Add a `LICENSE`.** The README invites forks and contributions, which
      nobody can legally act on without one.

**Done:** tracked files went from 1,691 to 11. Verified by cloning the branch
fresh and following `docs/commands.md` verbatim — dependencies install, the
server starts, shorten/redirect/stats all answer, and `git status` is still
clean afterwards, so the new ignore rules hold. Neither `.venv/` nor `.env`
appears in the clone.

---

## Phase 2 — Correctness (P0)

Each item below is a defect reproduced against the running service.

- [x] **Honour `DATABASE_URL`.** `main.py:23` reads the variable; `database.py:6`
      hardcodes `sqlite:///./urls.db` and ignores it. Consequence: deploying with
      a Postgres URL set silently keeps writing to a local SQLite file, so every
      link is lost on redeploy — the standard failure on Render, Fly and Heroku.
      Apply `connect_args={"check_same_thread": False}` only when the URL is
      SQLite. This is what makes `psycopg2-binary` in `requirements.txt` mean
      something.
- [x] **Reject reserved short codes.** *Verified:* `custom: "health"` and
      `custom: "docs"` both return 201 and persist, but `GET /health` and
      `GET /docs` continue to hit their own routes — the link is created, stored,
      billed to the user, and permanently dead. Reserve at minimum
      `health`, `docs`, `redoc`, `openapi.json`, `api`, `static`, and reject with
      409 at `main.py:157`.
- [x] **Validate the short-code charset.** `main.py:157-169` checks length only.
      *Verified:* `a/b` is accepted and then unreachable (`GET /a/b` → 404), and
      `<script>x` is accepted verbatim. Require `^[A-Za-z0-9_-]{3,50}$`.
- [x] **Redirect with 302, not 301.** `main.py:267` issues a permanent redirect,
      which browsers cache indefinitely: repeat visits never reach the service,
      so click counts silently undercount, and a link can never be retargeted or
      taken down once anyone has followed it. Use `302` (or `307`).
- [x] **Add the `created_at` column.** `URLStatsResponse` declares the field
      (`main.py:83`) but `models.py` has no such column, and the `hasattr` guard
      at `main.py:219` turns the gap into the string `"N/A"`. *Verified:* the
      stats endpoint returns `"created_at": "N/A"` for every link. Add
      `created_at = Column(DateTime, server_default=func.now())` and drop the
      guard.
- [x] **Handle `IntegrityError` on insert.** Both the custom-code check
      (`main.py:164`) and `generate_unique_code` (`main.py:96-105`) query and
      then insert without a transaction. Two concurrent requests for the same
      code hit the unique index and the loser gets a 500. Catch, retry once for
      generated codes, return 409 for custom ones.

**Done:** verified by replaying the Phase 3 suite over the `v0.1.0-baseline`
sources — 8 tests fail there and `tests/test_validation.py` cannot even import,
while the 10 that still pass are the round-trip basics that always worked.

Two of these fixes were changed by their own tests before landing: reserved
names containing a dot reported a charset error instead of a conflict, and
testing the Postgres branch by constructing a real engine required `psycopg2`
to be installed, which is why `engine_options()` is a pure function.

One caveat carried forward: `created_at` reaches new databases only.
`Base.metadata.create_all()` creates tables but never alters them, so an
existing deployment needs the Alembic migration in Phase 5 before it sees the
column.

---

## Phase 3 — Tests and CI (P0)

There is currently no test of any kind.

- [x] **Add `pytest` + `httpx` and a `TestClient` suite** against an in-memory
      SQLite database, covering: shorten → redirect → stats round trip; invalid
      and non-`http(s)` URLs; duplicate custom code → 409; reserved code → 409;
      bad charset → 400; unknown code → 404; click increment on redirect.
- [x] **Add a GitHub Actions workflow** running `ruff` and `pytest` on push and
      pull request.
- [x] **Pin dependencies.** `requirements.txt` uses `>=` throughout, so two
      installs a month apart produce different builds. Pin exact versions and
      keep the floors in a separate constraints file if you want Dependabot to
      manage them.

**Done:** `.github/workflows/ci.yml` lints with ruff, runs the suite on Python
3.11 and 3.12, then starts the real server and drives one shorten-and-redirect
round trip asserting a 302 — the class of breakage a test suite cannot see (a
bad uvicorn entrypoint, a missing static file). Every step was run locally
against a clean virtualenv built from the pinned requirements before it was
committed.

---

## Phase 4 — Security (P1)

- [x] **Escape frontend output.** `static/index.html:661` and `:714-727`
      interpolate the short URL and the original URL into `innerHTML` unescaped.
      `https://x.com/"><img src=x onerror=...>` passes `is_valid_url` — scheme and
      netloc are both valid — and then executes on render. Scope is self-XSS,
      since history lives in per-browser `localStorage`, but it is still an
      injection. Use `textContent` and build elements rather than string
      concatenation.
- [x] **Rate-limit `POST /api/shorten`.** Unauthenticated and unbounded; one
      script fills the database. `slowapi` is the usual answer for FastAPI.
- [x] **Block internal redirect targets.** `is_valid_url` (`main.py:107`) accepts
      any `http(s)` host, including `169.254.169.254`, `localhost` and RFC1918
      addresses. Resolve and reject private, loopback and link-local targets.
- [x] **Tighten CORS for production.** `main.py:50` already narrows to
      `FRONTEND_URL` outside development — confirm `ENVIRONMENT` is actually set
      in the deployment, or the permissive development list ships.
- [x] **Drop `allow_credentials=True`** (`main.py:51`) unless cookies are added
      later; nothing in the app authenticates today.
- [x] **Add link expiry.** An immortal, anonymous redirect service is a phishing
      asset. An `expires_at` column with a default TTL bounds the damage.

**Done:** 35 tests added, 80 in total. The XSS fix was verified in Chromium
rather than by reading the diff — with `https://example.com/"><img src=x
onerror=...>` as the target, the baseline page sets `window.__pwned` and injects
two elements into the history list, while the fixed page executes nothing and
renders the payload as text.

Two limits worth stating plainly:

- The rate limiter counts in one process. Behind N workers the effective limit
  is N times the configured number. A shared store belongs with the second
  worker, not before it.
- Target blocking resolves DNS at creation time, so a name re-pointed at an
  internal address afterwards still gets through, and DNS failures are allowed
  through by design. It stops the copy-paste cases, not a determined attacker.

`expires_at` is a second column that `create_all()` will not add to an existing
database — the same migration caveat as `created_at`.

---

## Phase 5 — Operability (P1)

- [ ] **Add a `Dockerfile`** (slim base, non-root user, `uvicorn` entrypoint) and
      a `docker-compose.yml` pairing it with Postgres for local parity.
- [ ] **Add Alembic.** `Base.metadata.create_all` (`main.py:67`) creates tables
      but never alters them, so the `created_at` column from Phase 2 will not
      appear on any existing database.
- [ ] **Serve structured logs.** `logging.basicConfig` at `main.py:29` emits
      unparseable text; JSON logs with a request id make production debugging
      possible.
- [ ] **Extend `/health` to check the database.** It currently returns `ok`
      whenever the process is alive, including when the database is unreachable
      — so a load balancer keeps routing to a broken instance.
- [ ] **Move handlers to `Depends(get_db)`.** Every endpoint opens
      `SessionLocal()` by hand in a `try/finally` (`main.py:143`, `:207`, `:253`);
      a dependency removes the repetition and guarantees cleanup.

---

## Phase 6 — Documentation (P2)

- [ ] **Correct the README API section.** It documents
      `POST /shorten?original_url=<url>`; the endpoint is `POST /api/shorten`
      with a JSON body. `GET /api/stats/{code}` is undocumented entirely.
- [ ] **Correct the setup instructions.** They say
      `pip install fastapi uvicorn sqlalchemy`, which skips `python-dotenv` and
      `pydantic` and ignores `requirements.txt`.
- [ ] **Update the structure tree** to include `.env.example`,
      `requirements.txt` and this file.
- [ ] **Document every environment variable** and its default.

---

## Deliberately out of scope

Listed so they are decisions rather than oversights: user accounts, an
analytics dashboard, QR codes, custom domains, and per-link edit or delete. All
are in the README's "Future Improvements" and none is required for a
trustworthy v1.
