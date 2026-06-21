"""CLI: replay --tree and the diff subcommand."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus import cli  # noqa: E402


def _write_session(path: Path, steps):
    lines = [json.dumps({"type": "state_change", "seq": 0, "payload": {"name": "session_start"}})]
    for i, (etype, payload) in enumerate(steps, start=1):
        lines.append(json.dumps({"type": etype, "seq": i, "payload": payload}))
    lines.append(json.dumps({"type": "session_end", "seq": len(steps) + 1, "payload": {"status": "completed"}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_replay_tree_renders(capsys, tmp_path):
    sess = tmp_path / "s.jsonl"
    _write_session(sess, [
        ("state_change", {"name": "span_start", "span_name": "outer"}),
        ("tool_call", {"tool": "search"}),
        ("state_change", {"name": "span_end"}),
    ])
    rc = cli.main(["replay", str(sess), "--tree"])
    out = capsys.readouterr().out
    assert rc == 0
    # tree mode prints something other than the flat "[seq] type" timeline
    assert out.strip() != ""


def test_diff_identical_sessions(capsys, tmp_path):
    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    steps = [("tool_call", {"tool": "search"}), ("goal_check", {"passed": True})]
    _write_session(a, steps)
    _write_session(b, list(steps))
    rc = cli.main(["diff", str(a), str(b)])
    assert rc == 0
    assert "match" in capsys.readouterr().out.lower()


def test_diff_regression_exits_nonzero(capsys, tmp_path):
    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    _write_session(a, [("goal_check", {"passed": True})])
    _write_session(b, [("goal_check", {"passed": False})])
    rc = cli.main(["diff", str(a), str(b)])
    out = capsys.readouterr().out
    assert rc == 2  # regression -> non-zero gate
    assert "REGRESSED" in out


def test_diff_missing_file(capsys, tmp_path):
    a = tmp_path / "a.jsonl"
    _write_session(a, [("tool_call", {"tool": "x"})])
    rc = cli.main(["diff", str(a), str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "could not find" in capsys.readouterr().out.lower()


def test_fingerprint_reports_failure(capsys, tmp_path):
    sess = tmp_path / "f.jsonl"
    sess.write_text(
        json.dumps({"type": "error", "seq": 1, "payload": {"message": "ValueError: bad"}})
        + "\n"
        + json.dumps({"type": "session_end", "seq": 2, "payload": {"status": "failed"}})
        + "\n",
        encoding="utf-8",
    )
    rc = cli.main(["fingerprint", str(sess)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "error" in out.lower()


def test_fingerprint_clean_session(capsys, tmp_path):
    sess = tmp_path / "c.jsonl"
    _write_session(sess, [("goal_check", {"passed": True})])
    rc = cli.main(["fingerprint", str(sess)])
    assert rc == 0
    assert "no failure" in capsys.readouterr().out.lower()
