# Kali Linux Portable Launcher

Windows용 **외장 SSD 포터블 WSL Kali Linux** 실행 GUI 클라이언트입니다.  
한 번의 클릭으로 WSL Kali + Win-KeX(TigerVNC) 세션을 시작·종료할 수 있습니다.

![Kali Linux Portable](kali_icon.png)

## 주요 기능

- **Kali Linux 시작** — WSL KeX 서버 기동 + Win-KeX TigerVNC 클라이언트 자동 실행
- **Kali Linux 정지** — TigerVNC/Win-KeX 프로세스 및 `kex --kill`로 세션 종료
- **드라이브 문자 자동 감지** — 외장 SSD 드라이브(H:, E: 등) 변경에도 경로 자동 계산
- **세션 모드 선택** — WIN (TigerVNC), VNC, ESM (RDP)
- **바탕화면 바로가기** — Kali 아이콘 포함 `.lnk` 생성
- **최초 WSL 가져오기** — `kali-final.tar` 자동 import (관리자 권한 필요)

## 요구 사항

| 항목 | 설명 |
|------|------|
| OS | Windows 10/11 (WSL2) |
| WSL | Kali Linux 배포판 (`kali-linux` 등) |
| Win-KeX | Kali WSL 내 `kex` (Win-KeX 3.x) |
| Python | exe 사용 시 불필요 / 소스 실행 시 3.10+ |

## 폴더 구조 (외장 SSD)

```
D:\0.Kali\                      ← 드라이브 문자는 자유
├── kali-final.tar                ← WSL 최초 import용 (선택)
└── kali-portable\
    ├── KaliLauncher.exe          ← 릴리스 exe
    ├── kali_icon.ico
    └── (WSL ext4.vhdx 등)
```

exe를 `kali-portable\dist\` 에 두어도 상위 폴더를 자동 탐색합니다.

## 빠른 시작

### 1. Release exe 사용 (권장)

1. [Releases](../../releases)에서 `KaliLauncher.exe` 다운로드
2. `kali-portable` 폴더에 저장
3. `KaliLauncher.exe` 실행 → **Kali Linux 시작**

### 2. 소스에서 빌드

```bat
cd kali-portable
build_exe.bat
```

빌드 결과: `dist\KaliLauncher.exe`

### 3. Python으로 직접 실행

```bat
python kali_launcher.py
```

## 사용법

1. **세션 모드** 선택 (기본: `win` — TigerVNC)
2. **Kali Linux 시작** 클릭
3. TigerVNC(Win-KeX) 창에서 **VNC 비밀번호** 입력  
   - 최초 1회: WSL에서 `kex --passwd` 로 설정
4. 종료 시 **Kali Linux 정지** 클릭

## 설정 (`kali_launcher_config.json`)

exe와 같은 폴더에 생성·편집 가능합니다.

```json
{
  "distro_name": "kali-linux",
  "wsl_user": "Kai_HT",
  "session_mode": "win",
  "kex_vnc_port": 5901,
  "clean_kex_before_start": true,
  "fix_xfce_notifyd": true
}
```

## 문제 해결

| 증상 | 해결 |
|------|------|
| TigerVNC 창이 안 뜸 | `kex --passwd` 재설정 후 재시작 |
| Xfce 알림 오류 | v1.0.7+ 에서 자동 비활성화 (무해) |
| WSL import 실패 | 관리자 권한으로 실행 |
| 포트 연결 거부 | `kex_vnc_port` 를 `5901` 로 확인 |

## 기술 스택

- Python 3 + Tkinter
- WSL2 + Win-KeX 3.x
- PyInstaller (단일 exe)

## GitHub 배포

```powershell
# 1. GitHub CLI 로그인 (최초 1회)
gh auth login

# 2. 레포지토리 생성 + Release 업로드
.\publish_github.ps1
```

태그 push 시 GitHub Actions가 exe를 자동 빌드·릴리스합니다.

```bat
git tag v1.1.1
git push origin v1.1.1
```

## 라이선스

MIT License — [LICENSE](LICENSE)

## 주의

Kali Linux 및 드래곤 로고는 [Kali Linux / Offensive Security](https://www.kali.org/) 의 상표입니다.  
본 프로젝트는 Kali Linux 공식 프로젝트와 무관한 서드파티 도구입니다.
