from __future__ import annotations

import ast
import base64
import hashlib
import json
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "packaging" / "mod_watcher_agent.spec"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_desktop.ps1"
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "smoke_test_desktop.ps1"
PORTABLE_SCRIPT = REPO_ROOT / "scripts" / "package_portable.ps1"


def _required_file(path: Path) -> Path:
    assert path.is_file(), f"Missing Task 7 file: {path.relative_to(REPO_ROOT)}"
    return path


def _assignment(tree: ast.Module, name: str) -> ast.expr:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return node.value
    pytest.fail(f"Missing assignment: {name}")


def _literal_strings(node: ast.expr) -> list[str]:
    value = ast.literal_eval(node)
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return value


def _path_parts(node: ast.expr) -> tuple[str, ...]:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
    ):
        return _path_parts(node.args[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return (*_path_parts(node.left), *_path_parts(node.right))
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return tuple(part for part in node.value.replace("\\", "/").split("/") if part)
    raise AssertionError(f"Unsupported spec path expression: {ast.dump(node)}")


def _call(tree: ast.Module, name: str) -> ast.Call:
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    ]
    assert len(calls) == 1, f"Expected exactly one {name} call"
    return calls[0]


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None}


def _parse_spec() -> tuple[ast.Module, dict[tuple[str, ...], str]]:
    text = _required_file(SPEC_PATH).read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(SPEC_PATH))
    datas_node = _assignment(tree, "datas")
    assert isinstance(datas_node, (ast.List, ast.Tuple))
    datas: dict[tuple[str, ...], str] = {}
    for item in datas_node.elts:
        assert isinstance(item, ast.Tuple) and len(item.elts) == 2
        source, destination = item.elts
        assert isinstance(destination, ast.Constant) and isinstance(destination.value, str)
        datas[_path_parts(source)] = destination.value.replace("\\", "/")
    return tree, datas


def _powershell_ast(path: Path) -> dict[str, Any]:
    _required_file(path)
    parser_script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{str(path).replace("'", "''")}',
    [ref]$tokens,
    [ref]$errors
)
$summary = [ordered]@{{
    errors = @($errors | ForEach-Object {{ $_.Message }})
    parameters = @($ast.ParamBlock.Parameters | ForEach-Object {{ $_.Name.VariablePath.UserPath }})
    commands = @($ast.FindAll(
        {{ param($node) $node -is [System.Management.Automation.Language.CommandAst] }},
        $true
    ) | ForEach-Object {{ $_.GetCommandName() }} | Where-Object {{ $_ }} | Sort-Object -Unique)
    variables = @($ast.FindAll(
        {{ param($node) $node -is [System.Management.Automation.Language.VariableExpressionAst] }},
        $true
    ) | ForEach-Object {{ $_.VariablePath.UserPath }} | Sort-Object -Unique)
    recursive_removals = @($ast.FindAll(
        {{
            param($node)
            $node -is [System.Management.Automation.Language.CommandAst] -and
            $node.GetCommandName() -eq 'Remove-Item' -and
            @($node.CommandElements | ForEach-Object {{ $_.Extent.Text }}) -contains '-Recurse'
        }},
        $true
    ) | ForEach-Object {{
        $parent = $_.Parent
        while ($parent -and
            $parent -isnot [System.Management.Automation.Language.FunctionDefinitionAst]) {{
            $parent = $parent.Parent
        }}
        [ordered]@{{
            function = if ($parent) {{ $parent.Name }} else {{ '' }}
            text = $_.Extent.Text
        }}
    }})
}}
$summary | ConvertTo-Json -Compress -Depth 4
"""
    encoded = base64.b64encode(parser_script.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    summary = json.loads(completed.stdout.strip())
    assert summary["errors"] == []
    return summary


def _run_script(path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(path),
            *arguments,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_spec_semantically_defines_required_onedir_bundle() -> None:
    tree, datas = _parse_spec()
    assert datas == {
        ("repo_root", "frontend", "dist"): "frontend/dist",
        ("repo_root", "backend", "alembic.ini"): "backend",
        ("repo_root", "backend", "game_aliases.json"): "backend",
        ("repo_root", "docs", "mwlogo.png"): "docs",
        ("repo_root", "README.md"): ".",
        ("repo_root", "LICENSE"): ".",
    }

    analysis = _call(tree, "Analysis")
    assert isinstance(analysis.args[0], ast.List) and len(analysis.args[0].elts) == 1
    assert _path_parts(analysis.args[0].elts[0]) == (
        "repo_root",
        "backend",
        "desktop_app.py",
    )
    assert isinstance(_keywords(analysis)["datas"], ast.Name)
    assert _keywords(analysis)["datas"].id == "datas"

    alembic_tree = _call(tree, "Tree")
    assert _path_parts(alembic_tree.args[0]) == ("repo_root", "backend", "alembic")
    tree_keywords = _keywords(alembic_tree)
    assert ast.literal_eval(tree_keywords["prefix"]) == "backend/alembic"
    assert set(ast.literal_eval(tree_keywords["excludes"])) == {"__pycache__", "*.pyc"}
    tree_append = next(
        node
        for node in tree.body
        if isinstance(node, ast.AugAssign) and ast.unparse(node.target) == "a.datas"
    )
    assert isinstance(tree_append.op, ast.Add)
    assert isinstance(tree_append.value, ast.Name) and tree_append.value.id == "alembic_datas"

    exe_keywords = _keywords(_call(tree, "EXE"))
    assert ast.literal_eval(exe_keywords["name"]) == "ModWatcherAgent"
    assert ast.literal_eval(exe_keywords["console"]) is False
    assert ast.literal_eval(exe_keywords["exclude_binaries"]) is True
    assert ast.literal_eval(exe_keywords["contents_directory"]) == "_internal"
    assert _path_parts(exe_keywords["icon"]) == ("repo_root", "docs", "mwlogo.png")
    assert _path_parts(exe_keywords["version"]) == (
        "repo_root",
        "packaging",
        "version_info.txt",
    )
    assert ast.literal_eval(_keywords(_call(tree, "COLLECT"))["name"]) == "ModWatcherAgent"

    root_assignment = ast.unparse(_assignment(tree, "repo_root"))
    assert "SPECPATH" in root_assignment
    assert "cwd" not in root_assignment.lower()


def test_windows_version_info_matches_project_version() -> None:
    version_path = _required_file(REPO_ROOT / "packaging" / "version_info.txt")
    tree = ast.parse(version_path.read_text(encoding="utf-8"), filename=str(version_path))
    fixed_info = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "FixedFileInfo"
    )
    keywords = _keywords(fixed_info)
    project = tomllib.loads((REPO_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    numeric_version = tuple(int(part) for part in version.split(".")) + (0,)
    assert ast.literal_eval(keywords["filevers"]) == numeric_version
    assert ast.literal_eval(keywords["prodvers"]) == numeric_version
    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert {"Mod Watcher Agent", "ModWatcherAgent.exe", version}.issubset(string_literals)


def test_spec_declares_required_hidden_imports_and_safe_excludes() -> None:
    tree, datas = _parse_spec()
    hidden_imports = set(_literal_strings(_assignment(tree, "hidden_imports")))
    assert {
        "app.main",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.dialects.sqlite.pysqlite",
        "pystray._win32",
        "webview",
        "webview.platforms.edgechromium",
        "PIL.Image",
        "PIL.ImageDraw",
        "clr",
    }.issubset(hidden_imports)

    excludes = set(_literal_strings(_assignment(tree, "excluded_modules")))
    assert {
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "tkinter",
        "_tkinter",
        "gi",
        "gtk",
        "cefpython3",
        "webview.platforms.qt",
        "webview.platforms.gtk",
        "webview.platforms.cef",
    }.issubset(excludes)

    forbidden_parts = {
        ".env",
        "browser_profiles",
        "snapshots",
        "cache",
        "tests",
        "data",
        "logs",
    }
    assert not {
        part.lower()
        for source_parts in datas
        for part in source_parts
        if part.lower() in forbidden_parts
    }


def test_build_script_has_safe_parameters_quality_gates_and_clean_build() -> None:
    summary = _powershell_ast(BUILD_SCRIPT)
    assert {
        "SkipTests",
        "SkipFrontendBuild",
        "SkipSmokeTest",
        "SkipPortable",
        "SkipInstaller",
        "PythonExecutable",
    }.issubset(set(summary["parameters"]))
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    lowered = text.lower()
    assert re.search(r'\$ErrorActionPreference\s*=\s*["\']Stop["\']', text)
    assert "$PSScriptRoot" in text
    assert "[dev,desktop,packaging]" in text
    for command in (
        "-m pytest backend",
        "-m ruff check backend",
        "npm ci",
        "npm run typecheck",
        "npm test",
        "npm run build",
        "-m PyInstaller",
        "--clean",
        "--distpath",
        "--workpath",
        "smoke_test_desktop.ps1",
        "package_portable.ps1",
    ):
        assert command.lower() in lowered
    assert re.search(r"exit\s+\$exitCode\b", text, re.IGNORECASE)
    assert "stop-frontendnodeprocesses" not in lowered
    assert "stop-process" not in lowered
    assert "taskkill" not in lowered
    assert "installer" in lowered and "not" in lowered


def test_smoke_script_is_isolated_bounded_and_checks_cleanup() -> None:
    summary = _powershell_ast(SMOKE_SCRIPT)
    assert {"ExecutablePath", "TimeoutSeconds"}.issubset(set(summary["parameters"]))
    assert {"Get-NetTCPConnection", "Remove-Item"}.issubset(set(summary["commands"]))
    text = SMOKE_SCRIPT.read_text(encoding="utf-8")
    lowered = text.lower()
    assert re.search(r'\$ErrorActionPreference\s*=\s*["\']Stop["\']', text)
    assert "$PSScriptRoot" in text
    assert "$env:MW_USER_DATA_DIR" in text
    assert "--smoke-test" in text
    assert "System.Diagnostics.ProcessStartInfo" in text
    assert "CreateNoWindow" in text
    assert "ReadToEndAsync" in text
    assert "$exitCode = $process.ExitCode" in text
    assert "Start-Process" not in text
    assert "exitcode" in lowered
    assert "mod_watcher.db" in lowered
    assert "desktop.log" in lowered
    assert "get-nettcpconnection" in lowered
    assert "localport" in lowered
    assert "finally" in lowered
    assert "remove-item" in lowered
    assert "node" not in lowered


def test_build_and_smoke_require_edgechromium_and_pythonnet_runtime_files(
    tmp_path: Path,
) -> None:
    required_files = {
        "_internal/webview/lib/Microsoft.Web.WebView2.Core.dll",
        "_internal/webview/lib/Microsoft.Web.WebView2.WinForms.dll",
        "_internal/webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
        "_internal/pythonnet/runtime/Python.Runtime.dll",
    }
    for script_path in (BUILD_SCRIPT, SMOKE_SCRIPT):
        text = script_path.read_text(encoding="utf-8").replace("\\", "/")
        assert "Assert-RequiredDesktopRuntimeFiles" in text
        assert required_files.issubset(set(re.findall(r'"([^"\r\n]+\.dll)"', text)))

    fake_bundle = tmp_path / "missing runtime" / "ModWatcherAgent"
    fake_bundle.mkdir(parents=True)
    fake_executable = fake_bundle / "ModWatcherAgent.exe"
    fake_executable.write_bytes(b"not-a-real-executable")
    completed = _run_script(
        SMOKE_SCRIPT,
        "-ExecutablePath",
        str(fake_executable),
        "-TimeoutSeconds",
        "1",
    )
    combined_output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode != 0
    assert "Missing required desktop runtime file" in combined_output
    assert "Microsoft.Web.WebView2.Core.dll" in combined_output


@pytest.mark.parametrize(
    ("script_path", "cleanup_function", "allowed_marker"),
    [
        (BUILD_SCRIPT, "Remove-ControlledDirectory", "$repoRoot"),
        (PORTABLE_SCRIPT, "Remove-ControlledDirectory", "$resolvedOutputDir"),
        (SMOKE_SCRIPT, "Remove-SmokeDirectory", "$systemTemp"),
    ],
)
def test_recursive_cleanup_is_confined_to_an_expected_root_and_leaf(
    script_path: Path,
    cleanup_function: str,
    allowed_marker: str,
) -> None:
    summary = _powershell_ast(script_path)
    removals = summary["recursive_removals"]
    assert removals, f"{script_path.name} should clean its controlled output"
    assert {removal["function"] for removal in removals} == {cleanup_function}
    text = script_path.read_text(encoding="utf-8")
    function_match = re.search(
        rf"function\s+{re.escape(cleanup_function)}\b(?P<body>.*?)(?=\nfunction\s|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    assert function_match is not None
    body = function_match.group("body")
    assert "GetFullPath" in body
    assert "Resolve-Path" in body
    assert "Split-Path -Leaf" in body
    assert allowed_marker in text


def test_portable_script_builds_clean_zip_and_matching_sha256(tmp_path: Path) -> None:
    _powershell_ast(PORTABLE_SCRIPT)
    executable_dir = tmp_path / "便携 输入" / "ModWatcherAgent"
    internal_dir = executable_dir / "_internal"
    internal_dir.mkdir(parents=True)
    (executable_dir / "ModWatcherAgent.exe").write_bytes(b"fake-executable")
    (internal_dir / "runtime.txt").write_text("runtime", encoding="utf-8")
    output_dir = tmp_path / "发布 空间"

    completed = _run_script(
        PORTABLE_SCRIPT,
        "-ExecutableDir",
        str(executable_dir),
        "-OutputDir",
        str(output_dir),
        "-Version",
        "9.8.7",
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    zip_path = output_dir / "ModWatcherAgent-9.8.7-win-x64-portable.zip"
    hash_path = Path(f"{zip_path}.sha256")
    assert zip_path.is_file()
    assert hash_path.is_file()
    expected_hash = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert hash_path.read_text(encoding="ascii").strip() == f"{expected_hash}  {zip_path.name}"
    with zipfile.ZipFile(zip_path) as archive:
        names = {name.replace("\\", "/") for name in archive.namelist()}
    assert "ModWatcherAgent/ModWatcherAgent.exe" in names
    assert "ModWatcherAgent/_internal/runtime.txt" in names
    assert not (output_dir / ".portable-staging").exists()


@pytest.mark.parametrize(
    "relative_path",
    [
        ".env",
        "data/mod_watcher.db-wal",
        "logs/desktop.log",
        "browser_profiles/profile.json",
        "snapshots/snapshot.json",
        "cache/cache.bin",
        "tests/test_key.pem",
    ],
)
def test_portable_script_rejects_runtime_data_tests_and_secrets(
    tmp_path: Path,
    relative_path: str,
) -> None:
    _required_file(PORTABLE_SCRIPT)
    executable_dir = tmp_path / "bundle" / "ModWatcherAgent"
    executable_dir.mkdir(parents=True)
    (executable_dir / "ModWatcherAgent.exe").write_bytes(b"fake-executable")
    forbidden = executable_dir / relative_path
    forbidden.parent.mkdir(parents=True, exist_ok=True)
    forbidden.write_text("forbidden", encoding="utf-8")

    completed = _run_script(
        PORTABLE_SCRIPT,
        "-ExecutableDir",
        str(executable_dir),
        "-OutputDir",
        str(tmp_path / "release"),
        "-Version",
        "9.8.7",
    )

    assert completed.returncode != 0
    assert "forbidden" in f"{completed.stdout}\n{completed.stderr}".lower()


def test_batch_entry_forwards_arguments_and_exit_code() -> None:
    batch = _required_file(REPO_ROOT / "build-desktop.bat").read_text(encoding="utf-8")
    normalized = batch.replace("/", "\\").lower()
    assert "%~dp0scripts\\build_desktop.ps1" in normalized
    assert "%*" in batch
    assert re.search(r"exit\s+/b\s+%errorlevel%", batch, re.IGNORECASE)
    assert "start " not in normalized


def test_gitignore_excludes_only_task7_local_build_outputs() -> None:
    entries = {
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {"dist-desktop/", "build-desktop/", ".venv-desktop-build/"}.issubset(entries)
