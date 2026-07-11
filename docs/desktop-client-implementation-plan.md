# Mod Watcher Agent Windows Desktop Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a Windows 10/11 x64 desktop client that runs FastAPI in-process, renders the existing React application in pywebview/WebView2, remains available in the system tray, stores writable state under `%LOCALAPPDATA%`, migrates legacy SQLite data safely, and ships as PyInstaller onedir portable and Inno Setup artifacts from GitHub Actions.

**Architecture:** Add a new `backend/desktop_app.py` entry point and focused `app.desktop` components. The legacy `backend/tray_app.py` remains the browser/source launcher and is not rewritten because it currently contains unrelated uncommitted lifecycle work. Runtime paths are configured before importing `app.config`, `app.db`, or `app.main`; the desktop entry then runs Uvicorn in a non-daemon thread and pywebview on the main thread.

**Tech Stack:** Python 3.11/3.12, FastAPI/Uvicorn, pywebview 6.x, pystray, SQLite Backup API, PyInstaller 6.x onedir, PowerShell, Inno Setup 6, GitHub Actions, React/Vite.

## Global Constraints

- Target Windows 10/11 x64 without requiring a user-installed Python or Node.js runtime.
- Bind the desktop backend only to `127.0.0.1`; the default port remains `17500`.
- Store database, logs, browser profiles, snapshots, WebView state, runtime files, and backups below `%LOCALAPPDATA%\ModWatcherAgent` in frozen mode.
- Preserve source/Docker behavior and do not make `app.main` import desktop-only dependencies.
- Keep the existing React/API contracts, routes, state management, and data structures unchanged.
- Do not modify `backend/tray_app.py` or replace `backend/tests/test_tray_app_lifecycle.py`; both contain pre-existing user work.
- Build onedir first. A onefile executable, auto-updater, DPAPI credentials, Windows service, and named-pipe activation are out of scope.
- Disable the Playwright Chromium installer inside a frozen executable; continue trying system Edge, system Chrome, then an already installed Playwright Chromium.
- Write tests before production code, verify the expected failure, then implement the smallest passing behavior.

---

### Task 1: Runtime path model and desktop environment bootstrap

**Files:**
- Create: `backend/app/runtime_paths.py`
- Create: `backend/tests/test_runtime_paths.py`

**Interfaces:**
- Produces: `RuntimePaths`, `is_frozen()`, `build_runtime_paths()`, `ensure_runtime_directories()`, and `configure_desktop_environment()`.
- `configure_desktop_environment(paths)` sets `MW_DESKTOP_MODE`, `MW_USER_DATA_DIR`, `DATABASE_URL`, `LOG_DIR`, `MW_BROWSER_PROFILE_ROOT`, `MW_SNAPSHOT_ROOT`, `MW_ENV_FILE`, and safe local access variables before backend imports.

- [ ] **Step 1: Write failing source/frozen/override path tests**

```python
def test_frozen_paths_use_local_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "本地 数据"))
    paths = build_runtime_paths(frozen=True, bundle_root=tmp_path / "bundle", executable_dir=tmp_path / "app")
    assert paths.database_path == tmp_path / "本地 数据" / "ModWatcherAgent" / "data" / "mod_watcher.db"
    assert paths.frontend_dist_dir == tmp_path / "bundle" / "frontend" / "dist"

def test_desktop_environment_is_local_only(monkeypatch, tmp_path):
    paths = build_runtime_paths(frozen=True, bundle_root=tmp_path / "bundle", executable_dir=tmp_path)
    configure_desktop_environment(paths)
    assert os.environ["MW_BIND_HOST"] == "127.0.0.1"
    assert os.environ["MW_ALLOW_LAN"] == "false"
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_runtime_paths.py -q`

Expected: import failure for `app.runtime_paths`.

- [ ] **Step 3: Implement the immutable path model**

```python
@dataclass(frozen=True)
class RuntimePaths:
    bundle_root: Path
    executable_dir: Path
    user_root: Path
    data_dir: Path
    config_dir: Path
    log_dir: Path
    cache_dir: Path
    webview_dir: Path
    runtime_dir: Path
    backup_dir: Path
    browser_profile_dir: Path
    snapshot_dir: Path
    database_path: Path
    frontend_dist_dir: Path
    alembic_ini_path: Path

def configure_desktop_environment(paths: RuntimePaths) -> None:
    os.environ.update({
        "MW_DESKTOP_MODE": "true",
        "MW_USER_DATA_DIR": str(paths.user_root),
        "DATABASE_URL": f"sqlite:///{paths.database_path.as_posix()}",
        "LOG_DIR": str(paths.log_dir),
        "MW_BROWSER_PROFILE_ROOT": str(paths.browser_profile_dir),
        "MW_SNAPSHOT_ROOT": str(paths.snapshot_dir),
        "MW_ENV_FILE": str(paths.config_dir / ".env"),
        "MW_BIND_HOST": "127.0.0.1",
        "MW_ALLOW_LAN": "false",
        "LOCAL_ONLY_API": "true",
    })
```

- [ ] **Step 4: Verify GREEN and path creation errors**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_runtime_paths.py -q`

Expected: all runtime path tests pass, including Chinese/space paths and missing `LOCALAPPDATA` fallback.

---

### Task 2: Apply runtime paths to backend resources and health reporting

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/logger.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/browser/page_fetcher.py`
- Modify: `backend/app/api/routes_loverslab_browser.py`
- Create: `backend/tests/test_desktop_runtime_integration.py`

**Interfaces:**
- Consumes: `build_runtime_paths()` from Task 1.
- Produces: `GET /api/health` with `status`, `version`, `database`, `scheduler`, `frontend`, `desktop`, and `packaged` fields.

- [ ] **Step 1: Write failing integration tests**

```python
def test_health_reports_desktop_runtime(client, monkeypatch):
    monkeypatch.setenv("MW_DESKTOP_MODE", "true")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["desktop"] is True

def test_browser_paths_follow_runtime_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MW_BROWSER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("MW_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    assert browser_profile_root() == tmp_path / "profiles"
    assert snapshot_root() == tmp_path / "snapshots"
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_desktop_runtime_integration.py -q`

Expected: `/api/health` or runtime path accessors are missing.

- [ ] **Step 3: Route resource lookups through runtime paths**

```python
env_file = os.getenv("MW_ENV_FILE")
load_dotenv(env_file if env_file else None)

runtime_paths = build_runtime_paths()
FRONTEND_DIST_DIR = runtime_paths.frontend_dist_dir
alembic_ini = runtime_paths.alembic_ini_path
```

The browser module must expose accessors instead of import-time fixed relative paths so tests and desktop bootstrapping can override them safely.

- [ ] **Step 4: Add health state and close the persistent browser during lifespan shutdown**

```python
@app.get("/api/health")
async def health() -> dict[str, object]:
    from app.jobs.scheduler import scheduler
    return {
        "status": "ok",
        "version": app.version,
        "database": "ready" if getattr(app.state, "database_ready", False) else "starting",
        "scheduler": "running" if scheduler.running else "stopped",
        "frontend": "ready" if FRONTEND_DIST_DIR.joinpath("index.html").is_file() else "missing",
        "desktop": parse_bool(os.getenv("MW_DESKTOP_MODE"), default=False),
        "packaged": is_frozen(),
    }
```

- [ ] **Step 5: Verify GREEN and existing local-security tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_desktop_runtime_integration.py backend\tests\test_local_first_routes.py backend\tests\test_security_local_first.py -q`

---

### Task 3: Safe legacy SQLite migration

**Files:**
- Create: `backend/app/desktop/database_migration.py`
- Create: `backend/tests/test_database_migration.py`

**Interfaces:**
- Produces: `MigrationResult`, `legacy_database_candidates(paths, cwd=None)`, and `migrate_legacy_database(paths, candidates=None)`.
- Migration uses `sqlite3.Connection.backup`, runs `PRAGMA integrity_check`, writes `backups/migration.json`, never deletes the source, and removes an incomplete target on failure.

- [ ] **Step 1: Write failing WAL-aware migration and rollback tests**

```python
def test_migration_uses_backup_api_and_preserves_wal_rows(runtime_paths, legacy_db):
    result = migrate_legacy_database(runtime_paths, candidates=[legacy_db])
    assert result.migrated is True
    with sqlite3.connect(runtime_paths.database_path) as db:
        assert db.execute("select count(*) from sample").fetchone() == (2,)
    assert legacy_db.exists()
    assert (runtime_paths.backup_dir / "migration.json").is_file()

def test_failed_integrity_check_removes_partial_target(runtime_paths, corrupt_db):
    with pytest.raises(DatabaseMigrationError):
        migrate_legacy_database(runtime_paths, candidates=[corrupt_db])
    assert not runtime_paths.database_path.exists()
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_database_migration.py -q`

- [ ] **Step 3: Implement backup, integrity validation, metadata, and rollback**

```python
with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(target_path) as target:
    source.backup(target)
    integrity = target.execute("PRAGMA integrity_check").fetchone()
    if integrity != ("ok",):
        raise DatabaseMigrationError(f"integrity_check failed: {integrity!r}")
```

- [ ] **Step 4: Verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_database_migration.py -q`

---

### Task 4: In-process Uvicorn server

**Files:**
- Create: `backend/app/desktop/__init__.py`
- Create: `backend/app/desktop/backend_server.py`
- Create: `backend/tests/test_embedded_backend.py`

**Interfaces:**
- Produces: `EmbeddedBackendServer(host, port, app_factory=None, health_path="/api/health")` with `start()`, `wait_ready(timeout)`, `stop(timeout=10)`, and `error`.

- [ ] **Step 1: Write failing lifecycle tests with a fake Uvicorn server**

```python
def test_server_starts_once_and_stop_is_idempotent(fake_uvicorn):
    server = EmbeddedBackendServer("127.0.0.1", 17500, server_factory=fake_uvicorn)
    server.start()
    with pytest.raises(RuntimeError, match="already started"):
        server.start()
    server.stop()
    server.stop()
    assert fake_uvicorn.instance.should_exit is True

def test_thread_error_is_exposed(fake_uvicorn_that_raises):
    server = EmbeddedBackendServer("127.0.0.1", 17500, server_factory=fake_uvicorn_that_raises)
    server.start()
    server.thread.join(1)
    assert isinstance(server.error, RuntimeError)
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_embedded_backend.py -q`

- [ ] **Step 3: Implement direct app import and non-daemon server thread**

```python
def _run(self) -> None:
    try:
        app = self._app_factory()
        config = uvicorn.Config(app=app, host=self.host, port=self.port, log_config=None, access_log=False)
        self._server = self._server_factory(config)
        self._server.run()
    except BaseException as exc:
        self._error = exc
```

- [ ] **Step 4: Verify GREEN and a real temporary-port integration start/stop**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_embedded_backend.py -q`

---

### Task 5: Desktop lifecycle, native window, tray, and single instance

**Files:**
- Create: `backend/app/desktop/controller.py`
- Create: `backend/app/desktop/window.py`
- Create: `backend/app/desktop/tray.py`
- Create: `backend/app/desktop/single_instance.py`
- Create: `backend/app/desktop/errors.py`
- Create: `backend/desktop_app.py`
- Create: `backend/tests/test_desktop_controller.py`
- Create: `backend/tests/test_single_instance.py`

**Interfaces:**
- `DesktopController(server, window, tray, guard, paths)` is the only coordinator.
- `PyWebViewWindow.run()` calls `webview.start()` on the main thread with `private_mode=False` and `storage_path=paths.webview_dir`.
- `TrayController` calls controller callbacks and reports startup failure before the window is allowed to hide.
- `SingleInstanceGuard` uses `Local\ModWatcherAgentDesktop` on Windows and a lock file in tests/non-Windows environments.

- [ ] **Step 1: Write failing close/minimize/restore/degraded/shutdown tests**

```python
def test_close_hides_when_tray_is_available(controller, window):
    controller.tray_available = True
    assert controller.on_window_closing() is False
    window.hide.assert_called_once()

def test_close_exits_when_tray_failed(controller):
    controller.tray_available = False
    assert controller.on_window_closing() is True

def test_shutdown_is_idempotent(controller):
    controller.shutdown("tray")
    controller.shutdown("window")
    controller.server.stop.assert_called_once()
    controller.guard.release.assert_called_once()
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_desktop_controller.py backend\tests\test_single_instance.py -q`

- [ ] **Step 3: Implement lifecycle states and adapters**

```python
class DesktopState(StrEnum):
    CREATED = "created"
    STARTING_BACKEND = "starting_backend"
    BACKEND_READY = "backend_ready"
    WINDOW_VISIBLE = "window_visible"
    WINDOW_HIDDEN = "window_hidden"
    EXITING = "exiting"
    STOPPED = "stopped"
    FAILED = "failed"
```

`window.events.minimized` hides only when the tray is healthy. `window.events.closing` returns `False` to cancel ordinary close-to-tray and `True` during a real exit. The tray default menu action restores the window; “退出” invokes one idempotent shutdown path.

- [ ] **Step 4: Implement the executable entry order**

```python
paths = build_runtime_paths()
ensure_runtime_directories(paths)
configure_desktop_environment(paths)
guard = SingleInstanceGuard(paths.runtime_dir / "desktop.lock")
if not guard.acquire():
    show_native_error("Mod Watcher Agent", "程序已在运行，请从系统托盘打开。")
    return 0
migrate_legacy_database(paths)
# Import backend application only after all environment variables are configured.
controller = build_desktop_controller(paths=paths, guard=guard)
return controller.start()
```

- [ ] **Step 5: Verify GREEN and pywebview API contract tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_desktop_controller.py backend\tests\test_single_instance.py -q`

---

### Task 6: Desktop dependencies, Playwright frozen behavior, crash logging, and smoke mode

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/services/browser/page_fetcher.py`
- Modify: `backend/app/api/routes_loverslab_browser.py`
- Modify: `backend/desktop_app.py`
- Create: `backend/tests/test_desktop_entry.py`

**Interfaces:**
- Adds optional dependency group `desktop = ["pywebview>=6.0,<7", "pystray>=0.19.5", "Pillow>=10"]` and build tools under a separate `packaging` extra.
- `desktop_app.py --smoke-test` initializes isolated user data, starts the embedded server, verifies `/api/health` and `/`, then shuts down without opening a GUI.
- Frozen `/install-chromium` returns a structured unsupported response instead of recursively launching the desktop EXE.

- [ ] **Step 1: Write failing frozen Chromium and crash-log tests**

```python
def test_frozen_chromium_install_is_disabled(monkeypatch):
    monkeypatch.setattr(runtime_paths, "is_frozen", lambda: True)
    result = BrowserPageFetcher.install_chromium()
    assert result["status"] == "unsupported_in_packaged_app"

def test_crash_log_redacts_secrets(tmp_path):
    write_crash_log(tmp_path, RuntimeError("Bearer secret-token"), state="starting")
    assert "secret-token" not in (tmp_path / "crash.log").read_text(encoding="utf-8")
```

- [ ] **Step 2: Verify RED, implement, then verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_desktop_entry.py backend\app\tests\test_browser_page_fetcher.py -q`

---

### Task 7: PyInstaller onedir and portable build scripts

**Files:**
- Create: `packaging/mod_watcher_agent.spec`
- Create: `scripts/build_desktop.ps1`
- Create: `scripts/smoke_test_desktop.ps1`
- Create: `scripts/package_portable.ps1`
- Create: `build-desktop.bat`
- Create: `backend/tests/test_packaging_contract.py`

**Interfaces:**
- Spec entry: `backend/desktop_app.py`.
- Datas preserve `frontend/dist`, `backend/alembic.ini`, `backend/alembic`, `backend/game_aliases.json`, `docs/mwlogo.png`, `README.md`, and `LICENSE` at runtime-expected destinations.
- Hidden imports include Uvicorn protocols/lifespan, `sqlalchemy.dialects.sqlite`, `pystray._win32`, `webview.platforms.edgechromium`, and `clr`; Qt/GTK/CEF backends are excluded.

- [ ] **Step 1: Write a failing static packaging contract test**

```python
def test_spec_contains_required_runtime_resources(repo_root):
    spec = (repo_root / "packaging" / "mod_watcher_agent.spec").read_text(encoding="utf-8")
    for required in ("frontend/dist", "backend/alembic", "webview.platforms.edgechromium", "pystray._win32"):
        assert required in spec
```

- [ ] **Step 2: Verify RED, add the spec/scripts, then verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_packaging_contract.py -q`

- [ ] **Step 3: Build frontend and onedir from a clean build environment**

Run: `.\scripts\build_desktop.ps1 -SkipInstaller`

Expected: `dist-desktop\ModWatcherAgent\ModWatcherAgent.exe` exists, `--smoke-test` returns zero, and a portable ZIP plus SHA256 is created under `release\`.

---

### Task 8: Inno Setup per-user installer and WebView2 bootstrapper policy

**Files:**
- Create: `packaging/installer/ModWatcherAgent.iss`
- Extend: `scripts/build_desktop.ps1`
- Extend: `backend/tests/test_packaging_contract.py`

**Interfaces:**
- Uses `PrivilegesRequired=lowest` and `DefaultDirName={localappdata}\Programs\ModWatcherAgent`.
- Creates Start Menu and optional desktop shortcuts.
- Includes/runs a Microsoft-signed WebView2 Evergreen bootstrapper only when supplied by the build; otherwise startup provides a clear native error and official installation link.
- Uninstall defaults to retaining `%LOCALAPPDATA%\ModWatcherAgent`; an explicit confirmation is required to remove it.

- [ ] **Step 1: Add failing installer-policy assertions**

```python
def test_installer_is_per_user_and_preserves_data(repo_root):
    iss = (repo_root / "packaging" / "installer" / "ModWatcherAgent.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in iss
    assert "{localappdata}\\Programs\\ModWatcherAgent" in iss
    assert "DeleteUserData" in iss
```

- [ ] **Step 2: Verify RED, implement `.iss`, then compile when `ISCC.exe` is available**

Run: `.\scripts\build_desktop.ps1 -SkipTests`

Expected: `release\ModWatcherAgent-Setup-<version>-win-x64.exe` and SHA256 exist when Inno Setup is installed.

---

### Task 9: GitHub Actions release pipeline and supply-chain checks

**Files:**
- Create: `.github/workflows/desktop-release.yml`
- Extend: `backend/tests/test_packaging_contract.py`

**Interfaces:**
- Trigger: `workflow_dispatch` and tags matching `v*`.
- Windows job uses Python 3.12, Node 24, `npm ci`, backend lint/tests, desktop build/smoke, artifact upload, and tag release upload through `gh`.
- Build output excludes `.env`, databases, WAL/SHM, logs, profiles, snapshots, and secrets; SHA256 files accompany each artifact.

- [ ] **Step 1: Add failing workflow contract assertions**

```python
def test_desktop_release_workflow_has_tag_and_artifact_steps(repo_root):
    workflow = (repo_root / ".github" / "workflows" / "desktop-release.yml").read_text(encoding="utf-8")
    assert 'tags:' in workflow and '"v*"' in workflow
    assert "actions/upload-artifact" in workflow
    assert "scripts/build_desktop.ps1" in workflow
```

- [ ] **Step 2: Verify RED, implement workflow, then verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest backend\tests\test_packaging_contract.py -q`

---

### Task 10: User documentation, risk matrix, and final acceptance map

**Files:**
- Modify: `README.md`
- Modify: `DEPENDENCIES.md`
- Create: `docs/desktop-client.md`
- Create: `docs/desktop-client-acceptance.md`
- Existing: `docs/desktop-client-technical-design.md`

**Interfaces:**
- User guide covers installer/portable startup, close-to-tray behavior, full exit, data/log locations, migration, WebView2/browser requirements, uninstall behavior, troubleshooting, and source-mode compatibility.
- Acceptance document maps every requirement in the technical design to an automated test, build check, or explicit manual Windows matrix item.

- [ ] **Step 1: Update docs without presenting scripts as the end-user launch path**

- [ ] **Step 2: Include the risk matrix with current mitigation and residual manual checks**

- [ ] **Step 3: Run link/placeholder/diff checks**

Run: `$patterns = @('T' + 'BD', 'T' + 'ODO', '待' + '定'); rg -n ($patterns -join '|') README.md DEPENDENCIES.md docs\desktop-client*.md`

Expected: no unresolved placeholders.

---

### Task 11: Full verification and release artifact inspection

**Files:**
- Verify all touched files; do not stage or commit unrelated dirty-worktree changes.

- [ ] **Step 1: Backend test and lint suite**

Run: `.\.venv\Scripts\python.exe -m pytest backend -q`

Run: `.\.venv\Scripts\python.exe -m ruff check backend`

- [ ] **Step 2: Frontend typecheck, tests, and production build**

Run: `npm --prefix frontend run typecheck`

Run: `npm --prefix frontend test -- --run`

Run: `npm --prefix frontend run build`

- [ ] **Step 3: Desktop onedir/portable/installer build**

Run: `.\scripts\build_desktop.ps1`

- [ ] **Step 4: Inspect artifacts for forbidden runtime data**

Assert no artifact contains: `.env`, `*.db`, `*.db-wal`, `*.db-shm`, `logs`, `browser_profiles`, `snapshots`, or API-key fixtures.

- [ ] **Step 5: Smoke test packaged executable**

Run: `.\scripts\smoke_test_desktop.ps1 -ExecutablePath .\dist-desktop\ModWatcherAgent\ModWatcherAgent.exe`

Expected: health, React index, Alembic resource, local database creation, and graceful port release checks pass.

- [ ] **Step 6: Manual acceptance matrix**

Record remaining manual-only checks for Windows 10/11, 100/125/150% DPI, one/two displays, Chinese username, path with spaces, non-admin install, WebView2 missing, close/minimize to tray, tray restore, and full exit.

- [ ] **Step 7: Final worktree and whitespace review**

Run: `git status --short`

Run: `git diff --check`

Expected: no whitespace errors; existing unrelated modifications remain preserved and clearly separated from desktop-client files.
