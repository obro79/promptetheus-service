# Server Internal Contract (State-0 in-process spine)

This is the **frozen seam** for the Analysis & Incident Spine build. Every module
implements against the signatures here. Do not change these signatures; if a real
need arises, it is a contract change that updates this file in the same commit.

The load-bearing layer is already written and MUST NOT be modified by implementers:
`models.py`, `store.py` (`Store` protocol + `InMemoryStore`), `auth.py`
(`AuthRegistry`, `AuthContext`, `hash_api_key`).

Source of truth for behavior: `docs/architecture/technical-architecture.md`
("API Contract", "Detector Semantics", "GitHub + Fix-Agent Security Contract",
"Storage Contract"). The 14 endpoints are locked.

---

## 1. Detectors — `server/analysis/detectors.py`

Pure functions over a session's ordered events + the session's `user_goal`.
Deterministic: same events in → same output. No I/O, no store access.

```python
from promptetheus.server.models import Detection

def detect_browser_goal_mismatch(events: list[dict], user_goal: str) -> Detection | None: ...
def detect_ignored_ui_warning(events: list[dict], user_goal: str) -> Detection | None: ...
def detect_false_success_claim(
    events: list[dict], user_goal: str, prior: dict[str, Detection]
) -> Detection | None: ...
def detect_forbidden_action(events: list[dict], user_goal: str) -> Detection | None: ...

# Ordered registry the engine iterates. false_success_claim depends on prior
# detections, so it runs last and receives {label: Detection} of what fired.
ALL_DETECTORS = [...]  # exposed for tests

def root_cause_sentence(detections: list[Detection], user_goal: str) -> str: ...
```

`events` are the stored event dicts (envelope + `payload`), already sorted by
`seq`. Each event: `{"type", "session_id", "timestamp", "seq", "idempotency_key",
"payload": {...}, "metadata"?}`.

Implement the rules, confidences, and evidence EXACTLY as specified in the
"Detector Semantics" section of technical-architecture.md:

- `browser_goal_mismatch`: fire on `goal_check.passed == False` (conf 0.9); else
  derive from final `dom_snapshot.selected_values` vs goal constraints (conf 0.7);
  else goal-text vs final `agent_message` disagreement (conf 0.5). Evidence: the
  failed `goal_check` seq or final `dom_snapshot` seq, plus the earliest
  `browser_action` that set the contradicting value (the critical step).
- `ignored_ui_warning`: fire when a `dom_snapshot.warnings` is non-empty and a
  later progressing `browser_action` (click/fill/submit) occurs with no
  intervening action addressing the warned field. Conf 0.9 if the warning
  persists into the final snapshot and the last progressing action is a
  submit/confirm; 0.6 if transient/positional. Evidence: warning snapshot seq +
  first progressing `browser_action` seq after it.
- `false_success_claim`: fire when a terminal `agent_message` asserts success
  (phrase set: "done", "booked", "completed", "successfully"; or
  `metadata.status == "success"`) AND (`browser_goal_mismatch` fired OR terminal
  `goal_check.passed` is false). Conf 0.95 when paired with a ≥0.7 goal mismatch;
  0.6 when the mismatch is itself 0.5. Evidence: claiming `agent_message` seq +
  the mismatch evidence refs.
- `forbidden_action`: parse `user_goal` for a stop-boundary ("stop at", "don't",
  "do not", "without"); fire when a `browser_action` crosses it (selector/target
  match conf 0.9, visible-text heuristic conf 0.6). Evidence: crossing
  `browser_action` seq + boundary-reaching `dom_snapshot` seq.

`critical_step_seq` per detection = lowest seq among evidence whose event *caused*
the failure (for value mismatches, the `browser_action` that set the wrong value,
not the snapshot that observed it).

`root_cause_sentence`: template-generated, one sentence naming the critical step,
the contradicted goal constraint, and the missing safeguard. No LLM in State 0.

## 2. Engine — `server/analysis/engine.py`

```python
from promptetheus.server.models import AnalysisResult
from promptetheus.server.store import Store

def analyze_session(session: dict, events: list[dict]) -> AnalysisResult:
    """Run all detectors; aggregate into AnalysisResult.

    - session-level critical_step_seq = min critical_step_seq across fired
      detections (None if nothing fired).
    - confidence = max detection confidence (0.0 if none).
    - root_cause = root_cause_sentence(detections, user_goal) when something fired,
      else None.
    """

def assemble_incidents(store: Store, session: dict, result: AnalysisResult) -> list[dict]:
    """Cluster the session's fired labels into incident rows and upsert them.

    Incident identity is per (workspace_id, primary label): id =
    f"incident_{workspace_id}_{label}". A session contributes to one incident per
    fired label (use the highest-confidence label as the incident's primary
    `label`; create one incident per fired label is acceptable — but keep it
    deterministic). Each incident row carries: id, workspace_id, project_id,
    label, severity ("high" if confidence>=0.9 else "medium"), status "new"
    (preserved if already set), representative_session_id, owner_id (None),
    session_ids (deduped list), critical_step_seq, confidence (max seen).
    Returns the upserted incident rows.
    """
```

Engine writes analysis + incidents only through the `Store`. It performs no HTTP.

## 3. Fix-agent — `server/fix_agent/runner.py`

```python
from promptetheus.server.models import FixAgentResult

def build_incident_bundle(store, incident: dict) -> dict:
    """Assemble a REDACTED bundle for dispatch: incident summary, representative
    session user_goal, ordered events around the critical step, analysis root
    cause, and connected-repo allowed_paths. Redact secrets/cookies/auth headers
    /obvious PII from event payloads before returning."""

class FixAgentRunner:
    def __init__(self, allowed_paths: list[str] | None = None): ...
    def run(self, incident_bundle: dict) -> FixAgentResult:
        """Deterministic fallback fix. Returns plan (list of steps) + a unified
        diff string that adds a post-action goal-verification guard targeting a
        path inside allowed_paths (default ['agents/']). metadata includes
        {"fallback": True, "branch": f"promptetheus/{incident_id}-{short_label}",
        "allowed_paths": [...]}. Reject (raise ValueError) if a generated change
        would touch a path outside allowed_paths."""
```

The diff is a real unified-diff string (parseable header `--- a/...`/`+++ b/...`
with `@@` hunks). It does not need to apply to a real repo in State 0, but it must
be well-formed and confined to allowed paths.

## 4. Regression — `server/regression/runner.py`

```python
def run_regression(store, incident: dict, *, pr_url: str | None = None) -> dict:
    """Produce a regression_run row with before/after pass/fail counts. State-0
    deterministic fallback: before = {pass:0, fail:N}, after = {pass:N, fail:0}
    where N = len(incident.session_ids) (min 1). Row fields: id, workspace_id,
    project_id, incident_id, pr_url, before_pass, before_fail, after_pass,
    after_fail, user_confirm_count(0), raw_results_json, fallback(True). Persist
    via store.add_regression_run and return the stored row."""
```

## 5. App — `server/app.py` (rewrite)

`create_app(store: Store | None = None, auth: AuthRegistry | None = None) -> FastAPI`.
Defaults construct `InMemoryStore()` and `AuthRegistry()`. Keep `GET /health` →
`{"status": "ok"}`. Expose the store/auth on `app.state` for tests/seed.

Resolve auth on every `/api/*` and `/artifacts/*` route via
`auth.resolve(request.headers.get("authorization"))`. Map:

| Condition | Status |
| --- | --- |
| missing/invalid credential | 401 |
| principal's workspace != target row's workspace | 403 |
| `PUT /api/traces/{id}/analysis` by non-server principal | 403 |
| trace/artifact/incident not found in workspace | 404 |
| malformed JSON body | 400 |
| event fails `schema.validate_event` | (per-event) 422 reason in `rejected[]` |
| `seq` conflict on append | (per-event) reason in `rejected[]` |
| artifact too large (> size limit) | 413 |
| unsupported artifact type | 415 |

### Endpoint bodies (locked)

- `POST /api/traces` (api_key|console) → create `trace_session` stamped with the
  caller's workspace_id/project_id. Body: `{user_goal, agent?, environment?,
  metadata?, tags?, id?}`. Response: `{"trace": {...session row...}}`, 201.
- `POST /api/traces/{id}/events` (api_key|console) → per-event accept/reject.
  Body: `{"events": [event, ...]}` (or a bare event). Response **200**:
  `{"accepted": n, "rejected": [{"index", "idempotency_key", "reason"}]}`.
  A bad/duplicate/conflicting event never drops valid events in the same batch.
  Each accepted event is also published to the SSE hub (see §6).
- `POST /api/traces/{id}/artifacts` (api_key|console) → store artifact row with
  `storage_path = artifacts/{workspace_id}/{session_id}/{artifact_id}/{filename}`.
  Enforce size limit (`PROMPTETHEUS_MAX_ARTIFACT_BYTES`, default 50 MiB → 413) and
  content-type allowlist (`video/webm`, `image/png`, `image/jpeg` → else 415).
  Response `{"artifact": {...}}`, 201.
- `GET /api/sessions` (console) → `{"sessions": [...]}` filtered to workspace.
- `GET /api/traces/{id}/events` (console) → `{"events": [...ordered...]}`.
- `GET /api/traces/{id}/analysis` (console) → `{"analysis": {...} | null}`.
- `PUT /api/traces/{id}/analysis` (**server-only**) → store analysis row,
  `{"analysis": {...}}`.
- `GET /api/stream` (console) → SSE (`text/event-stream`); see §6. Query:
  `project_id?`, `session_id?`, `after_seq?`.
- `GET /artifacts/{artifact_id}` (console) → `{"artifact_id", "signed_url",
  "expires_in"}` where `signed_url` is a synthetic short-lived URL (no real
  bucket in State 0). 404 if not in workspace.
- `POST /api/traces/{id}/analyze` (console) → run engine, store analysis, assemble
  incidents. Response `{"analysis": {...}, "incidents": [...]}`. **Back-compat:**
  the `analysis` object MUST include `trace_id`, `labels`, `critical_step_seq`,
  `confidence` (plus the richer `detections`/`root_cause`).
- `GET /api/incidents` (console) → `{"incidents": [...]}` workspace-scoped.
- `PATCH /api/incidents/{id}` (console) → update `status` (must be one of
  `models.INCIDENT_STATUSES`, else 400) and/or `owner_id`. `{"incident": {...}}`.
- `POST /api/incidents/{id}/fix-agent` (console) → build bundle, run
  `FixAgentRunner`, write an `audit_log` row, attach result to incident.
  `{"incident_id", "plan": [...], "diff": "...", "metadata": {...}}`.
- `POST /api/incidents/{id}/regression-runs` (console) → `run_regression`, write
  audit row. `{"regression_run": {...}}`.

Audit: fix-agent dispatch, PR/fallback toggle, and regression runs each write an
`audit_log` row via `store.add_audit`.

## 6. SSE hub — `server/stream.py` (new, owned by the app implementer)

A tiny in-process pub/sub: `StreamHub` with `async subscribe(workspace_id,
filters) -> AsyncIterator[str]` and `publish(workspace_id, event)`. `GET
/api/stream` backfills from `store.get_events(session_id)` by `after_seq` before
streaming live, sends heartbeats, and filters by workspace/project/session. Keep
it single-instance (State-0 constraint). The app holds one `StreamHub` on
`app.state`.

## 7. CLI + seed (separate owner)

- `cli.py`: `promptetheus dev` boots uvicorn on `:4318` against `create_app()`
  when uvicorn is importable; otherwise prints guidance (never crash). Keep
  `version` subcommand.
- `scripts/seed.py`: seed a workspace/project + several AcmeMeet failing-booking
  sessions THROUGH the API (use `fastapi.testclient.TestClient(create_app())` or
  an HTTP client against a running server). Each session: user_message → browser
  actions → dom_snapshots (with a warning) → an `agent_message` false-success
  claim → `goal_check(passed=False)` → `session_end`. Then call `/analyze` so
  incidents form. Print a summary. Must be runnable as `python scripts/seed.py`.

## Auth quick reference (for tests/seed)

- API-key principal: `Authorization: Bearer pt_dev_key` → ws_dev / proj_dev
- Console principal: `Authorization: Bearer pt_console_token` → ws_dev
- Server principal: `Authorization: Bearer pt_server_token`

## Test layout (`tests/`)

- `tests/analysis/test_detectors.py` — each label's firing rule + ≥1 negative case
  per detector (P26.8), confidence values, evidence/critical-step.
- `tests/analysis/test_engine.py` — aggregation + incident clustering.
- `tests/server/test_app_contract.py` — REWRITE: all 14 routes exist; real bodies;
  auth 401/403; 404; per-event accept/reject + seq conflict; artifact 413/415;
  analyze→incident; fix-agent diff; regression before/after. Health unchanged.
- `tests/server/test_auth.py` — resolve api_key/console/server/invalid.
- `tests/fix_agent/test_runner.py` — fallback diff well-formed + path allowlist
  rejection + bundle redaction.
- `tests/regression/test_runner.py` — before/after row shape + persistence.
- `tests/server/test_seed.py` — seed runs and produces ≥1 incident.

Existing passing tests in `tests/schema`, `tests/server`, `tests/analysis`,
`tests/fix_agent`, `tests/regression`, `tests/db`, and `tests/mcp` MUST stay
green.
```
