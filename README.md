# Kali Linux Portable Launcher

![Version](https://img.shields.io/badge/Version-1.2.11-blue) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Windows GUI client for running **WSL Kali Linux** from a portable external SSD.  
Start and stop Win-KeX (TigerVNC) sessions with one click.

![Kali Linux Portable](kali_icon.png)

## Features

- **Start Kali Linux** — Launch WSL KeX server and Win-KeX TigerVNC client automatically
- **Stop Kali Linux** — Terminate TigerVNC/Win-KeX processes and run `kex --kill`
- **Drive-letter auto-detection** — Works when the external SSD is mounted on any drive letter
- **Session modes** — WIN (TigerVNC), VNC, ESM (RDP)
- **Desktop shortcut** — Create a `.lnk` with the Kali icon
- **First-time WSL import** — Optional import from a local tar archive (requires administrator)
- **Portable SSD recovery** — Detects stale WSL state after drive reconnect and auto-recovers
- **Safe stop** — Optionally runs `wsl --shutdown` so the SSD can be unplugged cleanly

## Requirements

| Item | Description |
|------|-------------|
| OS | Windows 10/11 with WSL2 |
| WSL | Kali Linux distribution (e.g. `kali-linux`) |
| Win-KeX | `kex` inside Kali WSL (Win-KeX 3.x) |
| Python | Not required when using the release `.exe`; Python 3.10+ for source runs |

## Recommended folder layout (external SSD)

```
D:\kali-setup\                    <- drive letter may vary
├── kali-rootfs.tar               <- optional, for first WSL import (not included in repo)
└── kali-portable\
    ├── KaliLauncher.exe          <- from Releases
    ├── kali_icon.ico             <- optional, for shortcuts
    └── (WSL ext4.vhdx, etc.)     <- created locally, never committed
```

The launcher resolves paths from its own location. Running from `dist\` or the project root both work.

## Quick start

### Option 1: Release executable (recommended)

1. Download `KaliLauncher.exe` from [Releases](../../releases) **or** from the latest **Actions → Build EXE** artifact on this branch
2. Place it in your `kali-portable` / `0.Kali` folder (replace the old exe)
3. Run it and click **Start Kali Linux**

> Cloud/PR fixes land in GitHub first. The copy on your external SSD (`F:\0.Kali\...`) does **not** update until you replace that `.exe` (or rebuild with `build_exe.bat`).


### Option 2: Build from source

```bat
cd kali-portable
build_exe.bat
```

Output: `dist\KaliLauncher.exe`

### Option 3: Run with Python

```bat
python kali_launcher.py
```

## Usage

1. Select a **session mode** (default: `win` — TigerVNC)
2. Click **Start Kali Linux**
3. Enter your VNC password in the Win-KeX/TigerVNC window  
   - First time only: set the password inside WSL with `kex --passwd`
4. Click **Stop Kali Linux** when finished

## Configuration

Create `kali_launcher_config.json` next to the executable (this file is local and not part of the repository):

```json
{
  "distro_name": "kali-linux",
  "wsl_user": "your-wsl-username",
  "session_mode": "win",
  "kex_vnc_port": 5901,
  "clean_kex_before_start": true,
  "fix_xfce_notifyd": true
}
```

## Troubleshooting

| Symptom | Action |
|---------|--------|
| TigerVNC window does not appear | Run `kex --passwd` in WSL, then restart |
| Xfce notification daemon error | Harmless; disabled automatically in v1.0.7+ |
| WSL import fails | Run the launcher as administrator |
| Connection refused on VNC port | Confirm `kex_vnc_port` is `5901` |
| Fails after unplugging external SSD | Use **Stop Kali Linux** first (v1.2.5+ shuts down WSL). If it still fails, restart the launcher — it auto-recovers. |
| Works on another PC, fails on this PC | Usually the SSD drive letter changed and WSL `BasePath` still points at the old path. v1.2.6+ rewrites `BasePath` to the current `ext4.vhdx` folder (never deletes the VHDX). Also confirm Virtual Machine Platform is enabled. |
| Log shows `WSL 재시작 실패` with garbled text | Fixed in v1.2.6 (UTF-16/Korean console decoding). Re-run with the new build to see the real Windows error. |
| `HCS_E_CONNECTION_TIMEOUT` / Explorer freezes | Do **not** spam Start. Run `wsl --shutdown`, avoid opening `\\wsl$`, reboot Windows, then try once. If it still times out, the VHDX may be unhealthy — keep a copy of `ext4.vhdx` and consider re-import from `kali-final.tar`. |
| VNC connects but screen is blank/black | XFCE did not start. v1.2.8+ recreates `/tmp/.X11-unix` and waits for the desktop. Manual fix: `kex --kill`, recreate `/tmp/.X11-unix` as a 1777 directory, then `kex --win -s`. |
| Explorer loops / hangs when starting Kali | Usually `\\wsl$` or the VHDX on the external SSD is stuck. Do not open `\\wsl$`, Linux in the nav pane, or `ext4.vhdx` while starting. v1.2.9+ copies the Win-KeX client to `%LOCALAPPDATA%\\KaliLauncher` instead of launching from `\\wsl$`. Run `wsl --shutdown` and reboot if Explorer is already looping. |
| `wsl` commands hang for a long time | The portable `ext4.vhdx` is on USB/SSD and/or HCS is timing out. After BasePath is correct, reboot once; avoid hammering Start. Prefer USB 3.x direct ports. |
| VNC port 5901 never opens / `NO_XSTARTUP` | Win-KeX files are missing on this Kali (`/usr/lib/win-kex/xstartup`). v1.2.10+ tries `apt install kali-win-kex`. Manual: `sudo apt update && sudo apt install -y kali-win-kex` |
| `/tmp/.X11-unix` read-only / VNC never starts | Fixed automatically in v1.2.5 via root remount after WSL health check |

## Tech stack

- Python 3 + Tkinter
- WSL2 + Win-KeX 3.x
- PyInstaller (single-file executable)

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md). Maintained by [@KaiHT-Ladiant](https://github.com/KaiHT-Ladiant).

## License

MIT License — see [LICENSE](LICENSE)

## Disclaimer

Kali Linux and the dragon logo are trademarks of [Kali Linux / Offensive Security](https://www.kali.org/).  
This project is an unofficial third-party tool and is not affiliated with the Kali Linux project.
