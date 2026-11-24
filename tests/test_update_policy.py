import json
import os
from pathlib import Path
import shutil
import subprocess
from textwrap import dedent

import pytest


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = Path(".heaven/update-policy.json")
WORKFLOW_PATH = Path(".github/workflows/heaven-autoupdate-policy.yml")
REQUIRED_ERROR = "Automatic main source consumption must be required."
INTERVAL_TYPE_ERROR = "Source update poll interval must be a JSON integer."
INTERVAL_RANGE_ERROR = "Source update poll interval must be 1-60 minutes."
CONTROLLER_ERROR = "Source update controller mismatch."
MISSING = object()


@pytest.mark.parametrize("shell_name", ["powershell", "pwsh"])
def test_hosted_validator_requires_literal_json_scalars(tmp_path, shell_name):
    shell = shutil.which(shell_name)
    if shell is None:
        if os.name == "nt":
            pytest.fail(f"{shell_name} is required for the Windows validator regression")
        pytest.skip(f"{shell_name} is unavailable on this platform")

    workflow = (ROOT / WORKFLOW_PATH).read_text(encoding="utf-8")
    # Execute the actual enforcement step, including its source identity check,
    # using the checked-in validator rather than copying its predicates.
    validator = tmp_path / "validate.ps1"
    run_block = workflow.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0]
    assert "& ./scripts/Test-RepoUpdatePolicy.ps1" in run_block
    validator.write_text(dedent(run_block), encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(
        ROOT / "scripts/Test-RepoUpdatePolicy.ps1",
        tmp_path / "scripts/Test-RepoUpdatePolicy.ps1",
    )
    policy_file = tmp_path / POLICY_PATH
    policy_file.parent.mkdir()
    policy = json.loads((ROOT / POLICY_PATH).read_text(encoding="utf-8"))
    evidence = tmp_path / policy["runtime_update"]["apply_script"]
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.touch()
    subprocess.run(["git", "init", "--quiet", "--template="], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Policy fixture", "-c", "user.email=fixture@example.test",
            "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={tmp_path / 'no-hooks'}",
            "commit", "--allow-empty", "--quiet", "-m", "Policy fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    env = {
        **os.environ,
        "EXPECTED_SHA": head,
        "EXPECTED_REPOSITORY": "fengie/heaven-icloud-mail",
    }
    command = [shell, "-NoLogo", "-NoProfile", "-NonInteractive"]
    if os.name == "nt":
        command.extend(["-ExecutionPolicy", "Bypass"])
    command.extend(["-File", str(validator)])
    source_update = policy["source_update"]

    def assert_policy(field, value, error):
        original = source_update[field]
        try:
            if value is MISSING:
                del source_update[field]
            else:
                source_update[field] = value
            policy_file.write_text(json.dumps(policy), encoding="utf-8")
            result = subprocess.run(
                command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
            )
            output = result.stdout + result.stderr
            if error is None:
                assert result.returncode == 0 and "HEAVEN_AUTOUPDATE_POLICY_OK" in output, output
            else:
                assert result.returncode != 0 and error in output, (field, value, output)
                assert "HEAVEN_AUTOUPDATE_POLICY_OK" not in output
        finally:
            source_update[field] = original

    for value in (False, MISSING, None, "false", "true", 0, 1, {"value": True}, [], [True]):
        assert_policy("required", value, REQUIRED_ERROR)
    assert_policy("required", True, None)
    for value in (MISSING, None, "1", 1.0, 1.5, True, {"value": 1}, [], [1]):
        assert_policy("poll_interval_minutes", value, INTERVAL_TYPE_ERROR)
    for value in (0, 61):
        assert_policy("poll_interval_minutes", value, INTERVAL_RANGE_ERROR)
    for value in (1, 60):
        assert_policy("poll_interval_minutes", value, None)

    for value in (MISSING, None, False, "", "other/controller", "HEAVEN-TOOLBOX/repo-autoupdate", {}, [], ["heaven-toolbox/repo-autoupdate"]):
        assert_policy("controller", value, CONTROLLER_ERROR)
    assert_policy("controller", "heaven-toolbox/repo-autoupdate", None)

    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    result = subprocess.run(
        command, cwd=tmp_path, env={**env, "EXPECTED_SHA": "0" * 40},
        capture_output=True, text=True, timeout=30,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0 and "SOURCE_REVISION_MISMATCH" in output, output
    assert "HEAVEN_AUTOUPDATE_POLICY_OK" not in output
