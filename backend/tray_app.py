"""
Mod Watcher Agent — System Tray Launcher

在系统托盘中运行，管理后端 uvicorn 和前端 npm run dev 进程。
支持托盘右键菜单：打开面板、打开 API 文档、重启后端、退出。
左键点击图标打开前端面板。
"""

import sys
import os
import argparse
import json
import subprocess
import threading
import time
import socket
import atexit
import logging
from pathlib import Path

try:
    import pystray
except ImportError:
    print(
        "pystray 未安装。请运行:\n"
        "  pip install pystray Pillow\n"
        "  (或 pip install -e . 在 backend 目录安装项目依赖)"
    )
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print(
        "Pillow 未安装。请运行:\n"
        "  pip install Pillow\n"
        "  (或 pip install -e . 在 backend 目录安装项目依赖)"
    )
    sys.exit(1)

# ─────────────────────────────────────────────────
# 路径常量
# ─────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 7500
FRONTEND_DEV_PORT = 7501
DEFAULT_FRONTEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
API_DOCS_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}/docs"
_MUTEX_HANDLE = None
_LOCK_FILE_HANDLE = None

# ── 日志配置 ────────────────────────────────────
LOG_DIR = ROOT_DIR / "log"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOCK_FILE_PATH = LOG_DIR / "mod_watcher_agent.lock"
_STATE_FILE_PATH = LOG_DIR / "service_manager.json"

_tray_logger = logging.getLogger("tray")
_tray_logger.setLevel(logging.INFO)

_fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

_fh = logging.FileHandler(str(LOG_DIR / "tray.log"), encoding="utf-8")
_fh.setFormatter(_fmt)
_tray_logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("[Tray] %(message)s"))
_tray_logger.addHandler(_ch)


class _WindowsJob:
    """Windows job object that keeps service children bound to the manager."""

    def __init__(self) -> None:
        self._handle = None
        if sys.platform != "win32":
            return

        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.argtypes = (
            wintypes.LPVOID,
            wintypes.LPCWSTR,
        )
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.AssignProcessToJobObject.argtypes = (
            wintypes.HANDLE,
            wintypes.HANDLE,
        )
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self._handle = self._kernel32.CreateJobObjectW(None, "ModWatcherAgentServices")
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = self._kernel32.SetInformationJobObject(
            self._handle,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def add(self, proc: subprocess.Popen) -> None:
        if sys.platform != "win32" or not self._handle:
            return
        try:
            ok = self._kernel32.AssignProcessToJobObject(self._handle, proc._handle)
            if not ok:
                error_code = self._ctypes.get_last_error()
                _tray_logger.warning(
                    "子进程 PID=%s 加入 Job Object 失败: WinError %s",
                    proc.pid,
                    error_code,
                )
        except Exception as exc:
            _tray_logger.warning("子进程 PID=%s 加入 Job Object 失败: %s", proc.pid, exc)

    def close(self) -> None:
        if sys.platform != "win32" or not self._handle:
            return
        self._kernel32.CloseHandle(self._handle)
        self._handle = None


# ─────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────

def _check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """检查 TCP 端口是否可连接。"""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _set_windows_process_title(title: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        pass


def _acquire_single_instance() -> bool:
    """Acquire a process-wide single-instance lock for the tray launcher."""
    global _MUTEX_HANDLE, _LOCK_FILE_HANDLE

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        # Use Local namespace by default to avoid admin/session privilege issues.
        for mutex_name in ("Local\\ModWatcherAgentTray", "Global\\ModWatcherAgentTray"):
            handle = kernel32.CreateMutexW(None, False, mutex_name)
            if not handle:
                last_error = ctypes.get_last_error()
                # Access denied on Global namespace is common for non-admin users.
                if last_error == 5:
                    continue
                break
            already_exists = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
            if already_exists:
                kernel32.CloseHandle(handle)
                return False
            _MUTEX_HANDLE = handle
            return True

    def _try_create_lock_file() -> bool:
        global _LOCK_FILE_HANDLE
        _LOCK_FILE_HANDLE = os.open(
            str(_LOCK_FILE_PATH),
            os.O_CREAT | os.O_EXCL | os.O_RDWR,
        )
        os.write(_LOCK_FILE_HANDLE, str(os.getpid()).encode("ascii"))
        return True

    try:
        return _try_create_lock_file()
    except FileExistsError:
        # Recover from stale lock file left by an unclean exit.
        try:
            raw = _LOCK_FILE_PATH.read_text(encoding="utf-8", errors="ignore").strip()
            stale_pid = int(raw) if raw.isdigit() else None
        except Exception:
            stale_pid = None

        if stale_pid and _is_process_running(stale_pid):
            return False

        try:
            _LOCK_FILE_PATH.unlink()
        except Exception:
            return False

        try:
            return _try_create_lock_file()
        except FileExistsError:
            return False


def _release_single_instance() -> None:
    """Release the single-instance lock."""
    global _MUTEX_HANDLE, _LOCK_FILE_HANDLE

    if sys.platform == "win32" and _MUTEX_HANDLE:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(_MUTEX_HANDLE)
        _MUTEX_HANDLE = None
        return

    if _LOCK_FILE_HANDLE is not None:
        os.close(_LOCK_FILE_HANDLE)
        _LOCK_FILE_HANDLE = None
        try:
            _LOCK_FILE_PATH.unlink()
        except FileNotFoundError:
            pass


def _wait_for_port(host: str, port: int, max_wait: float = 30.0) -> bool:
    """等待端口就绪，每秒检查一次。"""
    elapsed = 0.0
    while elapsed < max_wait:
        if _check_port(host, port):
            return True
        time.sleep(1)
        elapsed += 1
    return False


def _open_url(url: str) -> None:
    """Open URL in default browser and bring window to foreground."""
    if sys.platform == "win32":
        subprocess.Popen(
            ["rundll32", "url.dll,FileProtocolHandler", url],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        import webbrowser
        webbrowser.open(url)


def _is_process_running(pid: int | None) -> bool:
    """Return True when a PID is still alive."""
    if not pid or pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes

            process_query_limited_information = 0x1000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32)
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            kernel32.CloseHandle.restype = ctypes.c_bool

            handle = kernel32.OpenProcess(
                process_query_limited_information,
                False,
                int(pid),
            )
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _terminate_process_tree(pid: int | None, name: str) -> None:
    """Terminate a process tree by PID. On Windows this also kills child node/python processes."""
    if not _is_process_running(pid):
        return
    _tray_logger.info("停止 %s 进程树 (PID=%s)...", name, pid)
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                encoding="mbcs",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=15,
            )
            if result.returncode != 0:
                _tray_logger.warning(
                    "taskkill 停止 %s 失败: %s",
                    name,
                    (result.stderr or result.stdout).strip(),
                )
                subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        f"Stop-Process -Id {int(pid)} -Force -ErrorAction SilentlyContinue",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="mbcs",
                    errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=15,
                )
        else:
            os.kill(pid, 15)
    except Exception as exc:
        _tray_logger.error("停止 %s 进程树失败: %s", name, exc)


def _port_owner_pids(port: int) -> set[int]:
    """Return owning process ids for a local TCP port."""
    if sys.platform != "win32":
        return set()
    command = (
        "Get-NetTCPConnection -LocalPort "
        f"{port} -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty OwningProcess -Unique"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10,
        )
        pids = {
            int(line.strip())
            for line in result.stdout.splitlines()
            if line.strip().isdigit()
        }
        if pids:
            return pids
    except Exception as exc:
        _tray_logger.warning("查询端口 %s 占用失败: %s", port, exc)

    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10,
        )
        pids = set()
        marker = f":{port}"
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0].upper() == "TCP" and marker in parts[1]:
                if parts[3].upper() == "LISTENING" and parts[4].isdigit():
                    pids.add(int(parts[4]))
        return pids
    except Exception as exc:
        _tray_logger.warning("netstat 查询端口 %s 占用失败: %s", port, exc)
        return set()


def _kill_port_owners(port: int, label: str, managed_pids: set[int] | None = None) -> None:
    """Kill processes listening on a known application port."""
    managed_pids = managed_pids or set()
    for pid in _port_owner_pids(port):
        if pid <= 0 or pid == os.getpid():
            continue
        if managed_pids and pid in managed_pids:
            continue
        _tray_logger.info("%s 端口 %s 被 PID=%s 占用，清理旧实例", label, port, pid)
        _terminate_process_tree(pid, f"{label}-port-{port}")


def _read_state() -> dict:
    try:
        return json.loads(_STATE_FILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    tmp_path = _STATE_FILE_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(_STATE_FILE_PATH)


def _clear_state() -> None:
    try:
        _STATE_FILE_PATH.unlink()
    except FileNotFoundError:
        pass


def _stop_existing_services() -> None:
    """Stop the recorded manager and any remaining service port owners."""
    state = _read_state()
    manager_pid = state.get("manager_pid")

    current_pid = os.getpid()
    if manager_pid:
        try:
            manager_pid_int = int(manager_pid)
        except (TypeError, ValueError):
            manager_pid_int = None
        if manager_pid_int and manager_pid_int != current_pid and _is_process_running(manager_pid_int):
            _terminate_process_tree(manager_pid_int, "manager")

    _kill_port_owners(BACKEND_PORT, "后端")
    _kill_port_owners(FRONTEND_DEV_PORT, "前端")
    _clear_state()
    _tray_logger.info("已停止记录的服务进程")


def _print_status() -> None:
    """Print current manager state and port readiness for CLI use."""
    state = _read_state()
    print("Mod Watcher Agent service status")
    print(f"  manager_pid : {state.get('manager_pid')}")
    print(f"  backend_pid : {state.get('backend_pid')}")
    print(f"  frontend_pid: {state.get('frontend_pid')}")
    print(f"  backend_port: {'ready' if _check_port(BACKEND_HOST, BACKEND_PORT) else 'stopped'}")
    print(f"  frontend_dev_port: {'ready' if _check_port(BACKEND_HOST, FRONTEND_DEV_PORT) else 'stopped'}")
    print(f"  frontend_url : {state.get('frontend_url') or DEFAULT_FRONTEND_URL}")
    print(f"  tray        : {'enabled' if state.get('use_tray') else 'disabled'}")


def _create_icon_image() -> Image.Image:
    """在内存中生成 32x32 托盘图标：深蓝圆角方块 + 白色 "MW"。"""
    size = 32
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg_color = (25, 55, 109)  # 深蓝
    margin = 2
    radius = 6
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=radius,
        fill=bg_color,
    )

    text = "MW"
    try:
        font = ImageFont.truetype("consola.ttf", 12)
    except OSError:
        try:
            font = ImageFont.truetype("cour.ttf", 11)
        except OSError:
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2
    y = (size - text_h) // 2 - 1
    draw.text((x, y), text, fill=(255, 255, 255), font=font)

    return img


# ─────────────────────────────────────────────────
# TrayApp
# ─────────────────────────────────────────────────

class TrayApp:
    """系统托盘应用程序，管理后端和前端进程。"""

    def __init__(self, use_tray: bool = True, open_browser: bool = True, frontend_mode: str = "static"):
        self.backend_proc = None
        self.frontend_proc = None
        self.icon = None
        self.scheduler_paused = False
        self.use_tray = use_tray
        self.open_browser = open_browser
        self.frontend_mode = frontend_mode
        self.frontend_port = FRONTEND_DEV_PORT if frontend_mode == "dev" else BACKEND_PORT
        self.frontend_url = f"http://{BACKEND_HOST}:{self.frontend_port}"
        self.app_title = "Mod Watcher Agent (Dev)" if frontend_mode == "dev" else "Mod Watcher Agent"
        self.service_job = _WindowsJob()

    # ── 子进程启动 ──────────────────────────────

    def _subprocess_kwargs(self) -> dict:
        """返回 Windows 子进程隐藏控制台窗口的参数。"""
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            kwargs["startupinfo"] = startupinfo
        return kwargs

    def launch_backend(self):
        """启动 uvicorn 后端子进程。"""
        if _check_port(BACKEND_HOST, BACKEND_PORT):
            _tray_logger.info("后端端口已就绪，跳过启动后端")
            return
        _kill_port_owners(BACKEND_PORT, "后端")
        _tray_logger.info("启动后端: %s:%s", BACKEND_HOST, BACKEND_PORT)
        backend_log = (LOG_DIR / "backend_service.log").open("a", encoding="utf-8")
        backend_log.write("\n=== starting backend service ===\n")
        backend_log.flush()
        self.backend_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                BACKEND_HOST,
                "--port",
                str(BACKEND_PORT),
            ],
            cwd=str(BACKEND_DIR),
            env={**os.environ, "MOD_WATCHER_PROCESS_NAME": "ModWatcherBackend"},
            stdout=backend_log,
            stderr=subprocess.STDOUT,
            **self._subprocess_kwargs(),
        )
        self.service_job.add(self.backend_proc)
        self._save_state()

    def launch_frontend(self):
        """启动 npm run dev 前端子进程（仅 dev 模式）。"""
        if self.frontend_mode != "dev":
            _tray_logger.info("前端 static 模式由后端托管，跳过 dev server")
            return
        if _check_port(BACKEND_HOST, FRONTEND_DEV_PORT):
            _tray_logger.info("前端端口已就绪，跳过启动前端")
            return
        _kill_port_owners(FRONTEND_DEV_PORT, "前端")
        _tray_logger.info("启动前端: npm run dev")
        frontend_log = (LOG_DIR / "frontend_service.log").open("a", encoding="utf-8")
        frontend_log.write("\n=== starting frontend service ===\n")
        frontend_log.flush()
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        self.frontend_proc = subprocess.Popen(
            [
                npm_cmd,
                "run",
                "dev",
            ],
            cwd=str(FRONTEND_DIR),
            env={**os.environ, "MOD_WATCHER_PROCESS_NAME": "ModWatcherFrontend"},
            stdout=frontend_log,
            stderr=subprocess.STDOUT,
        )
        self.service_job.add(self.frontend_proc)
        self._save_state()

    # ── 托盘菜单操作 ────────────────────────────

    def _open_panel(self, icon, item):
        """打开前端面板。"""
        _open_url(self.frontend_url)

    def _open_api_docs(self, icon, item):
        """打开 API 文档。"""
        _open_url(API_DOCS_URL)

    def _restart_backend(self, icon, item):
        """重启后端进程。"""
        _tray_logger.info("重启后端...")
        self._terminate_proc(self.backend_proc, "backend")
        self.backend_proc = None
        _kill_port_owners(BACKEND_PORT, "后端")
        self.launch_backend()

    def _exit_app(self, icon, item):
        """退出托盘。"""
        _tray_logger.info("退出...")
        self.stop()

    # ── HTTP API 工具 ───────────────────────────

    def _api_post(self, path: str) -> dict:
        """发送 POST 请求到后端 API，返回 JSON 字典。"""
        import urllib.request
        import json

        url = f"http://{BACKEND_HOST}:{BACKEND_PORT}/api{path}"
        try:
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            _tray_logger.error("API 调用失败: %s - %s", url, e)
            return {"error": str(e)}

    # ── 新增托盘菜单操作 ────────────────────────

    def _check_new_mods(self, icon, item):
        """立即检查新 Mod（后台线程）。"""
        def _run():
            _tray_logger.info("触发立即检查新 Mod")
            result = self._api_post("/jobs/discover-all")
            if self.icon:
                if "error" in result:
                    self.icon.notify(
                        f"检查失败: {result['error']}",
                        self.app_title,
                    )
                else:
                    self.icon.notify(
                        "已触发新 Mod 发现任务，稍后查看结果",
                        self.app_title,
                    )
        threading.Thread(target=_run, daemon=True).start()

    def _check_favorites(self, icon, item):
        """查看收藏更新（后台线程）。"""
        def _run():
            _tray_logger.info("触发查看收藏更新")
            result = self._api_post("/jobs/check-favorites")
            if self.icon:
                if "error" in result:
                    self.icon.notify(
                        f"检查失败: {result['error']}",
                        self.app_title,
                    )
                else:
                    self.icon.notify(
                        "已触发收藏更新检查，稍后查看结果",
                        self.app_title,
                    )
        threading.Thread(target=_run, daemon=True).start()

    def _toggle_pause(self, icon, item):
        """切换暂停/恢复检查。"""
        self.scheduler_paused = not self.scheduler_paused
        if self.scheduler_paused:
            _tray_logger.info("暂停调度检查")
            self._api_post("/jobs/pause")
        else:
            _tray_logger.info("恢复调度检查")
            self._api_post("/jobs/resume")

        if self.icon:
            msg = "调度检查已暂停" if self.scheduler_paused else "调度检查已恢复"
            self.icon.notify(msg, self.app_title)
            self.icon.update_menu(self._build_menu())

    def _open_settings(self, icon, item):
        """打开设置页面。"""
        _open_url(f"{self.frontend_url}/settings")

    # ── 菜单构建 ────────────────────────────────

    def _build_menu(self) -> pystray.Menu:
        """构建完整的托盘右键菜单。"""
        return pystray.Menu(
            pystray.MenuItem("打开面板", self._open_panel, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("立即检查新 Mod", self._check_new_mods),
            pystray.MenuItem("查看收藏更新", self._check_favorites),
            pystray.MenuItem(
                lambda _: "恢复检查" if self.scheduler_paused else "暂停检查",
                self._toggle_pause,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("设置", self._open_settings),
            pystray.MenuItem("打开 API 文档", self._open_api_docs),
            pystray.MenuItem("重启后端", self._restart_backend),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._exit_app),
        )

    # ── 生命周期 ────────────────────────────────

    def start(self):
        """主入口：启动子进程，打开浏览器，然后进入托盘事件循环。"""
        self._cleanup_stale_state()

        self.launch_backend()

        frontend_ready = self.frontend_mode != "dev"
        if _wait_for_port(BACKEND_HOST, BACKEND_PORT):
            _tray_logger.info("后端就绪")
            if self.frontend_mode == "dev":
                self.launch_frontend()
                if _wait_for_port(BACKEND_HOST, FRONTEND_DEV_PORT):
                    _tray_logger.info("前端就绪")
                    frontend_ready = True
                else:
                    _tray_logger.warning("⚠ 前端启动超时 (30s)")
            else:
                frontend_ready = True
        else:
            _tray_logger.warning("⚠ 后端启动超时 (30s)")

        if not frontend_ready:
            self._log_failed_child_status()
            self.stop()
            raise SystemExit(1)

        if frontend_ready:
            _tray_logger.info("打开前端面板: %s", self.frontend_url)
        else:
            _tray_logger.info("前端未确认就绪，仍尝试打开面板: %s", self.frontend_url)
        if self.open_browser:
            _open_url(self.frontend_url)

        if not self.use_tray:
            atexit.register(self._cleanup)
            _tray_logger.info("控制台管理器已启动。按 Ctrl+C 停止所有服务。")
            try:
                while True:
                    self._save_state()
                    time.sleep(5)
            except KeyboardInterrupt:
                _tray_logger.info("收到退出信号")
                self.stop()
            return

        menu = self._build_menu()

        icon_img = _create_icon_image()
        self.icon = pystray.Icon(
            "mod_watcher_agent",
            icon_img,
            self.app_title,
            menu,
        )

        atexit.register(self._cleanup)
        _tray_logger.info("托盘已启动 — 右键图标查看菜单")
        self.icon.run()

    def _log_failed_child_status(self) -> None:
        """Log child process exit codes and the latest captured service output."""
        for name, proc, log_name in (
            ("backend", self.backend_proc, "backend_service.log"),
            ("frontend", self.frontend_proc, "frontend_service.log"),
        ):
            if proc is not None and proc.poll() is not None:
                _tray_logger.error("%s 子进程已退出，退出码=%s", name, proc.returncode)
            log_path = LOG_DIR / log_name
            if log_path.exists():
                try:
                    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    for line in lines[-20:]:
                        _tray_logger.error("%s 日志: %s", name, line)
                except OSError as exc:
                    _tray_logger.error("读取 %s 失败: %s", log_path, exc)

    def stop(self):
        """停止所有子进程并退出托盘。"""
        self._terminate_proc(self.backend_proc, "backend")
        self._terminate_proc(self.frontend_proc, "frontend")
        self.service_job.close()
        _kill_port_owners(BACKEND_PORT, "后端")
        _kill_port_owners(FRONTEND_DEV_PORT, "前端")
        state = _read_state()
        if state.get("manager_pid") == os.getpid():
            _clear_state()
        if self.icon:
            self.icon.stop()

    def _terminate_proc(self, proc, name: str):
        """优雅终止子进程：先 terminate()，超时则 kill()。"""
        if proc is None:
            return
        _terminate_process_tree(proc.pid, name)
        self._save_state()

    def _wait_and_launch_frontend(self):
        """后台线程：等待后端就绪，然后启动前端。"""
        if self.frontend_mode != "dev":
            return
        if _wait_for_port(BACKEND_HOST, BACKEND_PORT):
            _tray_logger.info("后端就绪")
            self.launch_frontend()
        else:
            _tray_logger.warning("⚠ 后端启动超时 (30s)")
            # 等待图标就绪后显示通知
            time.sleep(1.0)
            for _ in range(5):
                try:
                    if self.icon:
                        self.icon.notify(
                            "后端启动超时，请检查日志",
                            self.app_title,
                        )
                        break
                except Exception:
                    time.sleep(0.5)

    def _cleanup(self):
        """atexit 清理处理器。"""
        self._terminate_proc(self.backend_proc, "backend")
        self._terminate_proc(self.frontend_proc, "frontend")
        self.service_job.close()
        state = _read_state()
        if state.get("manager_pid") == os.getpid():
            _clear_state()
        _release_single_instance()

    def _save_state(self) -> None:
        """Persist managed PIDs so a future launcher can detect or clean stale children."""
        _write_state(
            {
                "manager_pid": os.getpid(),
                "manager_name": "ModWatcherManager",
                "backend_pid": self.backend_proc.pid if self.backend_proc else None,
                "backend_name": "ModWatcherBackend",
                "frontend_pid": self.frontend_proc.pid if self.frontend_proc else None,
                "frontend_name": "ModWatcherFrontend",
                "frontend_url": self.frontend_url,
                "frontend_mode": self.frontend_mode,
                "use_tray": self.use_tray,
                "updated_at": time.time(),
            }
        )

    def _cleanup_stale_state(self) -> None:
        """Clean orphaned managed children from a previous crashed manager."""
        state = _read_state()
        if state:
            _tray_logger.info("清理旧服务状态，当前管理器将重新接管端口")
        _clear_state()
        _kill_port_owners(BACKEND_PORT, "后端")
        _kill_port_owners(FRONTEND_DEV_PORT, "前端")


# ─────────────────────────────────────────────────
# 入口点
# ─────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mod Watcher Agent service manager")
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Run in the foreground without a system tray icon.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the frontend URL after services are ready.",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop the recorded manager and service process trees.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print recorded service state and port readiness.",
    )
    parser.add_argument(
        "--frontend-mode",
        choices=["static", "dev"],
        default="static",
        help="Frontend serving mode: static (backend hosted) or dev (npm run dev).",
    )
    args = parser.parse_args()
    os.environ["MOD_WATCHER_PROCESS_NAME"] = "ModWatcherManager"
    _set_windows_process_title("ModWatcherManager")

    if args.stop:
        _stop_existing_services()
        sys.exit(0)

    if args.status:
        _print_status()
        sys.exit(0)

    if not _acquire_single_instance():
        state = _read_state()
        requested_mode = args.frontend_mode
        requested_use_tray = not args.no_tray
        existing_mode = state.get("frontend_mode") or "static"
        existing_use_tray = bool(state.get("use_tray"))
        backend_ready = _check_port(BACKEND_HOST, BACKEND_PORT)
        requested_frontend_ready = (
            backend_ready
            if requested_mode != "dev"
            else _check_port(BACKEND_HOST, FRONTEND_DEV_PORT)
        )
        tray_requirement_met = (not requested_use_tray) or existing_use_tray

        if existing_mode == requested_mode and backend_ready and requested_frontend_ready and tray_requirement_met:
            _tray_logger.info("检测到已有健康实例，打开前端并退出")
            if not args.no_browser:
                _open_url(state.get("frontend_url") or DEFAULT_FRONTEND_URL)
            sys.exit(0)

        _tray_logger.warning(
            "检测到已有实例但模式、托盘或端口状态不匹配 (existing=%s/%s, requested=%s/%s)，清理后接管",
            existing_mode,
            "tray" if existing_use_tray else "no-tray",
            requested_mode,
            "tray" if requested_use_tray else "no-tray",
        )
        _stop_existing_services()
        if not _acquire_single_instance():
            _tray_logger.error("无法接管实例，请手动结束残留 python 进程后重试")
            sys.exit(1)

    app = TrayApp(
        use_tray=not args.no_tray,
        open_browser=not args.no_browser,
        frontend_mode=args.frontend_mode,
    )
    app.start()
