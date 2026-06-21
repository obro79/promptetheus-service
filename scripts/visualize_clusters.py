#!/usr/bin/env python3
"""Visualize the fix-agent's Redis vector memory as 2D clusters.

What it shows
-------------
The fix-agent stores every verified `incident -> fix` pair as an embedding in a
Redis 8 Vector Set (`ptvec:{workspace}`) via ``VADD`` and retrieves neighbours
with ``VSIM`` (HNSW KNN over cosine). That KNN graph is the "clustering" the
service does at remediation time. This script:

1. (optionally) seeds a synthetic, multi-label incident corpus into Redis using
   the repo's deterministic local embedder (no Voyage key required);
2. reads every stored embedding back out, projects it to 2D with PCA (numpy SVD);
3. queries ``VSIM`` for each point to draw the actual KNN edges the memory forms;
4. serves an interactive Plotly scatter (points coloured by failure label, edges
   = VSIM links) in the browser.

Usage
-----
    .venv/bin/python scripts/visualize_clusters.py            # seed + serve
    .venv/bin/python scripts/visualize_clusters.py --no-seed  # serve existing
    .venv/bin/python scripts/visualize_clusters.py --port 8765

This is a demo/inspection tool. It is never imported by the service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from tempfile import mkdtemp
from types import SimpleNamespace
from typing import Any

import numpy as np

# Make sibling scripts (seed.py) importable so we can reuse its real trace/event
# builders rather than reinventing the event schema.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_WORKSPACE = "cluster-demo"
DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
EMBED_DIM = 256


# --------------------------------------------------------------------------- #
# Deterministic local embedder (demo only; mirrors scripts/demo_fix_agent.py).
# Similar text -> similar vectors, so VADD/VSIM behave like a real embedder.
# --------------------------------------------------------------------------- #
def fake_embed(text: str) -> list[float]:
    vec = [0.0] * EMBED_DIM
    for token in text.lower().split():
        if len(token) <= 2:
            continue
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % EMBED_DIM] += 1.0
    return vec


# --------------------------------------------------------------------------- #
# Synthetic corpus: several failure classes, each with overlapping phrasing so
# same-label incidents land near each other in embedding space.
# --------------------------------------------------------------------------- #
_TOOLS = ["email.send", "sms.send", "slack.post", "calendar.create", "payment.charge", "drive.upload", "ticket.open"]

_CORPUS: dict[str, list[str]] = {
    "missing_capability": [
        f"agent invoked the {t} tool but no such tool was registered in the registry"
        for t in _TOOLS
    ],
    "infinite_loop": [
        f"agent repeatedly called {t} over and over without making progress toward the goal"
        for t in _TOOLS
    ],
    "hallucinated_argument": [
        f"agent passed a fabricated nonexistent identifier argument to the {t} call"
        for t in _TOOLS
    ],
    "auth_failure": [
        f"agent failed to authenticate when calling {t}, missing api key returned unauthorized 401"
        for t in _TOOLS
    ],
    "rate_limited": [
        f"agent hit the rate limit calling {t}, server returned 429 too many requests throttled"
        for t in _TOOLS
    ],
    "bad_output_schema": [
        f"agent returned malformed json from {t}, response failed schema validation parsing"
        for t in _TOOLS
    ],
}


def _seed(memory: Any, workspace: str, reset: bool) -> int:
    client = memory._redis()
    if client is None:
        raise SystemExit("ERROR: no Redis connection. Is the local container up and REDIS_URL set?")

    if reset:
        keys = list(client.smembers(f"ptfix:ids:{workspace}"))
        to_del = [f"ptfix:{workspace}:{k}" for k in keys]
        to_del += [f"ptfix:ids:{workspace}", memory._vector_key(workspace)]
        if to_del:
            client.delete(*to_del)

    count = 0
    for label, phrases in _CORPUS.items():
        for i, root_cause in enumerate(phrases):
            incident = {
                "id": f"{label}-{i:02d}",
                "label": label,
                "severity": "high",
                "confidence": 0.9,
                "workspace_id": workspace,
            }
            bundle = {
                "incident": incident,
                "root_cause": root_cause,
                "source": "cluster-viz",
                "allowed_paths": ["agents/"],
                "events": [],
            }
            fix = SimpleNamespace(
                diff=f"# fix for {label}\n",
                plan=[f"Remediate {label}"],
            )
            memory.remember_fix(incident, bundle, fix)
            count += 1
    return count


# --------------------------------------------------------------------------- #
# Trace-grounded generator: build many fake SESSIONS in the real event schema
# (via scripts/seed.py), run them through the ACTUAL analysis engine, and embed
# the resulting (label, root_cause) incidents. This is "fake data based on the
# traces the system gives" rather than a hand-written corpus.
# --------------------------------------------------------------------------- #
_PEOPLE = ["Dana", "Maya", "Liam", "Noah", "Ava", "Ethan", "Sofia", "Mia", "Leo", "Zoe"]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
_TIMES = ["8am", "9am", "10am", "11am", "1pm", "2pm", "3pm", "4pm"]
_DURATIONS = ["15", "30", "45", "60"]
_CUSTOMERS = ["Maya", "Acme Corp", "Globex", "Initech", "Umbrella", "Stark Inc", "Wayne LLC"]
_INVOICES = ["duplicate Pro", "double-charged Team", "mistaken annual", "refunded Starter"]
_FILES = [
    "payments/checkout.py", "billing/charge.py", "auth/middleware.py",
    "payments/refund.py", "core/session.py", "api/webhooks.py",
]


def _expand_goals(scenario_index: int, n: int) -> list[str]:
    """Deterministically expand one scenario into n varied, realistic goals."""

    goals: list[str] = []
    i = 0
    while len(goals) < n:
        if scenario_index == 0:  # browser booking agent
            person = _PEOPLE[i % len(_PEOPLE)]
            day = _DAYS[(i // 2) % len(_DAYS)]
            time = _TIMES[i % len(_TIMES)]
            dur = _DURATIONS[i % len(_DURATIONS)]
            goals.append(f"Book a {dur} minute AcmeMeet with {person} on {day} at {time}")
        elif scenario_index == 1:  # support refund agent
            customer = _CUSTOMERS[i % len(_CUSTOMERS)]
            inv = _INVOICES[i % len(_INVOICES)]
            goals.append(
                f"Refund the {inv} invoice for {customer} and keep the account active"
            )
        else:  # coding agent
            f = _FILES[i % len(_FILES)]
            goals.append(
                f"Patch the checkout warning regression near {f} without changing billing flow"
            )
        i += 1
    return goals


def _make_sessions(workspace: str, per_scenario: int) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    import seed  # scripts/seed.py — reuse its real event-timeline builder

    out: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for sidx, scenario in enumerate(seed.SCENARIOS):
        for gi, goal in enumerate(_expand_goals(sidx, per_scenario)):
            session_id = f"gen_{scenario.surface}_{gi:03d}"
            session = {
                "id": session_id,
                "user_goal": goal,
                "workspace_id": workspace,
                "project_id": None,
            }
            events = seed._build_events(
                session_id=session_id, goal=goal, scenario=scenario, artifacts={}
            )
            out.append((session, events))
    return out


def _seed_from_traces(memory: Any, workspace: str, per_scenario: int, reset: bool) -> tuple[int, dict[str, int]]:
    """Generate traces, run the real engine, embed each fired incident."""

    from promptetheus.server.analysis.detectors import root_cause_sentence
    from promptetheus.server.analysis.engine import analyze_session

    client = memory._redis()
    if client is None:
        raise SystemExit("ERROR: no Redis connection. Is the local container up and REDIS_URL set?")

    if reset:
        keys = list(client.smembers(f"ptfix:ids:{workspace}"))
        to_del = [f"ptfix:{workspace}:{k}" for k in keys]
        to_del += [f"ptfix:ids:{workspace}", memory._vector_key(workspace)]
        if to_del:
            client.delete(*to_del)

    count = 0
    label_counts: dict[str, int] = {}
    for session, events in _make_sessions(workspace, per_scenario):
        result = analyze_session(session, events)
        for det in result.detections:
            # Per-label root cause from the SAME engine function (faithful).
            root_cause = root_cause_sentence([det], str(session["user_goal"]))
            incident_id = f"{session['id']}:{det.label}"
            incident = {
                "id": incident_id,
                "label": det.label,
                "severity": "high" if det.confidence >= 0.9 else "medium",
                "confidence": det.confidence,
                "workspace_id": workspace,
            }
            bundle = {
                "incident": incident,
                "root_cause": root_cause,
                "user_goal": session["user_goal"],
                "source": "trace-gen",
                "allowed_paths": ["agents/"],
                "events": events,
            }
            fix = SimpleNamespace(diff=f"# fix for {det.label}\n", plan=[f"Remediate {det.label}"])
            memory.remember_fix(incident, bundle, fix)
            count += 1
            label_counts[det.label] = label_counts.get(det.label, 0) + 1
    return count, label_counts


def _load_points(memory: Any, workspace: str) -> list[dict[str, Any]]:
    client = memory._redis()
    ids = sorted(client.smembers(f"ptfix:ids:{workspace}"))
    points: list[dict[str, Any]] = []
    for fix_id in ids:
        row = memory._load_row(client, workspace, fix_id)
        if not row or not row.get("embedding"):
            continue
        points.append(
            {
                "id": str(row.get("incident_id")),
                "label": str(row.get("label")),
                "root_cause": str(row.get("root_cause") or ""),
                "embedding": [float(x) for x in row["embedding"]],
            }
        )
    return points


def _pca_2d(vectors: list[list[float]]) -> np.ndarray:
    X = np.asarray(vectors, dtype=float)
    Xc = X - X.mean(axis=0, keepdims=True)
    _, _, Vt = np.linalg.svd(Xc, full_matrices=False)
    return Xc @ Vt[:2].T


def _knn_edges(
    memory: Any, workspace: str, points: list[dict[str, Any]], k: int
) -> tuple[list[tuple[int, int, float]], int, int]:
    """Return (edges, same_label_count, cross_label_count) using live VSIM."""
    client = memory._redis()
    index = {p["id"]: i for i, p in enumerate(points)}
    seen: set[tuple[int, int]] = set()
    edges: list[tuple[int, int, float]] = []
    same = cross = 0
    for i, p in enumerate(points):
        for element, score in memory._vsim(client, workspace, p["embedding"], k + 1):
            j = index.get(str(element))
            if j is None or j == i:
                continue
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            edges.append((i, j, float(score)))
            if points[i]["label"] == points[j]["label"]:
                same += 1
            else:
                cross += 1
    return edges, same, cross


_PALETTE = [
    "#4f46e5", "#059669", "#dc2626", "#d97706",
    "#0891b2", "#db2777", "#7c3aed", "#65a30d",
]


def _build_html(points, coords, edges, stats, workspace) -> str:
    labels = sorted({p["label"] for p in points})
    color_of = {lab: _PALETTE[i % len(_PALETTE)] for i, lab in enumerate(labels)}

    traces = []

    # Edge trace (drawn first, underneath the points).
    ex: list[Any] = []
    ey: list[Any] = []
    for i, j, _score in edges:
        ex += [float(coords[i, 0]), float(coords[j, 0]), None]
        ey += [float(coords[i, 1]), float(coords[j, 1]), None]
    traces.append(
        {
            "x": ex,
            "y": ey,
            "mode": "lines",
            "type": "scattergl",
            "name": "VSIM links",
            "line": {"color": "rgba(150,150,150,0.35)", "width": 1},
            "hoverinfo": "skip",
        }
    )

    # One point trace per label so the legend toggles whole clusters.
    for lab in labels:
        idx = [i for i, p in enumerate(points) if p["label"] == lab]
        traces.append(
            {
                "x": [float(coords[i, 0]) for i in idx],
                "y": [float(coords[i, 1]) for i in idx],
                "mode": "markers",
                "type": "scattergl",
                "name": lab,
                "marker": {"size": 11, "color": color_of[lab], "line": {"color": "white", "width": 1}},
                "text": [
                    f"<b>{points[i]['id']}</b><br>{points[i]['label']}<br>"
                    f"{points[i]['root_cause'][:90]}"
                    for i in idx
                ],
                "hovertemplate": "%{text}<extra></extra>",
            }
        )

    data_json = json.dumps(traces)
    purity = stats["same"] / stats["edges"] * 100 if stats["edges"] else 0.0

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Promptetheus - Fix Memory Clusters</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
         background:#0b0f17; color:#e5e7eb; }}
  header {{ padding:18px 24px; border-bottom:1px solid #1f2937; }}
  h1 {{ font-size:18px; margin:0 0 4px; }}
  .sub {{ color:#9ca3af; font-size:13px; }}
  .stats {{ display:flex; gap:24px; padding:14px 24px; flex-wrap:wrap; }}
  .stat {{ background:#111827; border:1px solid #1f2937; border-radius:10px; padding:10px 16px; }}
  .stat .v {{ font-size:20px; font-weight:600; }}
  .stat .k {{ font-size:12px; color:#9ca3af; }}
  #plot {{ height: calc(100vh - 190px); }}
</style>
</head>
<body>
<header>
  <h1>Fix Memory Clusters &mdash; Redis Vector Set <code>ptvec:{workspace}</code></h1>
  <div class="sub">PCA projection of VADD embeddings &middot; grey edges are live VSIM (KNN) links &middot; toggle labels in the legend</div>
</header>
<div class="stats">
  <div class="stat"><div class="v">{stats['points']}</div><div class="k">incidents (vectors)</div></div>
  <div class="stat"><div class="v">{len(set(p['label'] for p in points))}</div><div class="k">failure labels</div></div>
  <div class="stat"><div class="v">{stats['edges']}</div><div class="k">VSIM edges</div></div>
  <div class="stat"><div class="v">{purity:.0f}%</div><div class="k">edge purity (same-label)</div></div>
</div>
<div id="plot"></div>
<script>
  const data = {data_json};
  const layout = {{
    paper_bgcolor:'#0b0f17', plot_bgcolor:'#0b0f17',
    font:{{color:'#e5e7eb'}},
    margin:{{l:40,r:20,t:10,b:40}},
    xaxis:{{title:'PC1', gridcolor:'#1f2937', zeroline:false}},
    yaxis:{{title:'PC2', gridcolor:'#1f2937', zeroline:false}},
    legend:{{bgcolor:'rgba(17,24,39,0.6)'}},
    hovermode:'closest'
  }};
  Plotly.newPlot('plot', data, layout, {{responsive:true, displaylogo:false}});
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL") or DEFAULT_REDIS_URL)
    parser.add_argument("--no-seed", action="store_true", help="Visualize existing data without seeding")
    parser.add_argument("--no-reset", action="store_true", help="When seeding, keep existing entries")
    parser.add_argument(
        "--source",
        choices=("traces", "corpus"),
        default="traces",
        help="traces: generate sessions and run the real analysis engine (default); "
        "corpus: a hand-written multi-label phrase set",
    )
    parser.add_argument(
        "--per-scenario",
        type=int,
        default=40,
        help="Trace mode: fake sessions generated per scenario archetype",
    )
    parser.add_argument("--knn", type=int, default=4, help="Neighbours per node for VSIM edges")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)

    # Target the (local) Redis BEFORE importing the memory module, which caches
    # its client lazily on first use.
    os.environ["REDIS_URL"] = args.redis_url
    from promptetheus.server.fix_agent import memory

    # Use the deterministic local embedder so VADD/VSIM run without a Voyage key.
    memory._embed = fake_embed  # type: ignore[assignment]

    if not args.no_seed:
        if args.source == "traces":
            n, label_counts = _seed_from_traces(
                memory, args.workspace, args.per_scenario, reset=not args.no_reset
            )
            breakdown = ", ".join(f"{k}={v}" for k, v in sorted(label_counts.items()))
            print(f"generated traces -> embedded {n} incidents into ptvec:{args.workspace}")
            print(f"  label breakdown: {breakdown}")
        else:
            n = _seed(memory, args.workspace, reset=not args.no_reset)
            print(f"seeded {n} incidents into ptvec:{args.workspace}")

    points = _load_points(memory, args.workspace)
    if not points:
        raise SystemExit(
            f"No vectors found in ptvec:{args.workspace}. Run without --no-seed to populate."
        )

    coords = _pca_2d([p["embedding"] for p in points])
    edges, same, cross = _knn_edges(memory, args.workspace, points, args.knn)
    stats = {"points": len(points), "edges": len(edges), "same": same, "cross": cross}
    print(f"loaded {len(points)} vectors | {len(edges)} VSIM edges ({same} same-label, {cross} cross-label)")

    out_dir = mkdtemp(prefix="pt_cluster_viz_")
    html_path = os.path.join(out_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(_build_html(points, coords, edges, stats, args.workspace))

    os.chdir(out_dir)
    httpd = ThreadingHTTPServer((args.host, args.port), SimpleHTTPRequestHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"\nServing cluster visualization at {url}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
