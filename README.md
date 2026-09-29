# Kali Linux Portable Launcher

<p align="center">
  <img src="kali_icon.png" alt="Kali Linux Portable" width="220">
</p>

<p align="center">
  <a href="https://github.com/KaiHT-Ladiant/wsl-kali-portable-launcher/releases"><img src="https://img.shields.io/github/v/release/KaiHT-Ladiant/wsl-kali-portable-launcher?label=Release&color=blue" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="CONTRIBUTORS.md"><img src="https://img.shields.io/badge/Maintainer-Kai__HT-0a7ea4" alt="Maintainer Kai_HT"></a>
  <img src="https://img.shields.io/badge/Version-1.2.23-blue" alt="Version 1.2.23">
</p>

A Windows GUI client for running **WSL Kali Linux** from a portable external SSD.  
Start and stop Win-KeX (TigerVNC) sessions with one click.

Maintained by **[Kai_HT](https://github.com/KaiHT-Ladiant)** — see [CONTRIBUTORS.md](CONTRIBUTORS.md).

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
H:\0.Kali\                        <- drive letter may vary (F:, H:, …)
├── kali-final.tar                <- optional, for first/repair WSL import (local only)
├── KaliLauncher.exe              <- from GitHub Releases
├── kali_icon.ico                 <- optional, for shortcuts
└── kali-portable\
    └── ext4.vhdx                 <- created locally, never committed
```

The launcher resolves paths from its own location. Running from `dist\` or the project root both work.

## Quick start

### Option 1: Release executable (recommended)

1. Download `KaliLauncher.exe` from [Releases](https://github.com/KaiHT-Ladiant/wsl-kali-portable-launcher/releases)
2. Place it in your `0.Kali` / `kali-portable` folder (replace the old exe)
3. Run it and click **Start Kali Linux**

> Fixes land on GitHub first. The copy on your external SSD does **not** update until you replace that `.exe` (or rebuild with `build_exe.bat`).

### Option 2: Build from source

```bat
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

Create `kali_launcher_config.json` next to the executable (local only — not in this repository):

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
| Works on another PC, fails on this PC | Drive letter / WSL `BasePath` mismatch. v1.2.17+ remaps to the exe drive (never deletes the VHDX). |
| `MountDisk` / `0x80070570` | Not a path bug when BasePath matches. Optional last resort: **손상 복구(tar)** renames `ext4.vhdx` → `.bak-*` and imports local `kali-final.tar`. |
| After tar import, Win-KeX missing | v1.2.22+ installs `kali-win-kex` inside the same VHDX (package only — not a new Kali download). |
| Want old `/home` files back after tar import | Use **이전 VHDX 복원** (v1.2.23+): moves the new `ext4.vhdx` aside and restores the largest `ext4.vhdx.bak-*`. |
| `HCS_E_CONNECTION_TIMEOUT` / Explorer freezes | Do **not** spam Start. `wsl --shutdown`, avoid `\\wsl$`, reboot once. |
| TigerVNC `localhost:1` refused after "완료" | Fixed in v1.2.14 — server is kept running when connecting. |

## Releases

Binary releases are published on the [Releases](https://github.com/KaiHT-Ladiant/wsl-kali-portable-launcher/releases) page by **Kai_HT**.  
Tagging `v*` on `main` builds `KaliLauncher.exe` via GitHub Actions and attaches it to the release.

## Contributors

| Name | GitHub | Role |
|------|--------|------|
| Kai_HT | [@KaiHT-Ladiant](https://github.com/KaiHT-Ladiant) | Author and maintainer |

See [CONTRIBUTORS.md](CONTRIBUTORS.md) for contributing notes. Automated assist commits are not listed as maintainers.

## Tech stack

- Python 3 + Tkinter
- WSL2 + Win-KeX 3.x
- PyInstaller (single-file executable)

## License

MIT License — see [LICENSE](LICENSE)

## Disclaimer

Kali Linux and the dragon logo are trademarks of [Kali Linux / Offensive Security](https://www.kali.org/).  
This project is an unofficial third-party tool and is not affiliated with the Kali Linux project.
