from __future__ import annotations

import ast
import base64
import hashlib
import json
import re
import struct
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
PACKAGING_COMMON_SCRIPT = REPO_ROOT / "scripts" / "desktop_packaging_common.ps1"
PACKAGING_CORE_SCRIPT = REPO_ROOT / "scripts" / "packaging_common.ps1"
INSTALLER_SCRIPT = REPO_ROOT / "packaging" / "installer" / "ModWatcherAgent.iss"
REQUIRED_DESKTOP_RUNTIME_FILES = (
    "_internal/webview/lib/Microsoft.Web.WebView2.Core.dll",
    "_internal/webview/lib/Microsoft.Web.WebView2.WinForms.dll",
    "_internal/webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
    "_internal/pythonnet/runtime/Python.Runtime.dll",
)


def _required_file(path: Path) -> Path:
    assert path.is_file(), f"Missing required packaging file: {path.relative_to(REPO_ROOT)}"
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


def _invoke_powershell_predicate(
    path: Path,
    function_name: str,
    **arguments: str | bool,
) -> bool:
    _required_file(path)

    def powershell_literal(value: str | bool) -> str:
        if isinstance(value, bool):
            return "$true" if value else "$false"
        return "'{}'".format(value.replace("'", "''"))

    assignments = "\n".join(
        f"$invokeArguments['{key}'] = {powershell_literal(value)}"
        for key, value in arguments.items()
    )
    parser_script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{str(path).replace("'", "''")}',
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -gt 0) {{ throw ($errors.Message -join '; ') }}
$definitions = @($ast.FindAll(
    {{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq '{function_name}'
    }},
    $true
))
if ($definitions.Count -ne 1) {{
    throw 'Expected exactly one {function_name} function definition.'
}}
. ([ScriptBlock]::Create($definitions[0].Extent.Text))
$invokeArguments = @{{}}
{assignments}
[bool](& '{function_name}' @invokeArguments) | ConvertTo-Json -Compress
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
    return bool(json.loads(completed.stdout.strip()))


def _run_powershell_functions(
    path: Path,
    function_names: tuple[str, ...],
    statements: str,
) -> subprocess.CompletedProcess[str]:
    _required_file(path)
    names = ", ".join(f"'{name.replace(chr(39), chr(39) * 2)}'" for name in function_names)
    parser_script = rf"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{str(path).replace("'", "''")}',
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -gt 0) {{ throw ($errors.Message -join '; ') }}
foreach ($functionName in @({names})) {{
    $definitions = @($ast.FindAll(
        {{
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
        }},
        $true
    ))
    if ($definitions.Count -ne 1) {{
        throw "Expected exactly one $functionName function definition."
    }}
    . ([ScriptBlock]::Create($definitions[0].Extent.Text))
}}
{statements}
"""
    encoded = base64.b64encode(parser_script.encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


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


def _create_directory_junction(link: Path, target: Path) -> None:
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def _write_fake_pe(
    path: Path,
    *,
    machine: int = 0x8664,
    number_of_sections: int = 1,
    size_of_optional_header: int = 0xF0,
    characteristics: int = 0x0022,
    optional_magic: int = 0x020B,
    include_section_table: bool = True,
    truncate_to: int | None = None,
) -> None:
    pe_offset = 0x80
    optional_header_offset = pe_offset + 24
    optional_header_end = optional_header_offset + size_of_optional_header
    section_table_size = 40 * number_of_sections if include_section_table else 0
    payload = bytearray(max(optional_header_end + section_table_size, 0x9A))
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, pe_offset)
    payload[pe_offset : pe_offset + 4] = b"PE\0\0"
    struct.pack_into(
        "<HHIIIHH",
        payload,
        pe_offset + 4,
        machine,
        number_of_sections,
        0,
        0,
        0,
        size_of_optional_header,
        characteristics,
    )
    struct.pack_into("<H", payload, optional_header_offset, optional_magic)
    if truncate_to is not None:
        payload = payload[:truncate_to]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_truncated_x64_pe_header(path: Path) -> None:
    payload = bytearray(0x86)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", payload, 0x84, 0x8664)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_required_desktop_runtime_files(bundle_root: Path) -> None:
    for relative_path in REQUIRED_DESKTOP_RUNTIME_FILES:
        runtime_file = bundle_root / relative_path
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.write_bytes(b"runtime")


def _copy_build_script_fixture(repo: Path) -> Path:
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir(parents=True)
    copied_script = scripts_dir / BUILD_SCRIPT.name
    copied_script.write_text(BUILD_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    copied_common = scripts_dir / PACKAGING_COMMON_SCRIPT.name
    copied_common.write_text(
        PACKAGING_COMMON_SCRIPT.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    copied_core = scripts_dir / PACKAGING_CORE_SCRIPT.name
    copied_core.write_text(
        PACKAGING_CORE_SCRIPT.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return copied_script


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


def test_desktop_release_contract_is_portable_only() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "desktop-release.yml"
    publish_script = REPO_ROOT / "scripts" / "publish_desktop_release.sh"
    readme = REPO_ROOT / "README.md"
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (BUILD_SCRIPT, workflow_path, publish_script, readme)
    )

    assert not INSTALLER_SCRIPT.exists()
    assert "SkipInstaller" not in _powershell_ast(BUILD_SCRIPT)["parameters"]
    for installer_marker in (
        "ISCC",
        "Inno Setup",
        "ModWatcherAgent-Setup",
        "WebView2BootstrapperPath",
    ):
        assert installer_marker not in combined


def test_smoke_script_uses_explicit_port_handshake_and_checks_cleanup() -> None:
    summary = _powershell_ast(SMOKE_SCRIPT)
    assert {"ExecutablePath", "TimeoutSeconds"}.issubset(set(summary["parameters"]))
    assert "Remove-Item" in set(summary["commands"])
    assert "Get-NetTCPConnection" not in set(summary["commands"])
    text = SMOKE_SCRIPT.read_text(encoding="utf-8")
    lowered = text.lower()
    assert re.search(r'\$ErrorActionPreference\s*=\s*["\']Stop["\']', text)
    assert "$PSScriptRoot" in text
    assert "$env:MW_USER_DATA_DIR" in text
    assert "--smoke-test" in text
    assert "System.Diagnostics.ProcessStartInfo" in text
    assert "CreateNoWindow" in text
    assert "System.Net.Sockets.TcpListener" in text
    assert 'EnvironmentVariables["MW_SMOKE_PORT"]' in text
    assert "MW_SMOKE_PORT_USED=" in text
    assert "smoke-port-used.txt" in text
    assert "ReadToEndAsync" in text
    assert "$exitCode = $process.ExitCode" in text
    assert "Start-Process" not in text
    assert "exitcode" in lowered
    assert "mod_watcher.db" in lowered
    assert "desktop.log" in lowered
    assert "get-nettcpconnection" not in lowered
    assert "observedports" not in lowered
    assert "localendpoint" in lowered
    assert "loopback port was not released" in lowered
    assert "finally" in lowered
    assert "remove-item" in lowered
    assert "node" not in lowered


def test_build_and_smoke_require_edgechromium_and_pythonnet_runtime_files(
    tmp_path: Path,
) -> None:
    common_text = PACKAGING_COMMON_SCRIPT.read_text(encoding="utf-8").replace("\\", "/")
    assert set(REQUIRED_DESKTOP_RUNTIME_FILES).issubset(
        set(re.findall(r'"([^"\r\n]+\.dll)"', common_text))
    )
    for script_path in (BUILD_SCRIPT, SMOKE_SCRIPT):
        text = script_path.read_text(encoding="utf-8").replace("\\", "/")
        assert "Assert-RequiredDesktopRuntimeFiles" in text

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
        (PACKAGING_COMMON_SCRIPT, "Remove-ControlledDirectory", "$AllowedRoot"),
        (SMOKE_SCRIPT, "Remove-SmokeDirectory", "$systemTemp"),
    ],
)
def test_recursive_cleanup_is_confined_to_an_expected_root_and_leaf(
    script_path: Path, cleanup_function: str, allowed_marker: str
) -> None:
    summary = _powershell_ast(script_path)
    assert {removal["function"] for removal in summary["recursive_removals"]} == {
        cleanup_function
    }
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

    for consumer, marker in (
        (BUILD_SCRIPT, "$repoRoot"),
        (PORTABLE_SCRIPT, "$resolvedOutputDir"),
    ):
        consumer_summary = _powershell_ast(consumer)
        assert "Remove-ControlledDirectory" in set(consumer_summary["commands"])
        assert marker in consumer.read_text(encoding="utf-8")


def test_portable_script_builds_clean_zip_and_matching_sha256(tmp_path: Path) -> None:
    _powershell_ast(PORTABLE_SCRIPT)
    executable_dir = tmp_path / "便携 输入" / "ModWatcherAgent"
    internal_dir = executable_dir / "_internal"
    internal_dir.mkdir(parents=True)
    _write_fake_pe(executable_dir / "ModWatcherAgent.exe")
    (internal_dir / "runtime.txt").write_text("runtime", encoding="utf-8")
    certifi_bundle = internal_dir / "certifi" / "cacert.pem"
    certifi_bundle.parent.mkdir(parents=True)
    certifi_bundle.write_text(
        "-----BEGIN CERTIFICATE-----\npublic CA bundle\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    (internal_dir / "monkey.pem").write_text("non-key fixture", encoding="utf-8")
    (internal_dir / "public-key.pem").write_text(
        "-----BEGIN PUBLIC KEY-----\npublic key\n-----END PUBLIC KEY-----\n",
        encoding="utf-8",
    )
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
    assert "ModWatcherAgent/_internal/certifi/cacert.pem" in names
    assert "ModWatcherAgent/_internal/monkey.pem" in names
    assert "ModWatcherAgent/_internal/public-key.pem" in names
    assert not (output_dir / ".portable-staging").exists()


@pytest.mark.parametrize(
    "relative_path",
    [
        ".env",
        "data/mod_watcher.db-wal",
        "data/mod_watcher.db.backup-20260712",
        "data/mod_watcher.sqlite.bak",
        "data/runtime-private.bin",
        "logs/desktop.log",
        "logs/runtime-private.bin",
        "browser_profiles/profile.json",
        "snapshots/snapshot.json",
        "cache/cache.bin",
        "tests/test_key.pem",
        "private.key",
    ],
)
def test_portable_script_rejects_runtime_data_tests_and_secrets(
    tmp_path: Path,
    relative_path: str,
) -> None:
    _required_file(PORTABLE_SCRIPT)
    executable_dir = tmp_path / "bundle" / "ModWatcherAgent"
    executable_dir.mkdir(parents=True)
    _write_fake_pe(executable_dir / "ModWatcherAgent.exe")
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


@pytest.mark.parametrize(
    "relative_path",
    [
        "server.key",
        "server.key_backup",
        "signing.pfx.bak",
        "signing.pfx_backup",
        "test_key.pem",
        "id_rsa.bak",
        "id_dsa",
        "id_ed25519.old",
        "id_ecdsa",
        "credentials.json.bak",
        "secrets.json~",
        "private.key.old",
    ],
)
def test_portable_script_rejects_key_material_and_backups(
    tmp_path: Path,
    relative_path: str,
) -> None:
    executable_dir = tmp_path / "bundle" / "ModWatcherAgent"
    executable_dir.mkdir(parents=True)
    _write_fake_pe(executable_dir / "ModWatcherAgent.exe")
    forbidden = executable_dir / relative_path
    forbidden.write_text("private key material", encoding="utf-8")

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
    assert "forbidden" in f"{completed.stdout}\n{completed.stderr}".casefold()


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        ("ModWatcherAgent/server.key", True),
        ("ModWatcherAgent/server.key_backup", True),
        ("ModWatcherAgent/signing.pfx.bak", True),
        ("ModWatcherAgent/signing.pfx_backup", True),
        ("ModWatcherAgent/test_key.pem", True),
        ("ModWatcherAgent/id_rsa.bak", True),
        ("ModWatcherAgent/id_dsa", True),
        ("ModWatcherAgent/id_ed25519.old", True),
        ("ModWatcherAgent/id_ecdsa", True),
        ("ModWatcherAgent/credentials.json.bak", True),
        ("ModWatcherAgent/secrets.json~", True),
        ("ModWatcherAgent/private.key.old", True),
        ("ModWatcherAgent/_internal/certifi/cacert.pem", False),
        ("ModWatcherAgent/_internal/monkey.pem", False),
        ("ModWatcherAgent/_internal/public-key.pem", False),
    ],
)
def test_common_zip_path_policy_rejects_key_material_but_allows_ca_bundle(
    relative_path: str,
    expected: bool,
) -> None:
    assert (
        _invoke_powershell_predicate(
            PACKAGING_COMMON_SCRIPT,
            "Test-ForbiddenDesktopBundlePath",
            RelativePath=relative_path,
            IsDirectory=False,
        )
        is expected
    )


@pytest.mark.parametrize(
    "private_key_header",
    [
        "PRIVATE KEY",
        "RSA PRIVATE KEY",
        "EC PRIVATE KEY",
        "OPENSSH PRIVATE KEY",
    ],
)
def test_portable_rejects_private_key_pem_content_under_arbitrary_name(
    tmp_path: Path,
    private_key_header: str,
) -> None:
    executable_dir = tmp_path / "bundle" / "ModWatcherAgent"
    executable_dir.mkdir(parents=True)
    _write_fake_pe(executable_dir / "ModWatcherAgent.exe")
    (executable_dir / "transport.pem").write_text(
        f"-----BEGIN {private_key_header}-----\nsecret\n",
        encoding="utf-8",
    )

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
    assert "private key" in f"{completed.stdout}\n{completed.stderr}".casefold()


def test_portable_script_rejects_unsafe_version_without_touching_escaped_files(
    tmp_path: Path,
) -> None:
    executable_dir = tmp_path / "bundle" / "ModWatcherAgent"
    executable_dir.mkdir(parents=True)
    _write_fake_pe(executable_dir / "ModWatcherAgent.exe")
    output_dir = tmp_path / "release"
    output_dir.mkdir()
    unsafe_version = r"..\..\..\victim"
    escaped_zip = (output_dir / f"ModWatcherAgent-{unsafe_version}-win-x64-portable.zip").resolve()
    escaped_hash = Path(f"{escaped_zip}.sha256")
    assert escaped_zip.parent != output_dir.resolve()
    escaped_zip.parent.mkdir(parents=True, exist_ok=True)
    escaped_zip.write_bytes(b"keep-zip")
    escaped_hash.write_bytes(b"keep-hash")

    completed = _run_script(
        PORTABLE_SCRIPT,
        "-ExecutableDir",
        str(executable_dir),
        "-OutputDir",
        str(output_dir),
        "-Version",
        unsafe_version,
    )

    assert completed.returncode != 0
    assert "unsafe release version" in f"{completed.stdout}\n{completed.stderr}".casefold()
    assert escaped_zip.read_bytes() == b"keep-zip"
    assert escaped_hash.read_bytes() == b"keep-hash"


def test_portable_rejects_source_inside_staging_before_deleting_input(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "release"
    executable_dir = output_dir / ".portable-staging" / "ModWatcherAgent"
    executable_dir.mkdir(parents=True)
    _write_fake_pe(executable_dir / "ModWatcherAgent.exe")
    sentinel = executable_dir / "caller-owned.txt"
    sentinel.write_text("keep-input", encoding="utf-8")

    completed = _run_script(
        PORTABLE_SCRIPT,
        "-ExecutableDir",
        str(executable_dir),
        "-OutputDir",
        str(output_dir),
        "-Version",
        "9.8.7",
    )

    assert completed.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "keep-input"
    assert "overlap" in f"{completed.stdout}\n{completed.stderr}".casefold()


def test_portable_rejects_output_with_junction_ancestor_before_deleting_input(
    tmp_path: Path,
) -> None:
    real_output_parent = tmp_path / "real-output-parent"
    real_output_parent.mkdir()
    output_alias = tmp_path / "parent-junction-alias"
    _create_directory_junction(output_alias, real_output_parent)
    executable_dir = real_output_parent / "release" / ".portable-staging" / "ModWatcherAgent"
    executable_dir.mkdir(parents=True)
    _write_fake_pe(executable_dir / "ModWatcherAgent.exe")
    sentinel = executable_dir / "caller-owned.txt"
    sentinel.write_text("keep-input", encoding="utf-8")

    try:
        completed = _run_script(
            PORTABLE_SCRIPT,
            "-ExecutableDir",
            str(executable_dir),
            "-OutputDir",
            str(output_alias / "release"),
            "-Version",
            "9.8.7",
        )

        assert completed.returncode != 0
        assert sentinel.read_text(encoding="utf-8") == "keep-input"
        assert "reparse point" in f"{completed.stdout}\n{completed.stderr}".casefold()
    finally:
        if output_alias.exists():
            output_alias.rmdir()


def test_portable_rejects_missing_output_below_junction_before_creation(
    tmp_path: Path,
) -> None:
    real_output_parent = tmp_path / "real-output-parent"
    real_output_parent.mkdir()
    output_alias = tmp_path / "parent-junction-alias"
    _create_directory_junction(output_alias, real_output_parent)
    output_dir = output_alias / "new-release"
    executable_dir = tmp_path / "bundle" / "ModWatcherAgent"
    executable_dir.mkdir(parents=True)
    _write_fake_pe(executable_dir / "ModWatcherAgent.exe")
    sentinel = executable_dir / "caller-owned.txt"
    sentinel.write_text("keep-input", encoding="utf-8")

    try:
        completed = _run_script(
            PORTABLE_SCRIPT,
            "-ExecutableDir",
            str(executable_dir),
            "-OutputDir",
            str(output_dir),
            "-Version",
            "9.8.7",
        )

        assert completed.returncode != 0
        assert sentinel.read_text(encoding="utf-8") == "keep-input"
        assert "reparse point" in f"{completed.stdout}\n{completed.stderr}".casefold()
        assert not output_dir.exists()
    finally:
        if output_alias.exists():
            output_alias.rmdir()


def test_portable_rejects_output_ancestor_before_creating_artifacts(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "release"
    executable_dir = output_dir / "input" / "ModWatcherAgent"
    executable_dir.mkdir(parents=True)
    _write_fake_pe(executable_dir / "ModWatcherAgent.exe")
    sentinel = executable_dir / "caller-owned.txt"
    sentinel.write_text("keep-input", encoding="utf-8")

    completed = _run_script(
        PORTABLE_SCRIPT,
        "-ExecutableDir",
        str(executable_dir),
        "-OutputDir",
        str(output_dir),
        "-Version",
        "9.8.7",
    )

    assert completed.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "keep-input"
    assert "overlap" in f"{completed.stdout}\n{completed.stderr}".casefold()
    assert not (output_dir / ".portable-staging").exists()


@pytest.mark.parametrize(
    ("first_parts", "second_parts", "expected"),
    [
        (("source",), ("source",), True),
        (("source",), ("source", "release"), True),
        (("source", "release"), ("source",), True),
        (("source", "nested", ".."), ("source",), True),
        (("source",), ("source-output",), False),
    ],
)
def test_common_path_overlap_policy_is_canonical_and_separator_aware(
    tmp_path: Path,
    first_parts: tuple[str, ...],
    second_parts: tuple[str, ...],
    expected: bool,
) -> None:
    first = tmp_path.joinpath(*first_parts)
    second = tmp_path.joinpath(*second_parts)

    assert (
        _invoke_powershell_predicate(
            PACKAGING_COMMON_SCRIPT,
            "Test-DesktopPathsOverlap",
            FirstPath=str(first),
            SecondPath=str(second),
        )
        is expected
    )


def test_portable_script_rejects_non_x64_pe(tmp_path: Path) -> None:
    executable_dir = tmp_path / "bundle" / "ModWatcherAgent"
    executable_dir.mkdir(parents=True)
    _write_fake_pe(executable_dir / "ModWatcherAgent.exe", machine=0x014C)

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
    assert "x64 pe" in f"{completed.stdout}\n{completed.stderr}".casefold()


@pytest.mark.parametrize(
    "malformation",
    [
        "truncated-coff-header",
        "missing-optional-header",
        "not-an-executable-image",
        "pe32-not-pe32-plus",
        "truncated-optional-header",
        "zero-sections",
        "missing-section-table",
        "dll-image",
    ],
)
def test_portable_script_rejects_malformed_x64_pe_headers(
    tmp_path: Path,
    malformation: str,
) -> None:
    executable_dir = tmp_path / "bundle" / "ModWatcherAgent"
    executable_path = executable_dir / "ModWatcherAgent.exe"
    if malformation == "truncated-coff-header":
        _write_truncated_x64_pe_header(executable_path)
    elif malformation == "missing-optional-header":
        _write_fake_pe(executable_path, size_of_optional_header=0)
    elif malformation == "not-an-executable-image":
        _write_fake_pe(executable_path, characteristics=0x0020)
    elif malformation == "pe32-not-pe32-plus":
        _write_fake_pe(executable_path, optional_magic=0x010B)
    elif malformation == "truncated-optional-header":
        _write_fake_pe(executable_path, truncate_to=0xA0)
    elif malformation == "zero-sections":
        _write_fake_pe(executable_path, number_of_sections=0)
    elif malformation == "missing-section-table":
        _write_fake_pe(executable_path, include_section_table=False)
    elif malformation == "dll-image":
        _write_fake_pe(executable_path, characteristics=0x2022)
    else:  # pragma: no cover - protects the parameter table
        raise AssertionError(f"Unknown PE malformation: {malformation}")

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
    assert "x64 pe" in f"{completed.stdout}\n{completed.stderr}".casefold()


def test_portable_script_rejects_source_junction_without_copying_external_file(
    tmp_path: Path,
) -> None:
    executable_dir = tmp_path / "bundle" / "ModWatcherAgent"
    executable_dir.mkdir(parents=True)
    _write_fake_pe(executable_dir / "ModWatcherAgent.exe")
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    external_secret = external_dir / "external-secret.txt"
    external_secret.write_text("keep-secret", encoding="utf-8")
    junction = executable_dir / "assets-link"
    _create_directory_junction(junction, external_dir)
    try:
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
        assert "reparse point" in f"{completed.stdout}\n{completed.stderr}".casefold()
        assert external_secret.read_text(encoding="utf-8") == "keep-secret"
    finally:
        if junction.exists():
            junction.rmdir()


@pytest.mark.parametrize(
    "relative_path",
    [
        "data/private-runtime.bin",
        "logs/private-runtime.bin",
        "cache/private-runtime.bin",
        "browser_profiles/profile.json",
        "snapshots/snapshot.json",
        "tests/test_key.pem",
        "private.key",
    ],
)
def test_smoke_rejects_forbidden_bundle_content_before_launch(
    tmp_path: Path,
    relative_path: str,
) -> None:
    bundle_root = tmp_path / "ModWatcherAgent"
    _write_fake_pe(bundle_root / "ModWatcherAgent.exe")
    _write_required_desktop_runtime_files(bundle_root)
    forbidden = bundle_root / relative_path
    forbidden.parent.mkdir(parents=True, exist_ok=True)
    forbidden.write_text("forbidden", encoding="utf-8")

    completed = _run_script(
        SMOKE_SCRIPT,
        "-ExecutablePath",
        str(bundle_root / "ModWatcherAgent.exe"),
        "-TimeoutSeconds",
        "1",
    )

    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}".casefold()
    assert "forbidden" in output or "runtime data escaped" in output


@pytest.mark.parametrize(
    "relative_path",
    [
        "server.key",
        "server.key_backup",
        "signing.pfx.bak",
        "signing.pfx_backup",
        "test_key.pem",
        "id_rsa.bak",
        "id_dsa",
        "id_ed25519.old",
        "id_ecdsa",
        "credentials.json.bak",
        "secrets.json~",
        "private.key.old",
    ],
)
def test_smoke_rejects_key_material_before_launch(
    tmp_path: Path,
    relative_path: str,
) -> None:
    bundle_root = tmp_path / "ModWatcherAgent"
    _write_fake_pe(bundle_root / "ModWatcherAgent.exe")
    _write_required_desktop_runtime_files(bundle_root)
    (bundle_root / relative_path).write_text("private key material", encoding="utf-8")

    completed = _run_script(
        SMOKE_SCRIPT,
        "-ExecutablePath",
        str(bundle_root / "ModWatcherAgent.exe"),
        "-TimeoutSeconds",
        "1",
    )

    assert completed.returncode != 0
    assert "forbidden" in f"{completed.stdout}\n{completed.stderr}".casefold()


def test_smoke_rejects_private_key_pem_content_before_launch(tmp_path: Path) -> None:
    bundle_root = tmp_path / "ModWatcherAgent"
    _write_fake_pe(bundle_root / "ModWatcherAgent.exe")
    _write_required_desktop_runtime_files(bundle_root)
    (bundle_root / "transport.pem").write_text(
        "-----BEGIN ENCRYPTED PRIVATE KEY-----\nsecret\n",
        encoding="utf-8",
    )

    completed = _run_script(
        SMOKE_SCRIPT,
        "-ExecutablePath",
        str(bundle_root / "ModWatcherAgent.exe"),
        "-TimeoutSeconds",
        "1",
    )

    assert completed.returncode != 0
    assert "private key" in f"{completed.stdout}\n{completed.stderr}".casefold()


def test_smoke_rejects_non_x64_pe_before_launch(tmp_path: Path) -> None:
    bundle_root = tmp_path / "ModWatcherAgent"
    _write_fake_pe(bundle_root / "ModWatcherAgent.exe", machine=0x014C)
    _write_required_desktop_runtime_files(bundle_root)

    completed = _run_script(
        SMOKE_SCRIPT,
        "-ExecutablePath",
        str(bundle_root / "ModWatcherAgent.exe"),
        "-TimeoutSeconds",
        "1",
    )

    assert completed.returncode != 0
    assert "x64 pe" in f"{completed.stdout}\n{completed.stderr}".casefold()


def test_build_portable_and_smoke_enforce_windows_x64_pe_contract() -> None:
    common_text = _required_file(PACKAGING_COMMON_SCRIPT).read_text(encoding="utf-8")
    _powershell_ast(PACKAGING_COMMON_SCRIPT)
    assert "function Assert-X64PortableExecutable" in common_text
    assert "0x8664" in common_text
    for script_path in (BUILD_SCRIPT, PORTABLE_SCRIPT, SMOKE_SCRIPT):
        text = script_path.read_text(encoding="utf-8")
        assert "Assert-X64PortableExecutable" in text
        assert "desktop_packaging_common.ps1" in text

    build_text = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "sys.platform == 'win32'" in build_text
    assert "struct.calcsize('P') == 8" in build_text


def test_release_cleanup_removes_only_stale_portable_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    release = repo / "release"
    release.mkdir(parents=True)
    stale_portable = (
        release / "ModWatcherAgent-0.0.0-win-x64-portable.zip",
        release / "ModWatcherAgent-0.0.0-win-x64-portable.zip.sha256",
    )
    for path in stale_portable:
        path.write_bytes(b"stale")
    legacy_installer = release / "ModWatcherAgent-Setup-0.0.0-win-x64.exe"
    legacy_installer.write_bytes(b"keep")
    unknown = release / "release-notes.txt"
    unknown.write_text("keep", encoding="utf-8")

    repo_literal = str(repo).replace("'", "''")
    release_literal = str(release).replace("'", "''")
    completed = _run_powershell_functions(
        BUILD_SCRIPT,
        (
            "Resolve-ControlledReleaseRoot",
            "Assert-ControlledOutputFile",
            "Remove-ControlledFile",
            "Clear-ControlledPortableArtifacts",
        ),
        rf"""
Clear-ControlledPortableArtifacts `
    -RepoRoot '{repo_literal}' `
    -ReleaseRoot '{release_literal}'
""",
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert all(not path.exists() for path in stale_portable)
    assert legacy_installer.read_bytes() == b"keep"
    assert unknown.read_text(encoding="utf-8") == "keep"


def test_release_cleanup_rejects_matching_reparse_point_before_deleting_files(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    release = repo / "release"
    release.mkdir(parents=True)
    stale_file = release / "ModWatcherAgent-0.0.0-win-x64-portable.zip.sha256"
    stale_file.write_bytes(b"keep-until-preflight-passes")
    external = tmp_path / "external"
    external.mkdir()
    external_secret = external / "secret.txt"
    external_secret.write_text("keep-secret", encoding="utf-8")
    junction = release / "ModWatcherAgent-0.0.0-win-x64-portable.zip"
    _create_directory_junction(junction, external)

    repo_literal = str(repo).replace("'", "''")
    release_literal = str(release).replace("'", "''")
    try:
        completed = _run_powershell_functions(
            BUILD_SCRIPT,
            (
                "Resolve-ControlledReleaseRoot",
                "Assert-ControlledOutputFile",
                "Remove-ControlledFile",
                "Clear-ControlledPortableArtifacts",
            ),
            rf"""
Clear-ControlledPortableArtifacts `
    -RepoRoot '{repo_literal}' `
    -ReleaseRoot '{release_literal}'
""",
        )

        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}".casefold()
        assert "reparse point" in output
        assert stale_file.read_bytes() == b"keep-until-preflight-passes"
        assert external_secret.read_text(encoding="utf-8") == "keep-secret"
    finally:
        if junction.exists():
            junction.rmdir()


def test_build_script_rejects_release_junction_before_any_tool_runs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    copied_script = _copy_build_script_fixture(repo)
    pyproject = repo / "backend" / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    fake_python = tools_dir / "python.cmd"
    fake_python.write_text("@exit /b 99\r\n", encoding="ascii")

    external_release = tmp_path / "external-release"
    external_release.mkdir()
    sentinel = external_release / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    release_junction = repo / "release"
    _create_directory_junction(release_junction, external_release)
    try:
        completed = _run_script(
            copied_script,
            "-SkipTests",
            "-SkipFrontendBuild",
            "-SkipSmokeTest",
            "-PythonExecutable",
            str(fake_python),
        )

        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}".casefold()
        assert "release" in output and "reparse point" in output
        assert sentinel.read_text(encoding="utf-8") == "keep"
        assert not (repo / ".venv-desktop-build").exists()
    finally:
        if release_junction.exists():
            release_junction.rmdir()


def test_build_script_preserves_native_tool_exit_code(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    copied_script = _copy_build_script_fixture(repo)
    pyproject = repo / "backend" / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    fake_python = tmp_path / "python.cmd"
    fake_python.write_text("@exit /b 37\r\n", encoding="ascii")

    completed = _run_script(
        copied_script,
        "-SkipTests",
        "-SkipFrontendBuild",
        "-SkipSmokeTest",
        "-SkipPortable",
        "-PythonExecutable",
        str(fake_python),
    )

    assert completed.returncode == 37
    assert "failed with exit code 37" in f"{completed.stdout}\n{completed.stderr}"


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
