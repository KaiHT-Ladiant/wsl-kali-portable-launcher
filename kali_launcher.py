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
import re
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
APP_VERSION = "1.2.13"
LXSS_REG_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss"
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
        "kex_server_wait_sec": 60,
        "kex_desktop_wait_sec": 40,
        "winkex_fullscreen": False,
        "prefer_vcxsrv": False,
        "vnc_ports": [5901, 5902, 5903],
        "vnc_host": "localhost",
        "vnc_viewer_delay_sec": 5,
        "kex_client_delay_sec": 6,
        "fix_xfce_notifyd": True,
        "recover_wsl_on_start": True,
        "shutdown_wsl_on_stop": True,
        "auto_install_winkex": False,
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


def windows_path_to_wsl_mnt(path: str) -> str:
    """C:\\Users\\a\\b -> /mnt/c/Users/a/b (for wsl cp, avoids \\\\wsl$)."""
    raw = (path or "").strip().strip('"')
    normalized = raw.replace("/", "\\")
    match = re.match(r"^\\\\[?]\\([A-Za-z]):\\(.*)$", normalized)
    if match:
        letter = match.group(1).lower()
        tail = match.group(2).replace("\\", "/")
        return f"/mnt/{letter}/{tail}"
    match = re.match(r"^([A-Za-z]):\\(.*)$", normalized)
    if match:
        letter = match.group(1).lower()
        tail = match.group(2).replace("\\", "/")
        return f"/mnt/{letter}/{tail}"
    # Last resort for unusual paths (should not happen on Windows launcher runs).
    abs_path = os.path.abspath(raw)
    drive, tail = os.path.splitdrive(abs_path)
    letter = drive.rstrip(":\\/").lower() or "c"
    unix_tail = tail.replace("\\", "/")
    if not unix_tail.startswith("/"):
        unix_tail = "/" + unix_tail
    return f"/mnt/{letter}{unix_tail}"


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
    """
    WSL/콘솔 출력 디코딩.
    wsl.exe는 UTF-16 LE를 쓰는 경우가 많고, 한글 Windows 메시지는
    두 번째 바이트가 0이 아니라 기존 ASCII 휴리스틱만으로는 깨진다.
    """
    if not data:
        return ""
    if isinstance(data, str):
        return data.replace("\x00", "").strip()

    if data.startswith(b"\xff\xfe"):
        return data.decode("utf-16").replace("\x00", "").strip()
    if data.startswith(b"\xfe\xff"):
        return data.decode("utf-16-be").replace("\x00", "").strip()

    candidates: list[str] = []
    encodings: list[str] = []
    null_ratio = data.count(0) / max(1, len(data))
    if len(data) % 2 == 0 and null_ratio >= 0.05:
        encodings.append("utf-16-le")
    encodings.extend(["utf-8", "cp949"])
    if "utf-16-le" not in encodings and len(data) % 2 == 0:
        encodings.append("utf-16-le")

    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            text = data.decode(encoding, errors="replace")
        candidates.append(text.replace("\x00", "").strip())

    if not candidates:
        return data.decode("utf-8", errors="replace").replace("\x00", "").strip()

    def _score(text: str) -> tuple[int, int]:
        replacement = text.count("\ufffd")
        controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\r\n\t")
        hangul = sum(1 for ch in text if "\uac00" <= ch <= "\ud7a3")
        printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
        return (-(replacement + controls), hangul + printable)

    return max(candidates, key=_score)


def normalize_wsl_base_path(path: str | None) -> str:
    """Compare BasePath values across \\\\?\\ prefixes and drive-letter case."""
    value = (path or "").strip().strip('"')
    if value.startswith("\\\\?\\"):
        value = value[4:]
    if not value:
        return ""
    return os.path.normcase(os.path.normpath(value))


def format_wsl_base_path(path: str) -> str:
    normalized = os.path.normpath(path)
    if normalized.startswith("\\\\?\\"):
        return normalized
    return "\\\\?\\" + normalized


def parse_lxss_registry_output(text: str) -> list[dict]:
    """Parse `reg query HKCU\\...\\Lxss /s` into distro entries."""
    entries: list[dict] = []
    current: dict | None = None

    def _flush() -> None:
        nonlocal current
        if current and current.get("guid") and current.get("name"):
            entries.append(current)
        current = None

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("HKEY_") or line.startswith("HKCU"):
            _flush()
            tail = line.rstrip("\\").split("\\")[-1]
            current = {
                "guid_key": line,
                "guid": tail if tail.startswith("{") and tail.endswith("}") else None,
                "name": None,
                "base_path": None,
            }
            continue
        if current is None:
            continue
        match = re.match(r"^(\S+)\s+REG_\w+\s+(.*)$", line)
        if not match:
            continue
        key = match.group(1)
        value = match.group(2)
        key_l = key.lower()
        if key_l == "distributionname":
            current["name"] = value
        elif key_l == "basepath":
            current["base_path"] = value
    _flush()
    return entries


def list_wsl_registry_distros() -> list[dict]:
    result = run_command(["reg", "query", LXSS_REG_KEY, "/s"], timeout=30)
    if result.returncode != 0 and not (result.stdout or "").strip():
        return []
    return parse_lxss_registry_output(result.stdout or "")


def get_wsl_registry_entry(distro_name: str) -> dict | None:
    target = (distro_name or "").lower()
    for entry in list_wsl_registry_distros():
        if (entry.get("name") or "").lower() == target:
            return entry
    return None


def set_wsl_registry_base_path(guid_key: str, install_dir: str) -> RunResult:
    return run_command(
        [
            "reg",
            "add",
            guid_key,
            "/v",
            "BasePath",
            "/t",
            "REG_SZ",
            "/d",
            format_wsl_base_path(install_dir),
            "/f",
        ],
        timeout=30,
    )


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
            "cannot find the path",
            "cannot find the file",
            "the system cannot find",
            "access is denied",
            "device not ready",
            "not a valid",
            "거부되었습니다",
            "경로를 찾을 수 없",
            "파일을 찾을 수 없",
            "디스크가 없습니다",
            "장치를 찾을 수 없",
            "error code",
            "오류 코드",
            "hcs_",
            "wsl_e_",
            "0x800",
            "connection_timeout",
            "시간이 초과",
            "응답을 받지 못",
            "operation timed out",
            "timed out",
        )
        return any(marker in lowered for marker in markers)

    def _is_hcs_timeout(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(
            token in lowered
            for token in (
                "hcs_e_connection_timeout",
                "connection_timeout",
                "응답을 받지 못",
                "시간이 초과",
                "operation timed out",
            )
        )

    def sync_portable_base_path(self) -> bool:
        """
        외장 SSD를 다른 PC에 꽂거나 드라이브 문자가 바뀌면
        HKCU Lxss BasePath가 옛 경로를 가리켜 배포판이 뜨지 않는다.
        VHDX는 삭제/unregister 하지 않고 BasePath만 현재 폴더로 맞춘다.
        """
        install_dir = self.paths["wsl_install_dir"]
        vhdx_path = find_vhdx(install_dir)
        if not vhdx_path or not self.wsl_distro_exists():
            return True

        entry = get_wsl_registry_entry(self.config["distro_name"])
        if not entry or not entry.get("guid_key"):
            self.log("경고: WSL 목록에는 있으나 레지스트리 BasePath를 찾지 못했습니다.")
            return True

        registered = normalize_wsl_base_path(entry.get("base_path"))
        expected = normalize_wsl_base_path(install_dir)
        registered_vhdx = os.path.join(registered, VHDX_FILENAME) if registered else ""
        registered_ok = bool(registered) and os.path.isfile(registered_vhdx)

        if registered == expected and registered_ok:
            return True

        self.log("WSL 등록 경로가 현재 외장 SSD 위치와 다릅니다.")
        self.log(f"  등록됨: {entry.get('base_path') or '(없음)'}")
        self.log(f"  현재:   {install_dir}")
        if registered and not registered_ok:
            self.log("  → 등록된 경로에 ext4.vhdx가 없습니다 (드라이브 문자/PC 변경 가능).")
        self.log("  → VHDX는 유지한 채 BasePath만 현재 위치로 수정합니다.")

        self._run(["wsl", "--shutdown"], timeout=90.0)
        time.sleep(2)
        result = set_wsl_registry_base_path(entry["guid_key"], install_dir)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            self.log(f"  → BasePath 수정 실패: {message or '(출력 없음)'}")
            self.log("  → 관리자 권한 없이 실패했다면, 동일 Windows 계정인지 확인하세요.")
            return False

        self.log("  → BasePath 수정 완료 (ext4.vhdx 보존)")
        return True

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
                "test -x /usr/bin/kex && test -f /usr/lib/win-kex/xstartup && echo OK || echo BAD",
            ],
            timeout=45.0,
        )
        combined = f"{result.stdout}\n{result.stderr}"
        if self._wsl_output_unhealthy(combined):
            detail = (result.stderr or result.stdout or "").strip()
            self.log(f"  → 파일시스템/경로 오류: {detail[:500] or '(메시지 없음)'}")
            return False
        if result.returncode == 124:
            self.log("  → WSL 헬스체크 시간 초과 (탐색기/\\\\wsl$ 접근을 피하고 PC 재부팅을 권장)")
            return False
        if "OK" in (result.stdout or ""):
            return True
        detail = (result.stdout or result.stderr or "").strip()
        self.log(f"  → KeX 헬스체크 실패 (exit {result.returncode}): {detail[:500] or '(출력 없음)'}")
        return False

    def _restart_lxss_manager(self) -> None:
        """Best-effort service bounce after HCS timeouts (may need admin)."""
        self.log("  → LxssManager 서비스 재시작 시도...")
        for args in (
            ["powershell", "-NoProfile", "-Command", "Restart-Service LxssManager -Force -ErrorAction SilentlyContinue"],
            ["net", "stop", "LxssManager"],
        ):
            self._run(args, timeout=60.0)
        time.sleep(2)
        self._run(["net", "start", "LxssManager"], timeout=60.0)
        time.sleep(3)

    def _log_wsl_recovery_hints(self, detail: str) -> None:
        self.log("이 PC에서만 실패할 때 흔한 원인:")
        self.log("  1) 외장 SSD 드라이브 문자가 WSL 등록 경로와 다름 (BasePath)")
        self.log("  2) BIOS/Windows 가상화(Virtual Machine Platform) 미활성")
        self.log("  3) 이전 PC에서 「정지」 없이 SSD를 뽑아 VHDX가 불안정")
        self.log("  4) 다른 창에서 같은 kali-linux 세션이 잠금 중")
        lowered = (detail or "").lower()
        if any(token in lowered for token in ("path", "경로", "cannot find", "찾을 수 없", "disk", "디스크")):
            self.log("힌트: 등록 경로/드라이브 문자 문제 가능성이 큽니다. SSD가 F:로 보이는지 확인하세요.")
        if any(token in lowered for token in ("virtual", "hypervisor", "0x80370102", "가상")):
            self.log("힌트: Windows 기능에서 'Virtual Machine Platform'을 켠 뒤 재부팅하세요.")
        if self._is_hcs_timeout(detail):
            self.log("힌트: HCS_E_CONNECTION_TIMEOUT — WSL VM이 VHDX를 마운트하지 못했습니다.")
            self.log("  · 런처/시작을 반복하지 마세요 (탐색기가 멈출 수 있음).")
            self.log("  · \\\\wsl$ / \\\\wsl.localhost 폴더는 열지 마세요.")
            self.log("  · wsl --shutdown 후 Windows를 한 번 재부팅하세요.")
            self.log("  · 그래도 실패하면 ext4.vhdx 손상 가능 — kali-final.tar로 재등록을 검토하세요.")
        status = self._run(["wsl", "-l", "-v"], timeout=30.0)
        status_text = (status.stdout or status.stderr or "").strip()
        if status_text:
            self.log(f"WSL 상태:\n{status_text}")

    def recover_wsl(self) -> bool:
        """Reset WSL VM after portable drive reconnect or I/O errors."""
        self.log("WSL 복구 중... (외장 SSD 재연결 후 필요할 수 있습니다)")
        if not self.sync_portable_base_path():
            return False

        last_detail = ""
        for attempt in (1, 2, 3):
            self.log(f"  → 복구 시도 {attempt}/3")
            self._run(["wsl", "--shutdown"], timeout=90.0)
            time.sleep(4 + attempt * 4)
            if attempt >= 2:
                self._restart_lxss_manager()

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
            wake_text = f"{wake.stdout}\n{wake.stderr}"
            if wake.returncode == 0 and not self._wsl_output_unhealthy(wake_text):
                self.log("  → WSL 재시작 완료")
                return True

            last_detail = (wake.stderr or wake.stdout or "").strip()
            self.log(f"  → 시도 {attempt} 실패: {last_detail or '(메시지 없음)'}")
            if self._is_hcs_timeout(last_detail) or wake.returncode == 124:
                # Extra hammering makes Explorer/Vmmem worse on external SSDs.
                self.log("  → HCS 타임아웃 — 추가 재시도를 중단하고 안내만 표시합니다.")
                break

        self.log(f"  → WSL 재시작 실패: {last_detail or '(메시지 없음)'}")
        self._log_wsl_recovery_hints(last_detail)
        return False

    def ensure_wsl_healthy(self) -> bool:
        if not self.wsl_distro_exists():
            return True
        if not self.sync_portable_base_path():
            self.log("오류: 포터블 VHDX 경로(BasePath) 동기화에 실패했습니다.")
            return False
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
        self.log("  시작 버튼을 반복하지 말고, SSD 연결 확인 후 PC를 재부팅하세요.")
        self.log("  계속 HCS_E_CONNECTION_TIMEOUT이면 ext4.vhdx 점검 또는 tar 재등록이 필요할 수 있습니다.")
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

    def ensure_winkex_installed(self) -> bool:
        """
        Verify Win-KeX files inside the existing portable VHDX.
        Never deletes/replaces ext4.vhdx. Never downloads a new Kali distro.
        apt install is opt-in only (auto_install_winkex=true).
        """
        self.log("Win-KeX 구성 확인 (기존 VHDX 유지 · 새 Kali 다운로드 없음)")
        check = (
            "echo '--- paths ---'; "
            "ls -la /usr/bin/kex /usr/lib/win-kex /usr/lib/win-kex/xstartup "
            "/usr/lib/win-kex/TigerVNC/win-kex-win-x64 2>&1 | head -40; "
            "echo '--- xstartup detail ---'; "
            "file /usr/lib/win-kex/xstartup 2>&1 || true; "
            "stat /usr/lib/win-kex/xstartup 2>&1 || true; "
            "readlink -f /usr/lib/win-kex/xstartup 2>&1 || true; "
            "missing=''; "
            "test -x /usr/bin/kex || missing=\"$missing kex\"; "
            "test -f /usr/lib/win-kex/xstartup || missing=\"$missing xstartup\"; "
            "test -e /usr/lib/win-kex/TigerVNC/win-kex-win-x64 "
            "|| missing=\"$missing win-kex-win-x64\"; "
            "if command -v Xtigervnc >/dev/null 2>&1 || test -x /usr/bin/Xtigervnc; then "
            "true; else missing=\"$missing Xtigervnc\"; fi; "
            "if [ -z \"$missing\" ]; then echo WINKEX_OK; "
            "else echo WINKEX_MISSING:$missing; fi"
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
                check,
            ],
            timeout=45.0,
        )
        out = (result.stdout or "").strip()
        if out:
            self.log(out[-1200:])
        if "WINKEX_OK" in out:
            self.log("  → Win-KeX 구성 정상 (VHDX 내용 유지)")
            return True

        self.log("  → Win-KeX 파일이 이 VHDX 안에서 확인되지 않습니다.")
        self.log("  → 새 Kali를 받지 않습니다. ext4.vhdx도 삭제/교체하지 않습니다.")
        if not self.config.get("auto_install_winkex", False):
            self.log("힌트: 노트북과 같은 VHDX면 이 PC의 마운트/캐시 문제일 수 있습니다.")
            self.log("  wsl --shutdown 후 다시 시작하세요.")
            self.log("  패키지만 깨졌을 때만 VHDX 안에서: sudo apt install -y kali-win-kex")
            self.log("  자동 apt를 쓰려면 config에 \"auto_install_winkex\": true")
            return False

        self.log("  → auto_install_winkex=true — 같은 VHDX 안에 패키지만 설치")
        install = self._run(
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
                "export DEBIAN_FRONTEND=noninteractive; "
                "apt-get update -y && apt-get install -y kali-win-kex && echo INSTALL_OK || echo INSTALL_FAIL",
            ],
            timeout=900.0,
        )
        install_out = f"{install.stdout}\n{install.stderr}".strip()
        if "INSTALL_OK" in install_out:
            self.log("  → kali-win-kex 설치 완료 (VHDX 교체 없음)")
            return True
        self.log("오류: Win-KeX 복구 실패. VHDX는 그대로 두었습니다.")
        if install_out:
            self.log(f"설치 출력:\n{install_out[-800:]}")
        return False

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
        # IMPORTANT: do not use $f / $short vars in wsl bash -lc strings — on some
        # Windows hosts those get expanded to empty before bash sees them.
        xstartup = "/usr/lib/win-kex/xstartup"
        patch = (
            f"echo \"probe: $(ls -la {xstartup} 2>&1)\"; "
            f"if [ ! -e {xstartup} ]; then echo NO_XSTARTUP; exit 0; fi; "
            f"if [ ! -f {xstartup} ]; then echo NOT_REGULAR_FILE; exit 0; fi; "
            f"if grep -q 'unset WAYLAND_DISPLAY' {xstartup}; then echo ALREADY; exit 0; fi; "
            f"cp -a {xstartup} {xstartup}.bak-portable; "
            "awk 'BEGIN{done=0} "
            "/^export GDK_BACKEND=x11/ && !done {"
            "  print; "
            "  print \"unset WAYLAND_DISPLAY\"; "
            "  print \"unset WAYLAND_SOCKET\"; "
            "  print \"export QT_QPA_PLATFORM=xcb\"; "
            "  done=1; next"
            f"}} {{print}}' {xstartup} > {xstartup}.new "
            f"&& mv {xstartup}.new {xstartup} && chmod 755 {xstartup} && echo PATCHED"
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
        if "NO_XSTARTUP" in out or "NOT_REGULAR_FILE" in out:
            self.log("  → xstartup 패치 건너뜀 (VHDX 삭제/재다운로드 없음). VNC 기동은 계속 시도합니다.")

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

    def _fix_x11_unix_root(self, *, force_recreate: bool = False) -> bool:
        """
        WSLg remounts /tmp/.X11-unix read-only; kex then asks for sudo and fails
        non-interactively. Mount a writable tmpfs over it so kex does not need a password.
        """
        _ = force_recreate
        fix_script = (
            "umount /tmp/.X11-unix 2>/dev/null || true; "
            "rm -rf /tmp/.X11-unix; "
            "mkdir -p /tmp/.X11-unix; "
            "chmod 1777 /tmp/.X11-unix; "
            "chown root:root /tmp/.X11-unix; "
            "mount -t tmpfs -o mode=1777,size=16m winkex-x11 /tmp/.X11-unix "
            "|| mount -t tmpfs -o mode=1777 tmpfs /tmp/.X11-unix || true; "
            "chmod 1777 /tmp/.X11-unix; "
            "if touch /tmp/.X11-unix/.kex_w 2>/dev/null; then "
            "rm -f /tmp/.X11-unix/.kex_w; echo TMPFS_OK; exit 0; fi; "
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
        if fix.returncode == 0 and "TMPFS_OK" in out:
            self.log(f"  → X11 소켓 tmpfs 준비 완료 ({out or 'ok'})")
            return True
        self.log(f"  → X11 소켓 수정 실패: {out or fix.stderr}")
        return False

    def ensure_kex_nopasswd_mount(self) -> None:
        """Allow kex's internal sudo mount/umount without an interactive password."""
        user = self.config["wsl_user"]
        # Avoid $vars in the wsl command string.
        script = (
            f"printf '%s\\n' "
            f"'{user} ALL=(root) NOPASSWD: /bin/mount, /bin/umount, /usr/bin/mount, /usr/bin/umount' "
            f"> /etc/sudoers.d/99-winkex-x11 && "
            f"chmod 440 /etc/sudoers.d/99-winkex-x11 && "
            f"visudo -cf /etc/sudoers.d/99-winkex-x11 >/dev/null 2>&1 && echo SUDOERS_OK || "
            f"(rm -f /etc/sudoers.d/99-winkex-x11; echo SUDOERS_FAIL)"
        )
        result = self._run(
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
                script,
            ],
            timeout=30.0,
        )
        out = (result.stdout or "").strip()
        if "SUDOERS_OK" in out:
            self.log("  → kex용 mount sudo NOPASSWD 설정 완료")
        else:
            self.log(f"  → sudoers 설정 건너뜀: {out or result.stderr or 'ok'}")

    def clean_stale_vnc_state(self) -> None:
        """Remove laptop-hostname pid files / locks that break vncserver on this PC."""
        user = self.config["wsl_user"]
        home = f"/home/{user}"
        script = (
            f"rm -f {home}/.config/tigervnc/*.pid "
            f"{home}/.vnc/*.pid "
            f"/tmp/.X1-lock /tmp/.X2-lock "
            f"/tmp/.X11-unix/X1 /tmp/.X11-unix/X2 2>/dev/null || true; "
            f"mkdir -p {home}/.config/tigervnc {home}/.cache/kali-launcher; "
            f"echo CLEAN_OK"
        )
        result = self._run(
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
                script,
            ],
            timeout=30.0,
        )
        if "CLEAN_OK" in (result.stdout or ""):
            self.log("  → 이전 PC hostname VNC pid/lock 정리 완료")
        else:
            self.log(f"  → VNC 상태 정리 경고: {(result.stderr or result.stdout or '').strip()}")

    def prepare_x11_unix(self) -> bool:
        """
        WSLg mounts /tmp/.X11-unix as read-only. Win-KeX needs it writable.
        After portable SSD reconnect, remount only works once WSL VM is healthy.
        """
        self.log("X11 소켓(/tmp/.X11-unix) 쓰기 가능 여부 확인 중...")
        if self._x11_unix_writable():
            self.log("  → /tmp/.X11-unix 쓰기 가능")
            return True

        self.log("  → 읽기 전용/WSLg 마운트 — root로 복구 (sudo 암호 입력 없음)")
        if self._fix_x11_unix_root():
            return True

        if self.config.get("recover_wsl_on_start", True):
            self.log("  → X11 수정 실패 — WSL 재시작 후 재시도...")
            if self.recover_wsl() and self._fix_x11_unix_root():
                return True

        return False

    def wait_for_kex_desktop(self) -> bool:
        """
        Port 5901 can accept VNC before XFCE finishes starting.
        Connecting early looks like 'connected but blank screen'.
        """
        wait_sec = float(self.config.get("kex_desktop_wait_sec", 40))
        self.log(f"XFCE 데스크톱 준비 대기 중... (최대 {wait_sec:.0f}초)")
        script = (
            "for i in $(seq 1 "
            + str(max(1, int(wait_sec)))
            + "); do "
            "if pgrep -u \"$USER\" -x xfce4-session >/dev/null 2>&1 "
            "|| pgrep -u \"$USER\" -x xfwm4 >/dev/null 2>&1 "
            "|| pgrep -u \"$USER\" -x xfdesktop >/dev/null 2>&1; then "
            "echo DESKTOP_OK; exit 0; fi; "
            "sleep 1; "
            "done; "
            "echo DESKTOP_MISSING; exit 1"
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
                script,
            ],
            timeout=wait_sec + 15.0,
        )
        out = (result.stdout or "").strip()
        if "DESKTOP_OK" in out:
            self.log("  → XFCE 세션 감지됨")
            return True
        self.log("  → XFCE 세션이 아직 없습니다 (VNC만 열린 검정 화면일 수 있음)")
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

    def _build_wsl_kex_cmd(self, kex_args: list[str], *, capture_log: bool = False) -> list[str]:
        # Strip WSLg Wayland vars so Xfce inside TigerVNC stays on X11.
        # Avoid $HOME in the command string — some Windows hosts expand $vars early.
        quoted = " ".join(shlex.quote(a) for a in kex_args)
        home = f"/home/{self.config['wsl_user']}"
        env_file = f"{home}/.config/win-kex-env.sh"
        log_file = f"{home}/.cache/kali-launcher/kex-start.log"
        if capture_log:
            inner = (
                "unset WAYLAND_DISPLAY WAYLAND_SOCKET; "
                "export GDK_BACKEND=x11 XDG_SESSION_TYPE=x11 QT_QPA_PLATFORM=xcb; "
                f"[ -f {shlex.quote(env_file)} ] && . {shlex.quote(env_file)}; "
                f"mkdir -p {shlex.quote(home + '/.cache/kali-launcher')}; "
                f": > {shlex.quote(log_file)}; "
                f"exec >>{shlex.quote(log_file)} 2>&1; "
                f"echo \"==== $(date -Iseconds) kex {quoted} ====\"; "
                f"exec kex {quoted}"
            )
        else:
            inner = (
                "unset WAYLAND_DISPLAY WAYLAND_SOCKET; "
                "export GDK_BACKEND=x11 XDG_SESSION_TYPE=x11 QT_QPA_PLATFORM=xcb; "
                f"[ -f {shlex.quote(env_file)} ] && . {shlex.quote(env_file)}; "
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

    def _wsl_ipv4(self) -> str | None:
        result = self._run(
            [
                "wsl",
                "-d",
                self.config["distro_name"],
                "-u",
                self.config["wsl_user"],
                "--",
                "bash",
                "-lc",
                "hostname -I 2>/dev/null | tr ' ' '\\n' | awk -F. 'NF==4{print; exit}'",
            ],
            timeout=20.0,
        )
        ip = (result.stdout or "").strip().splitlines()
        return ip[0].strip() if ip else None

    def _peek_kex_start_log(self) -> str:
        log_file = f"/home/{self.config['wsl_user']}/.cache/kali-launcher/kex-start.log"
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
                f"tail -n 40 {shlex.quote(log_file)} 2>/dev/null || true",
            ],
            timeout=20.0,
        )
        return (result.stdout or "").strip()

    def _wait_for_vnc_port(self, port: int, wait_sec: float) -> bool:
        """
        Win-KeX/TigerVNC listens on 127.0.0.1 inside WSL. Windows must connect via
        localhost forwarding — NOT the WSL eth0 IP (that yields WSAECONNREFUSED 10061).
        """
        wait_sec = max(float(wait_sec), 45.0)
        # Always force client host back to localhost for Win-KeX.
        self.config["vnc_host"] = "localhost"
        host = "127.0.0.1"
        wsl_ip = self._wsl_ipv4()
        if wsl_ip:
            self.log(f"  → WSL IP: {wsl_ip} (참고용 · 클라이언트는 localhost 사용)")

        self.log(f"VNC 서버 대기 중... (localhost:{port}, 최대 {wait_sec:.0f}초)")
        deadline = time.time() + wait_sec
        last_peek = 0.0
        while time.time() < deadline:
            try:
                with socket.create_connection((host, int(port)), timeout=1.0):
                    self.log(f"  → VNC 응답: localhost:{port}")
                    return True
            except OSError:
                pass
            now = time.time()
            if now - last_peek >= 6.0:
                last_peek = now
                # Also confirm from inside WSL whether Xtigervnc is actually listening.
                listen = self._run(
                    [
                        "wsl",
                        "-d",
                        self.config["distro_name"],
                        "-u",
                        self.config["wsl_user"],
                        "--",
                        "bash",
                        "-lc",
                        f"ss -lntp 2>/dev/null | grep -E ':{port}\\b' || true",
                    ],
                    timeout=15.0,
                )
                listen_out = (listen.stdout or "").strip()
                if listen_out:
                    self.log(f"  → WSL 내부 리스닝 확인:\n{listen_out}")
                    # Server is up inside WSL but Windows localhost not forwarded yet.
                    if "127.0.0.1" in listen_out or "0.0.0.0" in listen_out or ":*" in listen_out:
                        # Give localhost forwarding a moment; still require Windows connect.
                        self.log("  → 서버는 떠 있음. localhost 포워딩 대기 중...")
                peek = self._peek_kex_start_log()
                if peek:
                    lowered = peek.lower()
                    if "win-kex server (win) is stopped" in lowered or "[sudo]" in lowered:
                        self.log("  → kex가 서버를 띄우지 못했습니다 (sudo 암호/X11 읽기전용 가능):")
                        self.log(peek[-700:])
                        return False
                    if any(
                        token in lowered
                        for token in ("error connecting", "can't parse pid", "failed", "denied")
                    ):
                        self.log("  → kex 로그에서 오류 감지:")
                        self.log(peek[-600:])
            time.sleep(0.4)
        return False

    def _diagnose_kex_server_failure(self) -> None:
        self.log("VNC 서버 실패 진단 중... (VHDX 재다운로드 아님)")
        script = (
            "echo '--- kex --status ---'; "
            "kex --status 2>&1 || true; "
            "echo '--- listeners ---'; "
            "ss -lntp 2>/dev/null | grep -E '590[0-9]|tiger|vnc' || "
            "netstat -lntp 2>/dev/null | grep -E '590[0-9]' || true; "
            "echo '--- processes ---'; "
            "pgrep -af 'Xtigervnc|tigervnc|win-kex|kex' 2>/dev/null || true; "
            "echo '--- xstartup ---'; "
            "ls -la /usr/lib/win-kex/xstartup /usr/bin/kex 2>&1 || true; "
            "echo '--- kex-start.log ---'; "
            f"tail -n 80 /home/{self.config['wsl_user']}/.cache/kali-launcher/kex-start.log 2>/dev/null || "
            "echo '(no log)'; "
            "echo '--- ip ---'; "
            "hostname -I 2>/dev/null || true"
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
                script,
            ],
            timeout=60.0,
        )
        detail = (result.stdout or result.stderr or "").strip()
        if detail:
            self.log(detail[-1800:])
        wslconfig = os.path.join(os.environ.get("USERPROFILE", ""), ".wslconfig")
        if os.path.isfile(wslconfig):
            try:
                text = open(wslconfig, encoding="utf-8", errors="ignore").read()
            except OSError:
                text = ""
            if "localhostforwarding" in text.lower() and "false" in text.lower():
                self.log("힌트: %USERPROFILE%\\.wslconfig 에 localhostForwarding=false 가 있습니다.")
                self.log("  [wsl2] localhostForwarding=true 로 바꾼 뒤 wsl --shutdown 하세요.")
        else:
            self.log("힌트: localhost 포워딩 문제가 의심되면 %USERPROFILE%\\.wslconfig 에")
            self.log("  [wsl2]")
            self.log("  localhostForwarding=true")
            self.log("  를 넣고 wsl --shutdown 후 다시 시도하세요.")


    def _stage_winkex_files_local(self) -> tuple[str | None, str | None]:
        """
        Copy TigerVNC client + passwd to a local NTFS folder via `wsl cp` /mnt/c/...

        Opening \\\\wsl$\\... from Explorer or CreateProcess while the portable VHDX
        is slow/stuck makes Explorer appear to 'loop' and every wsl.exe call waits
        for HCS timeouts. Local copies avoid that path entirely.
        """
        distro = self.config["distro_name"]
        user = self.config["wsl_user"]
        base = os.path.join(
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("TEMP")
            or os.environ.get("USERPROFILE")
            or "C:\\",
            "KaliLauncher",
            "winkex-cache",
        )
        try:
            os.makedirs(base, exist_ok=True)
        except OSError as exc:
            self.log(f"로컬 캐시 폴더 생성 실패: {exc}")
            return None, None

        client_win = os.path.join(base, "win-kex-win-x64.exe")
        passwd_win = os.path.join(base, "passwd")
        client_mnt = windows_path_to_wsl_mnt(client_win)
        passwd_mnt = windows_path_to_wsl_mnt(passwd_win)
        linux_client = "/usr/lib/win-kex/TigerVNC/win-kex-win-x64"
        linux_passwd = f"/home/{user}/.config/tigervnc/passwd"

        self.log("Win-KeX 클라이언트를 로컬 디스크로 복사 중 (\\\\wsl$ 미사용)...")
        script = (
            f"set -e; "
            f"test -r {shlex.quote(linux_client)}; "
            f"test -r {shlex.quote(linux_passwd)}; "
            f"cp -f {shlex.quote(linux_client)} {shlex.quote(client_mnt)}; "
            f"cp -f {shlex.quote(linux_passwd)} {shlex.quote(passwd_mnt)}; "
            f"chmod 644 {shlex.quote(passwd_mnt)} 2>/dev/null || true; "
            f"echo COPIED"
        )
        result = self._run(
            [
                "wsl",
                "--cd",
                "~",
                "-d",
                distro,
                "-u",
                "root",
                "--",
                "bash",
                "-lc",
                script,
            ],
            timeout=90.0,
        )
        if "COPIED" not in (result.stdout or "") or not (
            os.path.isfile(client_win) and os.path.isfile(passwd_win)
        ):
            detail = (result.stderr or result.stdout or "").strip()
            self.log(f"  → 로컬 복사 실패: {detail[:400] or '(메시지 없음)'}")
            return None, None

        self.log(f"  → {client_win}")
        return client_win, passwd_win

    def _launch_winkex_client(self) -> bool:
        """
        Launch win-kex-win-x64 as a Windows process (not via wsl start-client).

        Prefer a local NTFS copy. Never require \\\\wsl$\\ — that path freezes Explorer
        when the external-SSD VHDX / HCS stack is slow.
        """
        distro = self.config["distro_name"]
        user = self.config["wsl_user"]

        client, passwd = self._stage_winkex_files_local()
        if not client or not passwd:
            self.log("경고: 로컬 복사 실패 — \\\\wsl$ 폴백은 탐색기를 멈출 수 있어 짧게만 시도합니다.")
            self._run(
                ["wsl", "--cd", "~", "-d", distro, "-u", user, "--", "true"],
                timeout=20.0,
            )
            client = wsl_unc_path(distro, "/usr/lib/win-kex/TigerVNC/win-kex-win-x64")
            passwd = wsl_unc_path(distro, f"/home/{user}/.config/tigervnc/passwd")
            if not client or not wait_for_path(client, 5):
                self.log("오류: Win-KeX 클라이언트(win-kex-win-x64)를 찾을 수 없습니다.")
                return False
            if not passwd or not wait_for_path(passwd, 5):
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

        host = "localhost"
        self.config["vnc_host"] = host
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

        # Desktop WSLg remounts X11 RO and kex asks for sudo password.
        self.log("X11 tmpfs + VNC 잔여 상태 준비 중...")
        self.ensure_kex_nopasswd_mount()
        self.clean_stale_vnc_state()
        if not self._fix_x11_unix_root(force_recreate=True):
            self.prepare_x11_unix()

        port = int(self.config.get("kex_vnc_port", 5901))
        # Local config may set 25s; portable/external SSD often needs longer.
        wait_sec = max(float(self.config.get("kex_server_wait_sec", 60)), 45.0)

        for attempt in (1, 2):
            cmd = self._build_wsl_kex_cmd(server_args, capture_log=True)
            self.log(f"Win-KeX 서버 시작... ({' '.join(server_args)}) [시도 {attempt}/2]")
            self.log(f"> {' '.join(cmd)}")
            # CRITICAL: kex --start often never exits. Never use subprocess.run here.
            # CRITICAL: cwd must NOT be the portable drive (H: → /mnt/h I/O errors).
            try:
                start_detached(cmd, cwd=safe_windows_cwd())
            except OSError as exc:
                self.log(f"서버 시작 실패: {exc}")
                return False

            if not self._wait_for_vnc_port(port, wait_sec):
                self.log(f"  → 포트 {port} 응답 없음")
                self._diagnose_kex_server_failure()
                if attempt == 1:
                    self.log("  → Win-KeX/X11 재준비 후 한 번 더 시도합니다...")
                    self._run(self._build_wsl_kex_cmd(["--kill"]), timeout=45.0)
                    self.clean_stale_vnc_state()
                    self.ensure_kex_nopasswd_mount()
                    self._fix_x11_unix_root(force_recreate=True)
                continue

            self.log(f"  → VNC 서버 준비 완료 (포트 {port})")
            if not self.wait_for_kex_desktop():
                self.log("  → 데스크톱 미기동 — X11 소켓 강제 재생성 후 KeX 재시작")
                self._run(self._build_wsl_kex_cmd(["--kill"]), timeout=45.0)
                self._fix_x11_unix_root(force_recreate=True)
                if attempt == 1:
                    continue
                self.log("힌트: WSL에서 아래를 실행해 보세요.")
                self.log("  kex --kill")
                self.log("  sudo bash -c 'umount /tmp/.X11-unix 2>/dev/null; rm -rf /tmp/.X11-unix; mkdir -p /tmp/.X11-unix; chmod 1777 /tmp/.X11-unix'")
                self.log("  unset WAYLAND_DISPLAY WAYLAND_SOCKET; kex --win -s")
                # Still launch viewer so the user can see whatever is on the session.
            return self._launch_winkex_client()

        self.log("오류: VNC 서버가 시작되지 않아 클라이언트를 실행하지 않습니다.")
        self.log("힌트: 새 Kali를 받는 문제가 아닙니다. 같은 VHDX + 이 PC의 X11(tmpfs)/sudo/VNC pid를 의심하세요.")
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
            self.log("알림: ext4.vhdx 를 삭제/교체하거나 새 Kali를 받지 않습니다. 외장 SSD의 그 환경을 그대로 씁니다.")
            self.log("알림: 시작 중 탐색기에서 \\\\wsl$ / Linux 아이콘 / ext4.vhdx 를 열지 마세요.")
            self.log("알림: 외장 SSD의 VHDX는 첫 기동이 느릴 수 있습니다. 명령이 길면 HCS 대기일 수 있습니다.")

            if not self.ensure_wsl_platform():
                return

            if self.wsl_distro_exists():
                if not self.ensure_wsl_healthy():
                    return
                self.prepare_wsl_session()

            if not self.import_wsl_if_needed():
                return

            if not self.ensure_winkex_installed():
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
