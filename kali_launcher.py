#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kali Linux Portable Launcher (Windows)
WSL + Win-KeX + VcXsrv/TigerVNC 자동 실행 GUI 클라이언트
PyInstaller: pyinstaller --onefile --windowed --name KaliLauncher kali_launcher.py
"""

from __future__ import annotations

import ctypes
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, scrolledtext, ttk


# ---------------------------------------------------------------------------
# 경로 / 설정
# ---------------------------------------------------------------------------

APP_NAME = "Kali Linux Portable"
APP_VERSION = "1.2.5"
DEFAULT_DISTRO = "kali-linux"
DEFAULT_USER = "kali"
CONFIG_FILENAME = "kali_launcher_config.json"
ICON_FILENAME = "kali_icon.ico"
WSL_FOLDER_NAME = "kali-portable"
DEFAULT_TAR_FILENAME = "kali-final.tar"
TAR_FILENAMES = (DEFAULT_TAR_FILENAME, "kali-fresh.tar", "kali-wsl.tar")
VHDX_FILENAME = "ext4.vhdx"
# Never unregister / never delete VHDX. Portable disks must survive PC moves.

VCXSRV_CANDIDATES = [
    r"C:\Program Files\VcXsrv\vcxsrv.exe",
    r"C:\Program Files (x86)\VcXsrv\vcxsrv.exe",
    r"C:\VcXsrv\vcxsrv.exe",
]

TIGERVNC_VIEWER_CANDIDATES = [
    r"C:\Program Files\TigerVNC\vncviewer.exe",
    r"C:\Program Files (x86)\TigerVNC\vncviewer.exe",
    r"C:\TigerVNC\vncviewer.exe",
]

SESSION_KEX_ARGS = {
    "win": ["--win", "-s"],
    "vnc": ["--vnc", "-s"],
    "esm": ["--esm", "-s"],
}

SESSION_MODE_LABELS = {
    "win": "WIN (TigerVNC 자동)",
    "vnc": "VNC (TigerVNC)",
    "esm": "ESM (Windows RDP)",
}


def get_app_dir() -> str:
    """스크립트 또는 PyInstaller exe가 있는 디렉터리."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_path(filename: str) -> str:
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, filename)
        if os.path.isfile(bundled):
            return bundled
    local = os.path.join(get_app_dir(), filename)
    if os.path.isfile(local):
        return local
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)


def apply_window_icon(window: tk.Tk) -> None:
    icon_path = get_resource_path(ICON_FILENAME)
    if os.path.isfile(icon_path):
        try:
            window.iconbitmap(default=icon_path)
        except tk.TclError:
            pass

    png_path = get_resource_path("kali_icon.png")
    if os.path.isfile(png_path):
        try:
            photo = tk.PhotoImage(file=png_path)
            window.iconphoto(True, photo)
            window._kali_icon_photo = photo  # noqa: SLF001 — GC 방지
        except tk.TclError:
            pass


def _find_tar_in_dirs(dirs: list[str]) -> str | None:
    for directory in dirs:
        if not directory:
            continue
        for name in TAR_FILENAMES:
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                return path
    return None


def _find_config_path(dirs: list[str]) -> str:
    for directory in dirs:
        if not directory:
            continue
        path = os.path.join(directory, CONFIG_FILENAME)
        if os.path.isfile(path):
            return path
    return os.path.join(get_app_dir(), CONFIG_FILENAME)


def resolve_paths() -> dict:
    """
    외장 SSD 등 드라이브 문자가 바뀌어도 동작하도록
    실행 파일 위치에서 상위 폴더를 탐색해 WSL/tar 경로를 자동 계산.
    (dist\\KaliLauncher.exe 처럼 하위 폴더에서 실행해도 동작)
    """
    app_dir = get_app_dir()
    wsl_install_dir: str | None = None
    base_dir: str | None = None
    tar_path: str | None = None

    current = app_dir
    for _ in range(8):
        folder_name = os.path.basename(current).lower()

        if folder_name == WSL_FOLDER_NAME:
            wsl_install_dir = current
            base_dir = os.path.dirname(current)
            tar_path = _find_tar_in_dirs([base_dir, current])
            break

        sibling = os.path.join(current, WSL_FOLDER_NAME)
        if os.path.isdir(sibling):
            wsl_install_dir = sibling
            base_dir = current
            tar_path = _find_tar_in_dirs([current, sibling])
            break

        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    if wsl_install_dir is None:
        parent_dir = os.path.dirname(app_dir)
        wsl_install_dir = os.path.join(app_dir, WSL_FOLDER_NAME)
        base_dir = app_dir
        tar_path = _find_tar_in_dirs([app_dir, parent_dir, os.path.dirname(parent_dir)])

    if not tar_path:
        tar_path = os.path.join(base_dir or app_dir, DEFAULT_TAR_FILENAME)

    config_dirs = [app_dir, wsl_install_dir, base_dir, os.path.dirname(wsl_install_dir)]

    return {
        "app_dir": app_dir,
        "base_dir": base_dir or app_dir,
        "wsl_install_dir": wsl_install_dir,
        "tar_path": tar_path,
        "config_path": _find_config_path(config_dirs),
    }


def apply_config_to_paths(paths: dict, config: dict) -> None:
    if config.get("wsl_install_dir"):
        paths["wsl_install_dir"] = config["wsl_install_dir"]
    if config.get("tar_path"):
        paths["tar_path"] = config["tar_path"]
    elif config.get("tar_filename"):
        base = paths.get("base_dir") or paths["app_dir"]
        paths["tar_path"] = os.path.join(base, config["tar_filename"])


def load_config(paths: dict) -> dict:
    defaults = {
        "distro_name": DEFAULT_DISTRO,
        "wsl_user": DEFAULT_USER,
        "session_mode": "win",
        "kex_args": None,
        "auto_start_xserver": True,
        "shutdown_wsl_before_start": False,
        "stop_kex_before_start": False,
        "clean_kex_before_start": True,
        "auto_launch_vnc_viewer": False,
        "kex_vnc_port": 5901,
        "kex_display": ":1",
        "kex_server_wait_sec": 35,
        "winkex_fullscreen": False,
        "prefer_vcxsrv": False,
        "vnc_ports": [5901, 5902, 5903],
        "vnc_host": "localhost",
        "vnc_viewer_delay_sec": 5,
        "kex_client_delay_sec": 6,
        "fix_xfce_notifyd": True,
        "recover_wsl_on_start": True,
        "shutdown_wsl_on_stop": True,
        "vcxsrv_extra_args": [":0", "-multiwindow", "-clipboard", "-primary", "-wgl", "-dpi", "auto"],
    }
    cfg_path = paths["config_path"]
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                loaded = json.load(f)
            defaults.update({k: v for k, v in loaded.items() if v is not None})
        except (OSError, json.JSONDecodeError):
            pass
    return defaults


def save_config(paths: dict, config: dict) -> None:
    try:
        with open(paths["config_path"], "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Windows 유틸
# ---------------------------------------------------------------------------

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_as_admin() -> None:
    if getattr(sys, "frozen", False):
        target = sys.executable
        params = ""
    else:
        target = sys.executable
        params = f'"{os.path.abspath(__file__)}"'
    ctypes.windll.shell32.ShellExecuteW(None, "runas", target, params, None, 1)


def is_process_running(image_name: str) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return image_name.lower() in (result.stdout or "").lower()
    except OSError:
        return False


def wait_for_path(path: str, timeout: float = 20.0) -> bool:
    """UNC paths under \\\\wsl$\\ can lag until the distro is awake."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if os.path.isfile(path):
                return True
        except OSError:
            pass
        time.sleep(0.4)
    return False


def shell_execute(path: str, params: str, cwd: str | None = None) -> bool:
    """Launch a GUI Win32 app reliably from a windowed (no-console) process."""
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "open",
            path,
            params,
            cwd or safe_windows_cwd(),
            1,  # SW_SHOWNORMAL
        )
        return int(rc) > 32
    except Exception:
        return False


def focus_window_by_process(image_names: list[str]) -> bool:
    """Bring an existing top-level window to the foreground (best-effort)."""
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        SW_RESTORE = 9

        targets = {name.lower().removesuffix(".exe") for name in image_names}
        found_hwnd = wintypes.HWND(0)

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):
            nonlocal found_hwnd
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            hproc = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not hproc:
                return True
            try:
                buf = ctypes.create_unicode_buffer(260)
                size = wintypes.DWORD(260)
                if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                    base = os.path.basename(buf.value).lower().removesuffix(".exe")
                    if base in targets:
                        found_hwnd = hwnd
                        return False
            finally:
                kernel32.CloseHandle(hproc)
            return True

        user32.EnumWindows(_enum, 0)
        if not found_hwnd:
            return False
        if user32.IsIconic(found_hwnd):
            user32.ShowWindow(found_hwnd, SW_RESTORE)
        user32.SetForegroundWindow(found_hwnd)
        return True
    except Exception:
        return False


def find_executable(candidates: list[str], extra_dirs: list[str] | None = None) -> str | None:
    search_dirs = extra_dirs or []
    app_dir = get_app_dir()
    paths = resolve_paths()
    search_dirs.extend([
        app_dir,
        paths.get("base_dir", app_dir),
        os.path.join(app_dir, "tools"),
        os.path.join(app_dir, "TigerVNC"),
        os.path.join(paths.get("base_dir", app_dir), "TigerVNC"),
        os.path.join(app_dir, "VcXsrv"),
    ])

    for path in candidates:
        if os.path.isfile(path):
            return path

    which_name = os.path.basename(candidates[0]) if candidates else ""
    if which_name:
        found = shutil.which(which_name)
        if found:
            return found

    for directory in search_dirs:
        for name in ("vncviewer.exe", "vcxsrv.exe"):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def resolve_kex_args(config: dict) -> list[str]:
    if config.get("kex_args"):
        return list(config["kex_args"])
    mode = config.get("session_mode", "win")
    return list(SESSION_KEX_ARGS.get(mode, SESSION_KEX_ARGS["win"]))


def wait_for_tcp_port(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def wsl_unc_path(distro: str, linux_path: str) -> str | None:
    normalized = linux_path.replace("\\", "/").lstrip("/")
    win_tail = normalized.replace("/", "\\")
    for prefix in (f"\\\\wsl.localhost\\{distro}", f"\\\\wsl$\\{distro}"):
        candidate = f"{prefix}\\{win_tail}"
        if os.path.isfile(candidate):
            return candidate
    return f"\\\\wsl$\\{distro}\\{win_tail}"


def session_mode_label(mode: str) -> str:
    return SESSION_MODE_LABELS.get(mode, mode.upper())


def get_desktop_path() -> str:
    return os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str


def decode_subprocess_output(data: bytes | str | None) -> str:
    """WSL 명령 출력은 Windows에서 UTF-16 LE인 경우가 많음."""
    if not data:
        return ""
    if isinstance(data, str):
        return data.replace("\x00", "").strip()

    if data.startswith(b"\xff\xfe"):
        return data.decode("utf-16").strip()
    if data.startswith(b"\xfe\xff"):
        return data.decode("utf-16-be").strip()
    if len(data) >= 2 and data[1:2] == b"\x00":
        try:
            return data.decode("utf-16-le").replace("\x00", "").strip()
        except UnicodeDecodeError:
            pass

    for encoding in ("utf-8", "cp949"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


def safe_windows_cwd() -> str:
    """
    Never start wsl.exe with cwd on the portable drive.
    WSL maps Windows cwd to /mnt/<drive>/... and external SSDs often hit I/O error 19.
    """
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    if os.path.isdir(system32):
        return system32
    return os.environ.get("TEMP") or os.environ.get("USERPROFILE") or "C:\\"


def run_command(
    cmd: list[str],
    *,
    check: bool = False,
    timeout: float | None = 120.0,
    cwd: str | None = None,
) -> RunResult:
    workdir = cwd or safe_windows_cwd()
    try:
        result = subprocess.run(
            cmd,
            check=check,
            capture_output=True,
            timeout=timeout,
            cwd=workdir,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        return RunResult(
            returncode=124,
            stdout=decode_subprocess_output(exc.stdout),
            stderr=(decode_subprocess_output(exc.stderr) + "\n(timeout)").strip(),
        )
    except FileNotFoundError:
        return RunResult(returncode=127, stdout="", stderr="command not found")

    return RunResult(
        returncode=result.returncode,
        stdout=decode_subprocess_output(result.stdout),
        stderr=decode_subprocess_output(result.stderr),
    )


def start_detached(cmd: list[str], *, cwd: str | None = None) -> None:
    """Fire-and-forget. Do not wait — kex --start may never exit."""
    flags = subprocess.CREATE_NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        cmd,
        cwd=cwd or safe_windows_cwd(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def list_wsl_distros() -> list[str]:
    result = run_command(["wsl", "-l", "-q"], timeout=30)
    names: list[str] = []
    for line in (result.stdout or "").splitlines():
        name = line.strip().lstrip("*").strip()
        if name:
            names.append(name)
    return names


def wsl_exe_path() -> str | None:
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wsl.exe")
    if os.path.isfile(system32):
        return system32
    return shutil.which("wsl")


def is_wsl_usable() -> bool:
    """True when the WSL platform can list distros (feature enabled)."""
    if not wsl_exe_path():
        return False
    result = run_command(["wsl", "-l", "-q"], timeout=20)
    text = f"{result.stdout}\n{result.stderr}".lower().replace("-", "_")
    for marker in (
        "wsl_e_wsl_optional_component",
        "please enable the windows subsystem",
        "the windows subsystem for linux is not installed",
        "wsl2 is not supported",
    ):
        if marker.replace("-", "_") in text:
            return False
    # Empty distro list is still a usable WSL platform.
    return True


def find_vhdx(install_dir: str) -> str | None:
    path = os.path.join(install_dir, VHDX_FILENAME)
    if os.path.isfile(path):
        return path
    return None


# ---------------------------------------------------------------------------
# WSL / X 서버 / KeX
# ---------------------------------------------------------------------------

class KaliLauncher:
    def __init__(self, log_callback):
        self.log = log_callback
        self.paths = resolve_paths()
        self.config = load_config(self.paths)
        apply_config_to_paths(self.paths, self.config)
        self._busy = False

    def _run(self, cmd: list[str], *, check: bool = False, timeout: float | None = 120.0) -> RunResult:
        self.log(f"> {' '.join(cmd)}")
        return run_command(cmd, check=check, timeout=timeout)

    def wsl_distro_exists(self) -> bool:
        distro = self.config["distro_name"].lower()
        for name in list_wsl_distros():
            if name.lower() == distro:
                return True
        return False

    def ensure_wsl_platform(self) -> bool:
        """Install WSL platform if missing. Never touches distro VHDX files."""
        if is_wsl_usable():
            return True

        self.log("WSL이 설치되어 있지 않거나 아직 사용할 수 없습니다.")
        if not is_admin():
            self.log("WSL 자동 설치에는 관리자 권한이 필요합니다.")
            self.log("UAC 창이 뜨면 「예」를 눌러 관리자 권한으로 다시 실행해주세요.")
            run_as_admin()
            return False

        self.log("WSL 플랫폼 설치 중... (배포판은 설치하지 않음, 기존 vhdx 유지)")
        result = self._run(
            ["wsl", "--install", "--no-distribution"],
            timeout=600.0,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            self.log(f"WSL 설치 시도 결과:\n{message or '(출력 없음)'}")
            # Older Windows: enable optional components
            self.log("대체 방법으로 WSL 구성 요소 활성화를 시도합니다...")
            self._run(
                [
                    "dism.exe",
                    "/online",
                    "/enable-feature",
                    "/featurename:Microsoft-Windows-Subsystem-Linux",
                    "/all",
                    "/norestart",
                ],
                timeout=600.0,
            )
            self._run(
                [
                    "dism.exe",
                    "/online",
                    "/enable-feature",
                    "/featurename:VirtualMachinePlatform",
                    "/all",
                    "/norestart",
                ],
                timeout=600.0,
            )

        if is_wsl_usable():
            self.log("WSL 플랫폼 준비 완료.")
            return True

        self.log("WSL 설치 후 PC 재부팅이 필요할 수 있습니다.")
        self.log("재부팅 후 이 런처에서 다시 「Kali Linux 시작」을 눌러주세요.")
        messagebox.showwarning(
            APP_NAME,
            "WSL 설치가 진행되었습니다.\n"
            "재부팅이 필요할 수 있습니다.\n\n"
            "재부팅 후 다시 「Kali Linux 시작」을 눌러주세요.",
        )
        return False

    def import_wsl_if_needed(self) -> bool:
        """
        Register portable Kali for this PC.
        Priority:
          1) already registered
          2) existing ext4.vhdx via --import-in-place (never delete / never overwrite)
          3) tar via --import into empty install dir
        Never calls wsl --unregister. Never deletes *.vhdx.
        """
        if self.wsl_distro_exists():
            self.log("WSL 배포판이 이미 등록되어 있습니다.")
            return True

        install_dir = self.paths["wsl_install_dir"]
        tar_path = self.paths["tar_path"]
        vhdx_path = find_vhdx(install_dir)

        if not is_admin():
            self.log("첫 등록/가져오기에는 관리자 권한이 필요합니다.")
            self.log("UAC 창이 뜨면 「예」를 눌러 관리자 권한으로 다시 실행해주세요.")
            run_as_admin()
            return False

        os.makedirs(install_dir, exist_ok=True)

        # Prefer existing portable disk — critical for other PCs.
        if vhdx_path:
            self.log(f"기존 VHDX 발견 — 삭제하지 않고 등록합니다.\n  {vhdx_path}")
            result = self._run(
                [
                    "wsl",
                    "--import-in-place",
                    self.config["distro_name"],
                    vhdx_path,
                ],
                timeout=300.0,
            )
            if result.returncode == 0 or self.wsl_distro_exists():
                self.log("기존 VHDX 등록 완료 (파일 유지).")
                return True
            message = (result.stderr or result.stdout or "").strip()
            self.log(f"import-in-place 실패:\n{message}")
            self.log("VHDX는 삭제하지 않았습니다. tar 가져오기는 시도하지 않습니다 (덮어쓰기 방지).")
            return False

        if not os.path.isfile(tar_path):
            self.log(f"오류: 등록할 VHDX/tar를 찾을 수 없습니다.\n  vhdx: {install_dir}\\{VHDX_FILENAME}\n  tar: {tar_path}")
            return False

        self.log("처음 실행 — Kali Linux WSL 가져오기 중... (시간이 걸릴 수 있습니다)")
        result = self._run(
            [
                "wsl",
                "--import",
                self.config["distro_name"],
                install_dir,
                tar_path,
                "--version",
                "2",
            ],
            timeout=None,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "알 수 없는 오류").strip()
            if "already exists" in message.lower() or "이미" in message:
                self.log("배포판이 이미 등록되어 있습니다. 계속 진행합니다.")
                return True
            self.log(f"WSL 가져오기 실패:\n{message}")
            return False

        self.log("WSL 가져오기 완료.")
        return True

    def _wsl_output_unhealthy(self, text: str) -> bool:
        lowered = (text or "").lower()
        markers = (
            "input/output error",
            "i/o error",
            "입력/출력",
            "read-only file system",
            "cannot remove",
            "device or resource busy",
        )
        return any(marker in lowered for marker in markers)

    def probe_wsl_health(self) -> bool:
        """False when ext4 is stale (common after unplugging portable SSD while WSL was running)."""
        result = self._run(
            [
                "wsl",
                "--cd",
                "~",
                "-d",
                self.config["distro_name"],
                "-u",
                self.config["wsl_user"],
                "--",
                "bash",
                "-lc",
                "test -r /usr/bin/kex && test -r /usr/lib/win-kex/xstartup && echo OK || echo BAD",
            ],
            timeout=45.0,
        )
        combined = f"{result.stdout}\n{result.stderr}"
        if self._wsl_output_unhealthy(combined):
            return False
        return "OK" in (result.stdout or "")

    def recover_wsl(self) -> bool:
        """Reset WSL VM after portable drive reconnect or I/O errors."""
        self.log("WSL 복구 중... (외장 SSD 재연결 후 필요할 수 있습니다)")
        self._run(["wsl", "--shutdown"], timeout=90.0)
        time.sleep(6)
        wake = self._run(
            [
                "wsl",
                "--cd",
                "~",
                "-d",
                self.config["distro_name"],
                "-u",
                self.config["wsl_user"],
                "--",
                "true",
            ],
            timeout=90.0,
        )
        if wake.returncode != 0 or self._wsl_output_unhealthy(f"{wake.stdout}\n{wake.stderr}"):
            self.log(f"  → WSL 재시작 실패: {(wake.stderr or wake.stdout or '').strip()}")
            return False
        self.log("  → WSL 재시작 완료")
        return True

    def ensure_wsl_healthy(self) -> bool:
        if not self.wsl_distro_exists():
            return True
        if self.probe_wsl_health():
            return True
        if not self.config.get("recover_wsl_on_start", True):
            self.log("오류: WSL 파일시스템에 접근할 수 없습니다.")
            return False
        self.log("WSL 파일시스템 오류 감지 — 자동 복구 시도...")
        if not self.recover_wsl():
            return False
        if self.probe_wsl_health():
            self.log("  → WSL 복구 성공")
            return True
        self.log("오류: WSL이 정상 상태로 복구되지 않았습니다.")
        self.log("  SSD 연결 확인 후 PC 재부팅, 또는 WSL 내부 fsck가 필요할 수 있습니다.")
        return False

    def shutdown_wsl(self) -> None:
        self.log("기존 WSL 세션 정리 중...")
        self._run(["wsl", "--shutdown"], timeout=60.0)

    def prepare_wsl_session(self) -> None:
        if self.config.get("shutdown_wsl_before_start", False):
            self.shutdown_wsl()
            return

        if self.config.get("clean_kex_before_start", True):
            self.log("KeX 세션 정리 중...")
            self._run(self._build_wsl_kex_cmd(["--kill"]), timeout=45.0)
            return

        if not self.config.get("stop_kex_before_start", False):
            return

        self.log("기존 KeX 세션 정리 중...")
        self._run(self._build_wsl_kex_cmd(["--stop"]), timeout=45.0)

    def apply_xfce_fixes(self) -> None:
        """Keep Win-KeX on X11. WSLg Wayland env breaks Xfce 4.20 inside TigerVNC."""
        if not self.config.get("fix_xfce_notifyd", True):
            return

        self.log("Xfce/X11 세션 고정 설정 적용 중...")
        user_script = (
            "mkdir -p ~/.config/autostart ~/.config/environment.d && "
            "printf '[Desktop Entry]\\nHidden=true\\n' > ~/.config/autostart/xfce4-notifyd.desktop && "
            "printf '%s\\n' "
            "'GDK_BACKEND=x11' "
            "'XDG_SESSION_TYPE=x11' "
            "'QT_QPA_PLATFORM=xcb' "
            "> ~/.config/environment.d/win-kex.conf && "
            "printf '%s\\n' "
            "'unset WAYLAND_DISPLAY' "
            "'unset WAYLAND_SOCKET' "
            "'export GDK_BACKEND=x11' "
            "'export XDG_SESSION_TYPE=x11' "
            "'export QT_QPA_PLATFORM=xcb' "
            "> ~/.config/win-kex-env.sh"
        )
        result = self._run(
            [
                "wsl",
                "--cd",
                "~",
                "-d",
                self.config["distro_name"],
                "-u",
                self.config["wsl_user"],
                "--",
                "bash",
                "-lc",
                user_script,
            ],
            timeout=60.0,
        )
        if result.returncode == 0:
            self.log("  → 사용자 X11 환경 설정 완료")
        else:
            self.log("  → 사용자 X11 설정 실패 (계속 진행)")

        # Patch system Win-KeX xstartup once so VNC session unsets Wayland.
        patch = (
            "f=/usr/lib/win-kex/xstartup; "
            "if [ ! -f \"$f\" ]; then echo NO_XSTARTUP; exit 0; fi; "
            "if grep -q 'unset WAYLAND_DISPLAY' \"$f\"; then echo ALREADY; exit 0; fi; "
            "cp -a \"$f\" \"$f.bak-portable\"; "
            "awk 'BEGIN{done=0} "
            "/^export GDK_BACKEND=x11/ && !done {"
            "  print; "
            "  print \"unset WAYLAND_DISPLAY\"; "
            "  print \"unset WAYLAND_SOCKET\"; "
            "  print \"export QT_QPA_PLATFORM=xcb\"; "
            "  done=1; next"
            "} {print}' \"$f\" > \"$f.new\" && mv \"$f.new\" \"$f\" && chmod 755 \"$f\" && echo PATCHED"
        )
        patch_result = self._run(
            [
                "wsl",
                "--cd",
                "~",
                "-d",
                self.config["distro_name"],
                "-u",
                "root",
                "--",
                "bash",
                "-lc",
                patch,
            ],
            timeout=60.0,
        )
        out = (patch_result.stdout or "").strip()
        self.log(f"  → Win-KeX xstartup: {out or patch_result.stderr or 'ok'}")

    def _x11_unix_writable(self) -> bool:
        check = self._run(
            [
                "wsl",
                "--cd",
                "~",
                "-d",
                self.config["distro_name"],
                "-u",
                self.config["wsl_user"],
                "--",
                "bash",
                "-lc",
                "touch /tmp/.X11-unix/.kex_w 2>/dev/null && rm -f /tmp/.X11-unix/.kex_w && echo WRITABLE || echo READONLY",
            ],
            timeout=30.0,
        )
        combined = f"{check.stdout}\n{check.stderr}"
        if self._wsl_output_unhealthy(combined):
            return False
        return "WRITABLE" in (check.stdout or "")

    def _fix_x11_unix_root(self) -> bool:
        fix_script = (
            "if touch /tmp/.X11-unix/.kex_w 2>/dev/null; then "
            "rm -f /tmp/.X11-unix/.kex_w; echo OK; exit 0; fi; "
            "mount -o remount,rw /tmp/.X11-unix 2>/dev/null || true; "
            "if touch /tmp/.X11-unix/.kex_w 2>/dev/null; then "
            "rm -f /tmp/.X11-unix/.kex_w; echo REMOUNT_OK; exit 0; fi; "
            "echo FAIL; exit 1"
        )
        fix = self._run(
            [
                "wsl",
                "--cd",
                "~",
                "-d",
                self.config["distro_name"],
                "-u",
                "root",
                "--",
                "bash",
                "-lc",
                fix_script,
            ],
            timeout=45.0,
        )
        out = (fix.stdout or "").strip()
        if fix.returncode == 0 and ("OK" in out or "REMOUNT_OK" in out):
            self.log(f"  → X11 소켓 준비 완료 ({out or 'ok'})")
            return True
        self.log(f"  → X11 remount 실패: {out or fix.stderr}")
        return False

    def prepare_x11_unix(self) -> bool:
        """
        WSLg mounts /tmp/.X11-unix as read-only. Win-KeX needs it writable.
        After portable SSD reconnect, remount only works once WSL VM is healthy.
        """
        self.log("X11 소켓(/tmp/.X11-unix) 쓰기 가능 여부 확인 중...")
        if self._x11_unix_writable():
            self.log("  → /tmp/.X11-unix 쓰기 가능")
            return True

        self.log("  → 읽기 전용 — root로 remount (sudo 암호 입력 없음)")
        if self._fix_x11_unix_root():
            return True

        if self.config.get("recover_wsl_on_start", True):
            self.log("  → X11 수정 실패 — WSL 재시작 후 재시도...")
            if self.recover_wsl() and self._fix_x11_unix_root():
                return True

        return False

    def detect_and_start_xserver(self) -> None:
        if not self.config.get("auto_start_xserver", True):
            self.log("디스플레이 클라이언트 자동 실행이 비활성화되어 있습니다.")
            return

        mode = self.config.get("session_mode", "win")
        viewer = find_executable(TIGERVNC_VIEWER_CANDIDATES)

        if mode == "win":
            self.log("Win-KeX WIN 모드 — kex가 Win-KeX TigerVNC 클라이언트를 자동 실행합니다.")
            return

        if mode == "vnc":
            if viewer:
                self.log(f"Win-KeX VNC 모드 — kex가 뷰어를 실행합니다. ({viewer})")
            else:
                self.log("Win-KeX VNC 모드 — kex 내장 TigerVNC 클라이언트 사용.")
            return

        if mode == "esm":
            self.log("Win-KeX ESM 모드 — Windows RDP 클라이언트 사용.")
            return

        vcxsrv = find_executable(VCXSRV_CANDIDATES)
        if vcxsrv:
            self._start_vcxsrv(vcxsrv)

    def _build_wsl_kex_cmd(self, kex_args: list[str]) -> list[str]:
        # Strip WSLg Wayland vars so Xfce inside TigerVNC stays on X11.
        quoted = " ".join(shlex.quote(a) for a in kex_args)
        inner = (
            "unset WAYLAND_DISPLAY WAYLAND_SOCKET; "
            "export GDK_BACKEND=x11 XDG_SESSION_TYPE=x11 QT_QPA_PLATFORM=xcb; "
            "[ -f \"$HOME/.config/win-kex-env.sh\" ] && . \"$HOME/.config/win-kex-env.sh\"; "
            f"exec kex {quoted}"
        )
        return [
            "wsl",
            "--cd",
            "~",
            "-d",
            self.config["distro_name"],
            "-u",
            self.config["wsl_user"],
            "--",
            "bash",
            "-lc",
            inner,
        ]

    def _launch_winkex_client(self) -> bool:
        """
        Launch win-kex-win-x64 as a Windows process (not via wsl start-client).

        `kex --win --start-client` starts the GUI through WSL interop, then exits.
        When that short-lived wsl.exe session ends, the TigerVNC window often dies
        immediately — which matches 'client not visible'. Direct Windows launch keeps it alive.
        """
        distro = self.config["distro_name"]
        user = self.config["wsl_user"]

        # Wake distro so \\\\wsl$ paths resolve.
        self._run(
            ["wsl", "--cd", "~", "-d", distro, "-u", user, "--", "true"],
            timeout=30.0,
        )

        client = wsl_unc_path(distro, "/usr/lib/win-kex/TigerVNC/win-kex-win-x64")
        passwd = wsl_unc_path(distro, f"/home/{user}/.config/tigervnc/passwd")
        if not client or not wait_for_path(client, 20):
            self.log("오류: Win-KeX 클라이언트(win-kex-win-x64)를 찾을 수 없습니다.")
            return False
        if not passwd or not wait_for_path(passwd, 20):
            self.log("오류: VNC 비밀번호 파일 없음. WSL에서 kex --passwd 로 설정하세요.")
            return False

        for image_name in ("win-kex-win-x64.exe", "win-kex-win-x64"):
            if is_process_running(image_name):
                subprocess.run(
                    ["taskkill", "/IM", "win-kex-win-x64.exe", "/T", "/F"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                time.sleep(0.5)
                break

        host = self.config.get("vnc_host", "localhost")
        display = self.config.get("kex_display", ":1")
        target = f"{host}{display}"
        fullscreen = "FullScreen=1" if self.config.get("winkex_fullscreen", False) else "FullScreen=0"
        cwd = safe_windows_cwd()
        params = (
            f'-SecurityTypes VeNCrypt,TLSVnc -ReconnectOnError 1 '
            f'-passwd "{passwd}" {fullscreen} {target}'
        )
        args = [
            client,
            "-SecurityTypes",
            "VeNCrypt,TLSVnc",
            "-ReconnectOnError",
            "1",
            "-passwd",
            passwd,
            fullscreen,
            target,
        ]

        self.log(f"Win-KeX 클라이언트 실행: {target}")
        self.log(f"  → {client}")
        self.log("작업 표시줄에서 'TigerVNC' / '(Kai_HT) - TigerVNC' 창을 확인하세요.")

        launched = False
        try:
            subprocess.Popen(args, cwd=cwd)
            launched = True
        except OSError as exc:
            self.log(f"Popen 실패, ShellExecute로 재시도: {exc}")

        if not launched or not any(
            is_process_running(n) for n in ("win-kex-win-x64", "win-kex-win-x64.exe")
        ):
            time.sleep(1)
            if not any(is_process_running(n) for n in ("win-kex-win-x64", "win-kex-win-x64.exe")):
                if shell_execute(client, params, cwd=cwd):
                    launched = True
                else:
                    # Detached via cmd start (survives parent exit).
                    start_cmd = [
                        "cmd",
                        "/c",
                        "start",
                        "WinKeX",
                        client,
                        "-SecurityTypes",
                        "VeNCrypt,TLSVnc",
                        "-ReconnectOnError",
                        "1",
                        "-passwd",
                        passwd,
                        fullscreen,
                        target,
                    ]
                    try:
                        subprocess.Popen(start_cmd, cwd=cwd)
                        launched = True
                    except OSError as exc:
                        self.log(f"클라이언트 실행 실패: {exc}")
                        return False

        for _ in range(10):
            time.sleep(0.5)
            if is_process_running("win-kex-win-x64") or is_process_running("win-kex-win-x64.exe"):
                time.sleep(1)
                if focus_window_by_process(["win-kex-win-x64", "win-kex-win-x64.exe"]):
                    self.log("TigerVNC 창을 앞으로 가져왔습니다.")
                self.log("Win-KeX 클라이언트 실행됨. (비밀번호는 passwd 파일로 자동 입력)")
                return True

        self.log("경고: TigerVNC 프로세스가 아직 보이지 않습니다. 잠시 후 작업 표시줄을 확인하세요.")
        return launched

    def _start_kex_win_split(self, mode: str, kex_args: list[str]) -> bool:
        sound = "-s" in kex_args
        server_args = [f"--{mode}", "--start"]
        if sound:
            server_args.append("-s")

        # Avoid sudo password hang inside kex (read-only /tmp/.X11-unix).
        self.prepare_x11_unix()

        port = int(self.config.get("kex_vnc_port", 5901))
        wait_sec = float(self.config.get("kex_server_wait_sec", 35))

        for attempt in (1, 2):
            cmd = self._build_wsl_kex_cmd(server_args)
            self.log(f"Win-KeX 서버 시작... ({' '.join(server_args)}) [시도 {attempt}/2]")
            self.log(f"> {' '.join(cmd)}")
            # CRITICAL: kex --start often never exits. Never use subprocess.run here.
            # CRITICAL: cwd must NOT be the portable drive (H: → /mnt/h I/O errors).
            try:
                start_detached(cmd, cwd=safe_windows_cwd())
            except OSError as exc:
                self.log(f"서버 시작 실패: {exc}")
                return False

            self.log(f"VNC 서버 대기 중... (localhost:{port}, 최대 {wait_sec:.0f}초)")
            if wait_for_tcp_port("127.0.0.1", port, wait_sec):
                self.log(f"  → VNC 서버 준비 완료 (포트 {port})")
                return self._launch_winkex_client()

            self.log(f"  → 포트 {port} 응답 없음")
            if attempt == 1:
                self.log("  → X11 소켓 재준비 후 한 번 더 시도합니다...")
                self._run(self._build_wsl_kex_cmd(["--kill"]), timeout=45.0)
                self.prepare_x11_unix()

        self.log("오류: VNC 서버가 시작되지 않아 클라이언트를 실행하지 않습니다.")
        self.log("힌트: WSL에서 /tmp/.X11-unix 가 쓰기 가능해야 합니다.")
        return False

    def _start_kex_simple(self, kex_args: list[str]) -> bool:
        cmd = self._build_wsl_kex_cmd(kex_args)
        self.log(f"Win-KeX 시작: {' '.join(kex_args)}")
        self.log("> " + " ".join(cmd))
        try:
            # Do not pipe stdout / CREATE_NO_WINDOW here — ESM/RDP needs a visible client.
            subprocess.Popen(cmd, cwd=safe_windows_cwd())
        except OSError as exc:
            self.log(f"Win-KeX 실행 실패: {exc}")
            return False
        return True

    def start_kex(self) -> bool:
        kex_args = resolve_kex_args(self.config)
        mode = self.config.get("session_mode", "win")
        self.log(f"Win-KeX 시작 중... (모드: {mode}, 인자: {' '.join(kex_args)})")

        if mode == "esm":
            return self._start_kex_simple(kex_args)

        # KeX 3.x: WIN 모드가 TigerVNC 서버+클라이언트 (포트 5901)
        kex_mode = "win" if mode == "vnc" else mode
        if kex_mode == "win":
            return self._start_kex_win_split(kex_mode, kex_args)

        return self._start_kex_simple(kex_args)

    def _open_tigervnc_viewer(self, viewer_path: str, port: int) -> bool:
        host = self.config.get("vnc_host", "localhost")
        target = f"{host}:{port}"
        self.log(f"TigerVNC 뷰어 연결 시도: {target}")
        try:
            subprocess.Popen([viewer_path, target], cwd=os.path.dirname(viewer_path))
            return True
        except OSError as exc:
            self.log(f"  실패: {exc}")
            return False

    def _schedule_tigervnc_viewer(self, viewer_path: str) -> None:
        if not self.config.get("auto_launch_vnc_viewer", False):
            return

        delay = float(self.config.get("vnc_viewer_delay_sec", 8))
        ports = self.config.get("vnc_ports") or [5901, 5902, 5903]

        def worker():
            self.log(f"TigerVNC 수동 연결 대기 중... ({delay:.0f}초)")
            time.sleep(delay)
            if is_process_running("vncviewer.exe"):
                self.log("TigerVNC 뷰어가 이미 실행 중입니다.")
                return
            for port in ports:
                if self._open_tigervnc_viewer(viewer_path, int(port)):
                    time.sleep(2)
                    if is_process_running("vncviewer.exe"):
                        return

        threading.Thread(target=worker, daemon=True).start()

    def _start_vcxsrv(self, vcxsrv_path: str) -> str:
        if is_process_running("vcxsrv.exe"):
            self.log("VcXsrv가 이미 실행 중입니다.")
            return "vcxsrv"

        args = [vcxsrv_path] + self.config.get("vcxsrv_extra_args", [])
        self.log(f"VcXsrv 시작: {vcxsrv_path}")
        subprocess.Popen(
            args,
            cwd=os.path.dirname(vcxsrv_path),
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
        time.sleep(1.5)
        return "vcxsrv"

    def launch(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self.log("=" * 42)
            self.log(f"{APP_NAME} 시작")
            self.log(f"앱 경로: {self.paths['app_dir']}")
            self.log(f"WSL 설치 경로: {self.paths['wsl_install_dir']}")
            vhdx = find_vhdx(self.paths["wsl_install_dir"])
            if vhdx:
                self.log(f"VHDX: {vhdx} (보존)")
            self.log(f"배포판: {self.config['distro_name']} / 사용자: {self.config['wsl_user']}")

            if not self.ensure_wsl_platform():
                return

            if self.wsl_distro_exists():
                if not self.ensure_wsl_healthy():
                    return
                self.prepare_wsl_session()

            if not self.import_wsl_if_needed():
                return

            self.apply_xfce_fixes()
            self.detect_and_start_xserver()

            viewer = find_executable(TIGERVNC_VIEWER_CANDIDATES)
            if viewer and self.config.get("auto_launch_vnc_viewer", False):
                self._schedule_tigervnc_viewer(viewer)

            if not self.start_kex():
                self.log("Win-KeX 실행에 문제가 있었습니다.")
                return

            self.log("완료되었습니다. Kali 데스크톱이 곧 표시됩니다.")
        finally:
            self._busy = False

    def stop_session(self) -> None:
        self.log("=" * 42)
        self.log("Win-KeX / TigerVNC 세션 종료 중...")

        for image_name in ("win-kex-win-x64.exe", "vncviewer.exe"):
            if is_process_running(image_name):
                self.log(f"> taskkill /IM {image_name} /F")
                subprocess.run(
                    ["taskkill", "/IM", image_name, "/T", "/F"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )

        if is_wsl_usable() and self.wsl_distro_exists():
            self._run(self._build_wsl_kex_cmd(["--kill"]), timeout=45.0)
        else:
            self.log("WSL/배포판을 사용할 수 없어 Windows 프로세스만 종료했습니다.")

        if self.config.get("shutdown_wsl_on_stop", True) and is_wsl_usable():
            self.log("WSL 종료 (외장 SSD 분리 전 안전)...")
            self._run(["wsl", "--shutdown"], timeout=60.0)

        self.log("세션 종료 완료. (ext4.vhdx는 삭제하지 않음)")


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.paths = resolve_paths()
        self.config = load_config(self.paths)
        apply_config_to_paths(self.paths, self.config)
        self.launcher = KaliLauncher(self.append_log)

        self.title(APP_NAME)
        self.geometry("520x460")
        self.minsize(480, 360)
        self.configure(bg="#1e1e2e")
        apply_window_icon(self)

        self._setup_style()
        self._build_ui()
        self.mode_var.set(self.config.get("session_mode", "win"))
        self._update_mode_description()
        self._show_paths_on_start()

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        self.option_add("*Font", ("맑은 고딕", 10))
        style.configure("TFrame", background="#1e1e2e")
        style.configure("Title.TLabel", background="#1e1e2e", foreground="#cdd6f4", font=("맑은 고딕", 14, "bold"))
        style.configure("Sub.TLabel", background="#1e1e2e", foreground="#a6adc8", font=("맑은 고딕", 9))
        style.configure("TButton", font=("맑은 고딕", 10))
        style.configure("Accent.TButton", font=("맑은 고딕", 11, "bold"))

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 8))

        self._header_logo = None
        logo_path = get_resource_path("kali_icon.png")
        if os.path.isfile(logo_path):
            try:
                self._header_logo = tk.PhotoImage(file=logo_path)
                if self._header_logo.width() > 40:
                    self._header_logo = self._header_logo.subsample(
                        max(1, self._header_logo.width() // 40)
                    )
                ttk.Label(header, image=self._header_logo).pack(side=tk.LEFT, padx=(0, 10))
            except tk.TclError:
                self._header_logo = None

        title_box = ttk.Frame(header)
        title_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Label(title_box, text=APP_NAME, style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            title_box,
            text="외장 SSD 포터블 WSL · Win-KeX 런처",
            style="Sub.TLabel",
        ).pack(anchor=tk.W)

        mode_row = ttk.Frame(main)
        mode_row.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(mode_row, text="세션 모드:", style="Sub.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        self.mode_var = tk.StringVar(value=self.config.get("session_mode", "win"))
        self.mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self.mode_var,
            values=list(SESSION_MODE_LABELS.keys()),
            state="readonly",
            width=10,
        )
        self.mode_combo.pack(side=tk.LEFT, padx=(0, 8))
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_mode_changed)

        self.mode_desc_label = ttk.Label(mode_row, text="", style="Sub.TLabel")
        self.mode_desc_label.pack(side=tk.LEFT)
        self._update_mode_description()

        btn_row = ttk.Frame(main)
        btn_row.pack(fill=tk.X, pady=(0, 10))

        self.start_btn = ttk.Button(
            btn_row,
            text="Kali Linux 시작",
            style="Accent.TButton",
            command=self.on_start,
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_btn = ttk.Button(
            btn_row,
            text="Kali Linux 정지",
            command=self.on_stop,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            btn_row,
            text="바탕화면 바로가기",
            command=self.on_create_shortcut,
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            btn_row,
            text="경로 새로고침",
            command=self.on_refresh_paths,
        ).pack(side=tk.LEFT)

        self.log_box = scrolledtext.ScrolledText(
            main,
            height=14,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg="#11111b",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            relief=tk.FLAT,
            borderwidth=0,
        )
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.log_box.configure(state=tk.DISABLED)

        footer = ttk.Label(
            main,
            text=f"v{APP_VERSION}  |  드라이브 문자 자동 감지",
            style="Sub.TLabel",
        )
        footer.pack(anchor=tk.E, pady=(8, 0))

    def append_log(self, message: str) -> None:
        def _write():
            self.log_box.configure(state=tk.NORMAL)
            self.log_box.insert(tk.END, message + "\n")
            self.log_box.see(tk.END)
            self.log_box.configure(state=tk.DISABLED)

        self.after(0, _write)

    def _update_mode_description(self) -> None:
        mode = self.mode_var.get()
        self.mode_desc_label.configure(text=session_mode_label(mode))

    def on_mode_changed(self, _event=None) -> None:
        mode = self.mode_var.get()
        if mode not in SESSION_KEX_ARGS:
            return
        self.config["session_mode"] = mode
        self.launcher.config["session_mode"] = mode
        self._update_mode_description()
        save_config(self.paths, self.config)

    def _set_busy(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        self.start_btn.configure(state=state)
        self.stop_btn.configure(state=state)
        self.mode_combo.configure(state="disabled" if busy else "readonly")

    def _show_paths_on_start(self) -> None:
        p = self.paths
        tar_exists = os.path.isfile(p["tar_path"])
        self.append_log(f"실행 위치: {p['app_dir']}")
        self.append_log(f"WSL 경로: {p['wsl_install_dir']}")
        self.append_log(f"tar 파일: {p['tar_path']} {'(있음)' if tar_exists else '(없음 — 파일 위치 확인)'}")
        mode = self.config.get("session_mode", "win")
        self.append_log(f"세션 모드: {session_mode_label(mode)}  →  kex {' '.join(resolve_kex_args(self.config))}")
        if not tar_exists:
            self.append_log(f"  → {p.get('base_dir', '')}\\{DEFAULT_TAR_FILENAME} 에 두었는지 확인하세요.")
        self.append_log("「Kali Linux 시작」 / 「Kali Linux 정지」 버튼을 사용하세요.\n")

    def on_refresh_paths(self) -> None:
        self.paths = resolve_paths()
        self.config = load_config(self.paths)
        apply_config_to_paths(self.paths, self.config)
        self.launcher = KaliLauncher(self.append_log)
        self.mode_var.set(self.config.get("session_mode", "win"))
        self._update_mode_description()
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        self.log_box.configure(state=tk.DISABLED)
        self._show_paths_on_start()

    def on_start(self) -> None:
        if self.launcher._busy:
            return

        mode = self.mode_var.get()
        if mode not in SESSION_KEX_ARGS:
            messagebox.showerror("오류", "올바른 세션 모드를 선택해주세요.")
            return

        self.config["session_mode"] = mode
        self.launcher.config["session_mode"] = mode
        save_config(self.paths, self.config)

        self._set_busy(True)
        self.append_log("\n--- 실행 시작 ---")

        def worker():
            try:
                self.launcher.launch()
            except Exception as exc:
                self.append_log(f"예외 발생: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def on_stop(self) -> None:
        if self.launcher._busy:
            messagebox.showwarning("알림", "시작 작업이 진행 중입니다. 잠시 후 다시 시도하세요.")
            return

        self._set_busy(True)
        self.append_log("\n--- 세션 종료 ---")

        def worker():
            try:
                self.launcher.stop_session()
            except Exception as exc:
                self.append_log(f"예외 발생: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def on_create_shortcut(self) -> None:
        if getattr(sys, "frozen", False):
            target = sys.executable
        else:
            target = os.path.abspath(__file__)

        desktop = get_desktop_path()
        if not os.path.isdir(desktop):
            messagebox.showerror("오류", "바탕화면 경로를 찾을 수 없습니다.")
            return

        shortcut_path = os.path.join(desktop, f"{APP_NAME}.lnk")
        work_dir = os.path.dirname(target)
        icon_path = get_resource_path(ICON_FILENAME)
        if getattr(sys, "frozen", False):
            beside_exe = os.path.join(os.path.dirname(target), ICON_FILENAME)
            if os.path.isfile(beside_exe):
                icon_path = beside_exe

        ps_script = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{shortcut_path}"); '
            f'$s.TargetPath = "{target}"; '
            f'$s.WorkingDirectory = "{work_dir}"; '
            f'$s.Description = "WSL Kali Linux Portable Launcher"; '
        )
        if os.path.isfile(icon_path):
            ps_script += f'$s.IconLocation = "{icon_path},0"; '
        ps_script += f'$s.Save()'

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout)
            self.append_log(f"바탕화면 바로가기 생성: {shortcut_path}")
            messagebox.showinfo("완료", f"바탕화면에 바로가기를 만들었습니다.\n\n{shortcut_path}")
        except Exception as exc:
            messagebox.showerror("오류", f"바로가기 생성 실패:\n{exc}")


def main() -> None:
    # 고해상도 DPI 대응
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
