from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus import cli  # noqa: E402
from promptetheus import config as config_module  # noqa: E402


def _isolate_config(monkeypatch, tmp_path):
    """Point load_config at a nonexistent file and clear env so the developer's
    real ~/.promptetheus/config.toml never leaks into a CLI test."""
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "no-config.toml")
    for var in (
        "PROMPTETHEUS_API_URL",
        "PROMPTETHEUS_API_KEY",
        "PROMPTETHEUS_PROJECT",
        "PROMPTETHEUS_ENVIRONMENT",
        "PROMPTETHEUS_SAMPLE_RATE",
        "PROMPTETHEUS_REDACT",
    ):
        monkeypatch.delenv(var, raising=False)


def test_version(capsys):
    from promptetheus import __version__

    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_spool_list_absent_dir(capsys, tmp_path):
    rc = cli.main(["spool", "list", "--dir", str(tmp_path / "nope")])
    assert rc == 0
    assert "nothing pending" in capsys.readouterr().out.lower()


def test_spool_list_counts_files(capsys, tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "sess_a.jsonl").write_text('{"seq":1}\n{"seq":2}\n', encoding="utf-8")
    dead = spool / "dead-letter"
    dead.mkdir()
    (dead / "sess_b.jsonl").write_text('{"seq":1}\n', encoding="utf-8")

    rc = cli.main(["spool", "list", "--dir", str(spool)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2 event(s)" in out  # 2 pending
    assert "1 event(s)" in out  # 1 dead-lettered


def test_spool_purge_keeps_dead_letter_by_default(capsys, tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "sess_a.jsonl").write_text('{"seq":1}\n', encoding="utf-8")
    dead = spool / "dead-letter"
    dead.mkdir()
    (dead / "sess_b.jsonl").write_text('{"seq":1}\n', encoding="utf-8")

    assert cli.main(["spool", "purge", "--dir", str(spool)]) == 0
    assert not (spool / "sess_a.jsonl").exists()
    assert (dead / "sess_b.jsonl").exists()  # dead-letter retained


def test_spool_purge_dead_letter_flag(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    dead = spool / "dead-letter"
    dead.mkdir()
    (dead / "sess_b.jsonl").write_text('{"seq":1}\n', encoding="utf-8")
    assert cli.main(["spool", "purge", "--dir", str(spool), "--dead-letter"]) == 0
    assert not (dead / "sess_b.jsonl").exists()


def test_doctor_no_api_key_returns_nonzero(capsys, monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    rc = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no api_key" in out.lower()


def test_doctor_never_leaks_api_key(capsys, monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("PROMPTETHEUS_API_URL", "http://127.0.0.1:9")  # unreachable
    monkeypatch.setenv("PROMPTETHEUS_API_KEY", "super-secret-key-value")

    rc = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "super-secret-key-value" not in out  # never printed
    assert "api_key      : set" in out
    assert "UNREACHABLE" in out  # graceful, no traceback
    assert rc == 1


def test_init_requires_console_token(capsys, monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.delenv("PROMPTETHEUS_CONSOLE_TOKEN", raising=False)

    rc = cli.main(["init"])
    out = capsys.readouterr().out

    assert rc == 2
    assert "no console token" in out.lower()
    assert "pt_console_token" in out


def test_init_bootstraps_project_and_writes_env(capsys, monkeypatch, tmp_path):
    calls = []

    def fake_post_json(url, payload, *, bearer_token, timeout=30.0):
        calls.append((url, payload, bearer_token, timeout))
        return 201, {
            "workspace": {"id": "w1", "name": "Hackathon"},
            "project": {"id": "p1", "name": "Browser Agent"},
            "api_key": "pt_live_test_key",
        }

    monkeypatch.setattr(cli, "_post_json", fake_post_json)
    env_file = tmp_path / ".env"

    rc = cli.main(
        [
            "init",
            "--api-url",
            "http://127.0.0.1:4318",
            "--console-token",
            "console-token",
            "--workspace-name",
            "Hackathon",
            "--project-name",
            "Browser Agent",
            "--agent-name",
            "browser",
            "--write-env",
            str(env_file),
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert calls == [
        (
            "http://127.0.0.1:4318/api/onboarding/bootstrap",
            {
                "workspace_name": "Hackathon",
                "project_name": "Browser Agent",
                "agent_name": "browser",
            },
            "console-token",
            30.0,
        )
    ]
    assert "pt_live_test_key" in out
    assert "PROMPTETHEUS_API_KEY='pt_live_test_key'" in env_file.read_text()
    assert "PROMPTETHEUS_API_URL='http://127.0.0.1:4318'" in env_file.read_text()


def test_init_writes_sdk_config(capsys, monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)

    def fake_post_json(url, payload, *, bearer_token, timeout=30.0):
        return 201, {
            "workspace": {"name": "Team"},
            "project": {"name": "Project"},
            "api_key": "pt_live_config_key",
        }

    monkeypatch.setattr(cli, "_post_json", fake_post_json)
    config_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)

    rc = cli.main(["init", "--console-token", "console-token", "--write-config"])
    out = capsys.readouterr().out
    text = config_path.read_text(encoding="utf-8")

    assert rc == 0
    assert "Wrote SDK config" in out
    assert 'api_key = "pt_live_config_key"' in text
    assert 'api_url = "https://api-production-8a8a.up.railway.app"' in text


def test_init_existing_project_without_raw_key_is_nonzero(capsys, monkeypatch):
    def fake_post_json(url, payload, *, bearer_token, timeout=30.0):
        return 200, {
            "workspace": {"name": "Team"},
            "project": {"name": "Project"},
            "api_key": None,
            "api_key_preview": "pt_live_...abcd",
        }

    monkeypatch.setattr(cli, "_post_json", fake_post_json)

    rc = cli.main(["init", "--console-token", "console-token"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "raw API key is not recoverable" in out
    assert "pt_live_...abcd" in out


def test_mcp_install_codex_prints_hosted_stdio_bridge(capsys):
    rc = cli.main(
        [
            "mcp",
            "install",
            "--client",
            "codex",
            "--workspace",
            "team alpha",
            "--project-ref",
            "abc123",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "https://mcp.promptetheus.dev/promptetheus/team%20alpha/abc123" in out
    assert '[mcp_servers."promptetheus"]' in out
    assert 'args = ["-y", "mcp-remote"' in out
    assert "read-only Promptetheus evidence scoped to this project" in out


def test_mcp_install_cursor_prints_workspace_json(capsys):
    rc = cli.main(
        [
            "mcp",
            "install",
            "--client",
            "cursor",
            "--workspace",
            "team",
            "--project-ref",
            "ref",
            "--server-name",
            "pt-evidence",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Cursor workspace .cursor/mcp.json snippet" in out
    assert '"pt-evidence"' in out
    assert '"command": "npx"' in out
    assert '"mcp-remote"' in out


def test_mcp_without_install_preserves_stdio_server(monkeypatch):
    called = False

    def fake_run_mcp():
        nonlocal called
        called = True

    monkeypatch.setattr(cli, "_run_mcp", fake_run_mcp)
    assert cli.main(["mcp"]) == 0
    assert called is True


# -- sessions / export / replay / import ------------------------------------


def _spool_with_session(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "sess_x.jsonl").write_text(
        '{"type":"user_message","session_id":"sess_x","seq":0,"idempotency_key":"k0","payload":{"content":"hi"}}\n'
        '{"type":"state_change","session_id":"sess_x","seq":1,"idempotency_key":"k1","payload":{"name":"span_start","span_name":"step"},"span_id":"sp1"}\n'
        '{"type":"agent_message","session_id":"sess_x","seq":2,"idempotency_key":"k2","payload":{"content":"working"},"span_id":"sp1"}\n'
        '{"type":"state_change","session_id":"sess_x","seq":3,"idempotency_key":"k3","payload":{"name":"span_end","span_name":"step"},"span_id":"sp1"}\n',
        encoding="utf-8",
    )
    return spool


def test_sessions_lists_spooled(capsys, tmp_path):
    spool = _spool_with_session(tmp_path)
    assert cli.main(["sessions", "--dir", str(spool)]) == 0
    out = capsys.readouterr().out
    assert "sess_x" in out and "4 event(s)" in out


def test_sessions_empty(capsys, tmp_path):
    assert cli.main(["sessions", "--dir", str(tmp_path / "nope")]) == 0
    assert "no sessions" in capsys.readouterr().out.lower()


def test_export_to_file_and_stdout(capsys, tmp_path):
    spool = _spool_with_session(tmp_path)
    out_file = tmp_path / "export.json"
    assert cli.main(["export", "sess_x", "--dir", str(spool), "--out", str(out_file)]) == 0
    import json

    doc = json.loads(out_file.read_text())
    assert doc["session_id"] == "sess_x"
    assert doc["summary"]["count"] == 4
    assert len(doc["events"]) == 4


def test_export_missing_session_nonzero(capsys, tmp_path):
    spool = _spool_with_session(tmp_path)
    assert cli.main(["export", "ghost", "--dir", str(spool)]) == 1


def test_replay_prints_timeline_with_span_indent(capsys, tmp_path):
    spool = _spool_with_session(tmp_path)
    assert cli.main(["replay", "sess_x", "--dir", str(spool)]) == 0
    out = capsys.readouterr().out
    assert "[0] user_message" in out
    assert "span_start" in out
    # the agent_message inside the span is indented
    assert any(line.startswith("  ") and "agent_message" in line for line in out.splitlines())


def test_import_no_api_key_nonzero(capsys, monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    spool = _spool_with_session(tmp_path)
    export = tmp_path / "e.json"
    cli.main(["export", "sess_x", "--dir", str(spool), "--out", str(export)])
    capsys.readouterr()
    rc = cli.main(["import", str(export)])
    assert rc == 1
    assert "no api_key" in capsys.readouterr().out.lower()
