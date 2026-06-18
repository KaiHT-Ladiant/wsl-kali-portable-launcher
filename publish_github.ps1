# GitHub 배포 스크립트
# 사전 준비: gh auth login

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$repoName = "wsl-kali-portable-launcher"
$version = "v1.1.1"
$desc = "Windows portable WSL Kali Linux GUI launcher (Win-KeX / TigerVNC)"
$safeDir = "-c", "safe.directory=$((Get-Location).Path -replace '\\','/')"

function Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & git @safeDir @Args
}

Write-Host "GitHub 로그인 확인..."
gh auth status
if ($LASTEXITCODE -ne 0) {
    Write-Host "먼저 실행: gh auth login"
    exit 1
}

if (-not (Test-Path ".git")) {
    Git init
    Git branch -M main
}

Git add .
git status
Git commit -m "Release $version - Kali Linux Portable Launcher" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "커밋할 변경 없음 또는 이미 커밋됨"
}

$remote = gh repo view $repoName --json url -q .url 2>$null
if (-not $remote) {
    Write-Host "GitHub 레포지토리 생성: $repoName"
    gh repo create $repoName --public --source=. --remote=origin --description $desc --push
} else {
    Write-Host "기존 레포지토리 사용: $remote"
    git push -u origin main
}

if (-not (Test-Path "dist\KaliLauncher.exe")) {
    Write-Host "dist\KaliLauncher.exe 없음 — build_exe.bat 실행 후 다시 시도"
    exit 1
}

Write-Host "GitHub Release 생성: $version"
gh release create $version `
    "dist/KaliLauncher.exe" `
    "dist/kali_icon.ico" `
    "dist/kali_icon.png" `
    --title "Kali Linux Portable $version" `
    --notes "## Kali Linux Portable Launcher $version

- WSL Kali + Win-KeX TigerVNC 원클릭 시작/정지
- 외장 SSD 드라이브 자동 감지
- Kali 아이콘 적용

### 설치
1. KaliLauncher.exe 를 kali-portable 폴더에 저장
2. 실행 후 「Kali Linux 시작」"

Write-Host "완료!"
gh repo view --web
