"""Lightweight cross-platform tests for the fixed security and auto-update contract."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_autoupdate_policy_names_own_repo_and_non_none_runtime():
    policy = json.loads((ROOT / ".heaven/update-policy.json").read_text())
    assert policy["repository"] == "fengie/heaven-icloud-mail"
    assert policy["branch"] == "main"
    assert policy["kind"] == "product"
    assert policy["runtime_update"]["mode"] == "apply-script"
    assert (ROOT / policy["runtime_update"]["apply_script"]).is_file()
    assert policy["source_update"]["strategy"] == "ff-only"


def test_powershell_runner_refuses_network_and_checks_installed_sha():
    script = (ROOT / "scripts/Run-HeavenICloudMail.ps1").read_text()
    updater = (ROOT / "scripts/Apply-HeavenICloudMail.ps1").read_text()
    assert "-ne 'stdio'" in script
    assert "^[0-9a-f]{40}$" in script
    assert "--show-current" in updater
    assert "--porcelain" in updater
    assert "HEAVEN_ICLOUD_MAIL_LOCAL_INSTALLED" in updater


def test_local_gitignore_protects_mail_dumps():
    text = (ROOT / ".gitignore").read_text()
    for pattern in (".env", "*.eml", "*.mbox", "*.pem", "*.key"):
        assert pattern in text


def test_git_for_windows_forward_slash_roots_are_normalized():
    updater = (ROOT / "scripts/Apply-HeavenICloudMail.ps1").read_text()
    assert '[IO.Path]::GetFullPath' in updater
    assert '[StringComparer]::OrdinalIgnoreCase' in updater
