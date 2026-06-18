# Kali Linux Portable Launcher

![Version](https://img.shields.io/badge/Version-1.1.1-blue) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

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

1. Download `KaliLauncher.exe` from [Releases](../../releases)
2. Place it in your `kali-portable` folder
3. Run it and click **Start Kali Linux**

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

## Tech stack

- Python 3 + Tkinter
- WSL2 + Win-KeX 3.x
- PyInstaller (single-file executable)

## License

MIT License — see [LICENSE](LICENSE)

## Disclaimer

Kali Linux and the dragon logo are trademarks of [Kali Linux / Offensive Security](https://www.kali.org/).  
This project is an unofficial third-party tool and is not affiliated with the Kali Linux project.
