from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "desktop-release.yml"
PUBLISH_SCRIPT = REPO_ROOT / "scripts" / "publish_desktop_release.sh"
ACTION_PINS = {
    "actions/checkout": "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",  # v7.0.0
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",  # v6.3.0
    "actions/setup-node": "48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e",  # v6.4.0
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",  # v7.0.1
    "actions/download-artifact": "37930b1c2abaa49bbe596cd826c3c89aef350131",  # v7.0.0
}


def _load_workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.is_file(), "Missing desktop release workflow"
    loaded = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict)
    return loaded


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    assert all(isinstance(step, dict) for step in steps)
    return steps


def _step_by_name(job: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [step for step in _steps(job) if step.get("name") == name]
    assert len(matches) == 1, f"Expected one workflow step named {name!r}"
    return matches[0]


def test_desktop_release_workflow_has_bounded_triggers_and_permissions() -> None:
    workflow = _load_workflow()

    assert set(workflow["on"]) == {"workflow_dispatch", "push"}
    assert workflow["on"]["push"]["tags"] == ["v*"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"

    jobs = workflow["jobs"]
    assert set(jobs) == {"build-desktop", "publish-release"}
    assert jobs["build-desktop"]["permissions"] == {"contents": "read"}
    assert jobs["publish-release"]["permissions"] == {"contents": "write"}
    assert jobs["publish-release"]["needs"] == "build-desktop"
    assert jobs["publish-release"]["if"] == ("startsWith(github.ref, 'refs/tags/v')")
    assert int(jobs["build-desktop"]["timeout-minutes"]) <= 90
    assert int(jobs["publish-release"]["timeout-minutes"]) <= 15


def test_desktop_release_workflow_pins_every_external_action() -> None:
    workflow = _load_workflow()
    seen: dict[str, str] = {}
    checkout: dict[str, Any] | None = None
    for job in workflow["jobs"].values():
        for step in _steps(job):
            uses = step.get("uses")
            if not uses:
                continue
            action, separator, revision = uses.partition("@")
            assert separator and re.fullmatch(r"[0-9a-f]{40}", revision)
            seen[action] = revision
            if action == "actions/checkout":
                checkout = step

    assert seen == ACTION_PINS
    assert checkout is not None
    assert checkout["with"]["persist-credentials"] == "false"


def test_windows_build_job_uses_expected_toolchain_and_quality_gates() -> None:
    job = _load_workflow()["jobs"]["build-desktop"]
    assert job["runs-on"] in {"windows-2025", "windows-latest"}

    setup_python = next(
        step for step in _steps(job) if step.get("uses", "").startswith("actions/setup-python@")
    )
    setup_node = next(
        step for step in _steps(job) if step.get("uses", "").startswith("actions/setup-node@")
    )
    assert setup_python["with"]["python-version"] == "3.12"
    assert setup_node["with"]["node-version"] == "24"
    assert setup_node["with"]["cache"] == "npm"
    assert setup_node["with"]["cache-dependency-path"] == "frontend/package-lock.json"

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for command in (
        'python -m pip install -e ".\\backend[dev,desktop,packaging]"',
        "npm ci",
        "python -m pytest backend -q",
        "python -m ruff check backend",
        "npm run typecheck",
        "npm test",
        "npm run build",
        ".\\scripts\\build_desktop.ps1",
        "-SkipTests",
        "-SkipFrontendBuild",
        "-SkipSmokeTest",
        ".\\scripts\\smoke_test_desktop.ps1",
    ):
        assert command in workflow_text


def test_native_quality_gates_are_independent_fail_fast_steps() -> None:
    job = _load_workflow()["jobs"]["build-desktop"]
    expected_steps = {
        "Run backend tests": "python -m pytest backend -q",
        "Run backend lint": "python -m ruff check backend",
        "Run frontend typecheck": "npm run typecheck",
        "Run frontend tests": "npm test",
        "Build frontend": "npm run build",
    }

    for name, command in expected_steps.items():
        assert _step_by_name(job, name)["run"].strip() == command


def test_build_verifies_tag_version_hashes_and_clean_release_artifacts() -> None:
    job = _load_workflow()["jobs"]["build-desktop"]
    version_step = _step_by_name(job, "Validate tag version")
    verify_step = _step_by_name(job, "Verify release artifacts")
    combined = f"{version_step['run']}\n{verify_step['run']}"

    assert "backend\\pyproject.toml" in version_step["run"]
    assert "GITHUB_REF_TYPE" in version_step["run"]
    assert '"v$projectVersion"' in version_step["run"]
    assert "Get-FileHash" in verify_step["run"]
    assert "SHA256" in verify_step["run"]
    assert "expectedReleaseNames" in verify_step["run"]
    assert "actualReleaseNames" in verify_step["run"]
    assert "Compare-Object" in verify_step["run"]
    assert "exactly the two expected portable artifacts" in verify_step["run"]
    assert "ModWatcherAgent-$env:PROJECT_VERSION-win-x64-portable.zip" in combined
    assert ".sha256" in combined
    assert "GetFullPath" in verify_step["run"]
    assert "release" in verify_step["run"]


def test_artifacts_are_uploaded_and_tag_release_is_immutable_and_idempotent() -> None:
    workflow = _load_workflow()
    build = workflow["jobs"]["build-desktop"]
    upload = next(
        step
        for step in _steps(build)
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["compression-level"] == "0"
    assert int(upload["with"]["retention-days"]) <= 30
    paths = upload["with"]["path"]
    assert "portable.zip" in paths
    assert paths.count(".sha256") >= 1

    publish = workflow["jobs"]["publish-release"]
    download = next(
        step
        for step in _steps(publish)
        if step.get("uses", "").startswith("actions/download-artifact@")
    )
    assert download["with"]["path"] == "release"
    reverify = _step_by_name(publish, "Reverify exact downloaded artifact set and SHA256 files")[
        "run"
    ]
    assert "expected_assets" in reverify
    assert "actual_assets" in reverify
    assert "find release -mindepth 1 -maxdepth 1" in reverify
    assert "diff -u" in reverify
    assert "release/*.sha256" in reverify
    assert "referenced_name" in reverify
    assert "expected_name" in reverify
    assert "Checksum file does not reference its matching artifact" in reverify
    release = _step_by_name(publish, "Publish GitHub release")
    assert release["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert release["env"]["GH_REPO"] == "${{ github.repository }}"
    assert "scripts/publish_desktop_release.sh" in release["run"]
    assert "docs/" not in release["run"]
    assert "--clobber" not in release["run"]


def test_publish_script_generates_release_notes_without_document_dependency() -> None:
    script = PUBLISH_SCRIPT.read_text(encoding="utf-8")

    assert "<tag> <release-dir>" in script
    assert "<notes-file>" not in script
    assert "required_notes" not in script
    assert "--notes-file" not in script
    assert "--generate-notes" in script


def test_every_powershell_workflow_step_is_syntactically_valid(tmp_path: Path) -> None:
    workflow = _load_workflow()
    parser_path = tmp_path / "parse-powershell.ps1"
    parser_path.write_text(
        """
param([Parameter(Mandatory = $true)][string]$Path)
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    $Path,
    [ref]$tokens,
    [ref]$errors
) | Out-Null
if ($errors.Count -gt 0) {
    $errors | ForEach-Object { [Console]::Error.WriteLine($_.Message) }
    exit 1
}
""".strip(),
        encoding="utf-8",
    )

    parsed = 0
    for job_name, job in workflow["jobs"].items():
        for index, step in enumerate(_steps(job)):
            if step.get("shell") != "pwsh" or "run" not in step:
                continue
            script_path = tmp_path / f"{job_name}-{index}.ps1"
            script_path.write_text(step["run"], encoding="utf-8")
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(parser_path),
                    "-Path",
                    str(script_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            assert result.returncode == 0, result.stderr or result.stdout
            parsed += 1

    assert parsed >= 10


def test_release_verification_rejects_any_unpaired_or_extra_file(tmp_path: Path) -> None:
    workflow = _load_workflow()
    script = _step_by_name(workflow["jobs"]["build-desktop"], "Verify release artifacts")["run"]
    script_path = tmp_path / "verify-release.ps1"
    script_path.write_text(script, encoding="utf-8")
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    version = "9.8.7"
    artifact_names = (
        f"ModWatcherAgent-{version}-win-x64-portable.zip",
    )
    for index, artifact_name in enumerate(artifact_names):
        payload = f"artifact-{index}".encode()
        (release_dir / artifact_name).write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        (release_dir / f"{artifact_name}.sha256").write_text(
            f"{digest}  {artifact_name}\n", encoding="ascii"
        )

    environment = os.environ.copy()
    environment["PROJECT_VERSION"] = version
    success = subprocess.run(
        [
            "pwsh.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert success.returncode == 0, success.stderr or success.stdout

    (release_dir / "ModWatcherAgent-debug-win-x64-portable.zip").write_bytes(b"unverified-extra")
    rejected = subprocess.run(
        [
            "pwsh.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert rejected.returncode != 0
    assert "exactly the two expected portable artifacts" in (
        f"{rejected.stdout}\n{rejected.stderr}"
    )


def test_publish_reverification_rejects_mismatched_hash_filename(
    tmp_path: Path,
) -> None:
    git_bash = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe"
    if not git_bash.is_file():
        pytest.skip("Git Bash is required to execute the Windows release shell gate")

    workflow = _load_workflow()
    script = _step_by_name(
        workflow["jobs"]["publish-release"],
        "Reverify exact downloaded artifact set and SHA256 files",
    )["run"]
    script_path = tmp_path / "reverify-release.sh"
    script_path.write_text(script, encoding="utf-8", newline="\n")
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    version = "9.8.7"
    portable_name = f"ModWatcherAgent-{version}-win-x64-portable.zip"
    payload = b"portable"
    (release_dir / portable_name).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    hash_path = release_dir / f"{portable_name}.sha256"
    hash_path.write_text(
        f"{digest}  {portable_name}\n", encoding="ascii", newline="\n"
    )
    environment = os.environ.copy()
    environment["GITHUB_REF_NAME"] = f"v{version}"

    success = subprocess.run(
        [str(git_bash), script_path.name],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert success.returncode == 0, success.stderr or success.stdout

    hash_path.write_text(
        f"{digest}  wrong-portable.zip\n", encoding="ascii", newline="\n"
    )
    rejected = subprocess.run(
        [str(git_bash), script_path.name],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert rejected.returncode != 0
    assert "does not reference its matching artifact" in rejected.stderr


def _write_fake_gh_wrapper(path: Path) -> None:
    path.write_text(
        r"""#!/usr/bin/env bash
set -euo pipefail

gh() {
  printf '%s\n' "$*" >> "$FAKE_GH_LOG"
  [[ "$1" == "release" ]]
  local operation="$2"
  local tag="$3"
  local remote="$FAKE_GH_REMOTE/$tag"
  shift 3
  case "$operation" in
    view)
      [[ -d "$remote" ]] || return 1
      if [[ " $* " == *" --json assets "* ]]; then
        [[ "${FAKE_GH_MODE:-}" != "inventory_failure" ]] || return 9
        find "$remote" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort
      fi
      ;;
    download)
      local pattern=""
      local destination=""
      while (($#)); do
        case "$1" in
          --pattern) pattern="$2"; shift 2 ;;
          --dir) destination="$2"; shift 2 ;;
          *) shift ;;
        esac
      done
      [[ -f "$remote/$pattern" ]] || return 1
      mkdir -p "$destination"
      cp "$remote/$pattern" "$destination/$pattern"
      ;;
    upload)
      local asset="$1"
      local name
      name="$(basename "$asset")"
      [[ ! -e "$remote/$name" ]] || return 2
      cp "$asset" "$remote/$name"
      ;;
    edit)
      ;;
    create)
      mkdir -p "$remote"
      while (($#)); do
        if [[ -f "$1" && "$1" == */release/* ]]; then
          cp "$1" "$remote/$(basename "$1")"
        fi
        shift
      done
      ;;
    *) return 3 ;;
  esac
}

source "$1" "${@:2}"
""",
        encoding="utf-8",
        newline="\n",
    )


@pytest.mark.parametrize(
    ("remote_mode", "expected_returncode", "expected_uploads"),
    [
        ("matching", 0, 0),
        ("mismatch", 1, 0),
        ("missing", 0, 1),
        ("extra", 1, 0),
        ("inventory_failure", 1, 0),
        ("missing_then_mismatch", 1, 0),
    ],
)
def test_publish_script_enforces_immutable_existing_release_assets_with_fake_gh(
    tmp_path: Path,
    remote_mode: str,
    expected_returncode: int,
    expected_uploads: int,
) -> None:
    git_bash = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe"
    if not git_bash.is_file():
        pytest.skip("Git Bash is required to execute the release publisher")

    publish_script = tmp_path / "publish.sh"
    publish_script.write_bytes(PUBLISH_SCRIPT.read_bytes())
    wrapper = tmp_path / "fake-gh-wrapper.sh"
    _write_fake_gh_wrapper(wrapper)

    tag = "v9.8.7"
    release_dir = tmp_path / "release"
    remote_dir = tmp_path / "remote" / tag
    release_dir.mkdir()
    remote_dir.mkdir(parents=True)
    names = (
        "ModWatcherAgent-9.8.7-win-x64-portable.zip",
        "ModWatcherAgent-9.8.7-win-x64-portable.zip.sha256",
    )
    for index, name in enumerate(names):
        payload = f"asset-{index}".encode()
        (release_dir / name).write_bytes(payload)
        should_skip = (remote_mode == "missing" and index == len(names) - 1) or (
            remote_mode == "missing_then_mismatch" and index == 0
        )
        if not should_skip:
            remote_payload = (
                b"changed"
                if (remote_mode == "mismatch" and index == 0)
                or (remote_mode == "missing_then_mismatch" and index == 1)
                else payload
            )
            (remote_dir / name).write_bytes(remote_payload)
    if remote_mode == "extra":
        (remote_dir / "unexpected-debug.zip").write_bytes(b"unexpected")

    log_path = tmp_path / "gh.log"
    environment = os.environ.copy()
    environment["FAKE_GH_REMOTE"] = str(tmp_path / "remote")
    environment["FAKE_GH_LOG"] = str(log_path)
    environment["FAKE_GH_MODE"] = remote_mode
    result = subprocess.run(
        [
            str(git_bash),
            wrapper.name,
            publish_script.name,
            tag,
            release_dir.name,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == expected_returncode, result.stderr or result.stdout
    log = log_path.read_text(encoding="utf-8")
    assert log.count("release upload") == expected_uploads
    if remote_mode in {
        "mismatch",
        "extra",
        "inventory_failure",
        "missing_then_mismatch",
    }:
        expected_error = {
            "mismatch": "immutable release asset mismatch",
            "extra": "unexpected remote release assets",
            "inventory_failure": "unable to query remote release assets",
            "missing_then_mismatch": "immutable release asset mismatch",
        }[remote_mode]
        assert expected_error in result.stderr.casefold()
        if remote_mode == "missing_then_mismatch":
            assert not (remote_dir / names[0]).exists()
    else:
        for name in names:
            assert (remote_dir / name).read_bytes() == (release_dir / name).read_bytes()
