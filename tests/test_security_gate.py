"""Exercise the real tracked-file gate with synthetic index and file contents."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def gate(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/security_gate.py"
    spec = importlib.util.spec_from_file_location("privacy_gate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)

    def tracked_index(command, **kwargs):
        assert command == ["git", "-C", str(tmp_path), "ls-files", "-z"]
        assert kwargs == {"capture_output": True, "check": False}
        index = b"\x00".join(path.name.encode("utf-8") for path in tmp_path.iterdir() if path.is_file())
        return SimpleNamespace(returncode=0, stdout=index + b"\x00")

    monkeypatch.setattr(module.subprocess, "run", tracked_index)
    return module


@pytest.mark.parametrize("field", [
    "ICLOUD_MAIL_USERNAME", "ICLOUD_MAIL_APP_PASSWORD", "APPLE_ID_PASSWORD", "MCP_ACCESS_TOKEN",
])
@pytest.mark.parametrize("filename", [".env.example", ".ENV.EXAMPLE"])
@pytest.mark.parametrize("prefix", ["", "export ", "export\t"])
@pytest.mark.parametrize("value", [
    "synthetic-placeholder", "  synthetic-placeholder  ", '"synthetic-placeholder"',
    "'synthetic-placeholder'", '"  synthetic-placeholder  " # comment', '"#synthetic-placeholder"',
])
def test_populated_example_credentials_fail_without_printing_values(gate, field, filename, prefix, value, capsys):
    (gate.ROOT / filename).write_text(f"{prefix}{field}={value}\n", encoding="utf-8")
    assert gate.main() == 1
    captured = capsys.readouterr()
    assert filename in captured.err
    assert "synthetic-placeholder" not in captured.out + captured.err


@pytest.mark.parametrize("value", ["", "  \t", "# documented empty", "''", '\"\"', "'' # empty"])
@pytest.mark.parametrize("filename", [".env.example", ".ENV.EXAMPLE"])
@pytest.mark.parametrize("prefix", ["", "export "])
def test_empty_example_credentials_are_allowed(gate, value, filename, prefix):
    (gate.ROOT / filename).write_text(
        f"{prefix}ICLOUD_MAIL_USERNAME={value}\n{prefix}ICLOUD_MAIL_APP_PASSWORD={value}\n"
        "ICLOUD_MAIL_ACCOUNT_CONSENT=no\nICLOUD_MAIL_TIMEZONE=America/New_York\nHEAVEN_MAIL_TRANSPORT=stdio\n",
        encoding="utf-8",
    )
    assert gate.main() == 0


@pytest.mark.parametrize("filename", [".env.private", ".ENV.PRIVATE"])
def test_private_env_case_aliases_remain_forbidden(gate, filename, capsys):
    (gate.ROOT / filename).write_text("# synthetic private config\n", encoding="utf-8")
    assert gate.main() == 1
    assert filename in capsys.readouterr().err
