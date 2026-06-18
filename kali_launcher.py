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
APP_VERSION = "1.1.1"
DEFAULT_DISTRO = "kali-linux"
DEFAULT_USER = "kali"
CONFIG_FILENAME = "kali_launcher_config.json"
ICON_FILENAME = "kali_icon.ico"
WSL_FOLDER_NAME = "kali-portable"
DEFAULT_TAR_FILENAME = "kali-final.tar"
TAR_FILENAMES = (DEFAULT_TAR_FILENAME, "kali-fresh.tar")

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
        "kex_server_wait_sec": 25,
        "winkex_fullscreen": False,
        "prefer_vcxsrv": False,
        "vnc_ports": [5901, 5902, 5903],
        "vnc_host": "localhost",
        "vnc_viewer_delay_sec": 5,
        "kex_client_delay_sec": 6,
        "fix_xfce_notifyd": True,
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


def run_command(cmd: list[str], *, check: bool = False) -> RunResult:
    result = subprocess.run(
        cmd,
        check=check,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return RunResult(
        returncode=result.returncode,
        stdout=decode_subprocess_output(result.stdout),
        stderr=decode_subprocess_output(result.stderr),
    )


def list_wsl_distros() -> list[str]:
    result = run_command(["wsl", "-l", "-q"])
    names: list[str] = []
    for line in (result.stdout or "").splitlines():
        name = line.strip().lstrip("*").strip()
        if name:
            names.append(name)
    return names


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

    def _run(self, cmd: list[str], *, check: bool = False) -> RunResult:
        self.log(f"> {' '.join(cmd)}")
        return run_command(cmd, check=check)

    def wsl_distro_exists(self) -> bool:
        distro = self.config["distro_name"].lower()
        for name in list_wsl_distros():
            if name.lower() == distro:
                return True
        return False

    def import_wsl_if_needed(self) -> bool:
        if self.wsl_distro_exists():
            self.log("WSL 배포판이 이미 등록되어 있습니다.")
            return True

        tar_path = self.paths["tar_path"]
        install_dir = self.paths["wsl_install_dir"]

        if not os.path.isfile(tar_path):
            self.log(f"오류: 설치용 tar 파일을 찾을 수 없습니다.\n  {tar_path}")
            return False

        os.makedirs(install_dir, exist_ok=True)

        if not is_admin():
            self.log("첫 설치에는 관리자 권한이 필요합니다.")
            self.log("UAC 창이 뜨면 「예」를 눌러 관리자 권한으로 다시 실행해주세요.")
            run_as_admin()
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
            ]
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

    def shutdown_wsl(self) -> None:
        self.log("기존 WSL 세션 정리 중...")
        self._run(["wsl", "--shutdown"])

    def prepare_wsl_session(self) -> None:
        if self.config.get("shutdown_wsl_before_start", False):
            self.shutdown_wsl()
            return

        if self.config.get("clean_kex_before_start", True):
            self.log("KeX 세션 정리 중...")
            self._run(self._build_wsl_kex_cmd(["--kill"]))
            return

        if not self.config.get("stop_kex_before_start", False):
            return

        self.log("기존 KeX 세션 정리 중...")
        self._run(self._build_wsl_kex_cmd(["--stop"]))

    def apply_xfce_fixes(self) -> None:
        """Win-KeX(VNC/X11)에서 xfce4-notifyd Wayland 오류 방지."""
        if not self.config.get("fix_xfce_notifyd", True):
            return

        self.log("Xfce 알림 오류 방지 설정 적용 중...")
        script = (
            "mkdir -p ~/.config/autostart ~/.config/environment.d && "
            "printf '[Desktop Entry]\\nHidden=true\\n' > ~/.config/autostart/xfce4-notifyd.desktop && "
            "printf 'GDK_BACKEND=x11\\n' > ~/.config/environment.d/win-kex.conf"
        )
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
                script,
            ]
        )
        if result.returncode == 0:
            self.log("  → xfce4-notifyd 비활성화, GDK_BACKEND=x11 설정 완료")
        else:
            self.log("  → Xfce 설정 적용 실패 (무시하고 계속 진행)")

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
        return [
            "wsl",
            "--cd",
            "~",
            "-d",
            self.config["distro_name"],
            "-u",
            self.config["wsl_user"],
            "--",
            "kex",
            *kex_args,
        ]

    def _launch_winkex_client(self) -> bool:
        distro = self.config["distro_name"]
        user = self.config["wsl_user"]
        client = wsl_unc_path(distro, "/usr/lib/win-kex/TigerVNC/win-kex-win-x64")
        passwd = wsl_unc_path(distro, f"/home/{user}/.config/tigervnc/passwd")

        if not client or not os.path.isfile(client):
            self.log("오류: Win-KeX 클라이언트(win-kex-win-x64)를 찾을 수 없습니다.")
            return False
        if not passwd or not os.path.isfile(passwd):
            self.log("오류: VNC 비밀번호 파일 없음. WSL에서 kex --passwd 로 설정하세요.")
            return False

        host = self.config.get("vnc_host", "localhost")
        display = self.config.get("kex_display", ":1")
        target = f"{host}{display}"
        fullscreen = "FullScreen=1" if self.config.get("winkex_fullscreen", False) else "FullScreen=0"

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
        try:
            subprocess.Popen(args)
        except OSError as exc:
            self.log(f"클라이언트 실행 실패: {exc}")
            return False

        time.sleep(2)
        if is_process_running("win-kex-win-x64") or is_process_running("win-kex-win-x64.exe"):
            self.log("Win-KeX 클라이언트 실행됨. 비밀번호 입력 후 데스크톱이 표시됩니다.")
        else:
            self.log("클라이언트가 시작됐을 수 있습니다. 작업 표시줄을 확인하세요.")
        return True

    def _start_kex_win_split(self, mode: str, kex_args: list[str]) -> bool:
        sound = "-s" in kex_args
        server_args = [f"--{mode}", "--start"]
        if sound:
            server_args.append("-s")

        self.log(f"Win-KeX 서버 시작... ({' '.join(server_args)})")
        self._run(self._build_wsl_kex_cmd(server_args))

        port = int(self.config.get("kex_vnc_port", 5901))
        wait_sec = float(self.config.get("kex_server_wait_sec", 25))
        self.log(f"VNC 서버 대기 중... (localhost:{port}, 최대 {wait_sec:.0f}초)")
        if wait_for_tcp_port("127.0.0.1", port, wait_sec):
            self.log(f"  → VNC 서버 준비 완료 (포트 {port})")
        else:
            self.log(f"  → 경고: 포트 {port} 응답 없음 — 클라이언트 실행 계속")

        return self._launch_winkex_client()

    def _start_kex_simple(self, kex_args: list[str]) -> bool:
        cmd = self._build_wsl_kex_cmd(kex_args)
        launch_cwd = self.paths.get("app_dir") or get_app_dir()
        self.log(f"Win-KeX 시작: {' '.join(kex_args)}")
        self.log("> " + " ".join(cmd))
        try:
            subprocess.Popen(cmd, cwd=launch_cwd)
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
            self.log(f"배포판: {self.config['distro_name']} / 사용자: {self.config['wsl_user']}")

            if not shutil.which("wsl"):
                self.log("오류: WSL(wsl.exe)을 찾을 수 없습니다. Windows 기능에서 WSL을 활성화해주세요.")
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

        if shutil.which("wsl"):
            self._run(self._build_wsl_kex_cmd(["--kill"]))
        else:
            self.log("WSL을 찾을 수 없어 Windows 프로세스만 종료했습니다.")

        self.log("세션 종료 완료.")


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
