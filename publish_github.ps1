# Publish to GitHub
# Prerequisites: gh auth login

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$repoName = "wsl-kali-portable-launcher"
$version = "v1.1.1"
$desc = "Windows portable WSL Kali Linux GUI launcher (Win-KeX / TigerVNC)"
$safeDir = "-c", "safe.directory=$((Get-Location).Path -replace '\\','/')"

function Resolve-Tool {
    param(
        [string]$Name,
        [string[]]$Candidates
    )

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    foreach ($path in $Candidates) {
        if (Test-Path $path) {
            $dir = Split-Path $path -Parent
            if ($env:Path -notlike "*$dir*") {
                $env:Path = "$dir;$env:Path"
            }
            return $path
        }
    }

    return $null
}

$ghExe = Resolve-Tool -Name "gh" -Candidates @(
    "$env:ProgramFiles\GitHub CLI\gh.exe",
    "${env:ProgramFiles(x86)}\GitHub CLI\gh.exe",
    "$env:LocalAppData\Programs\GitHub CLI\gh.exe"
)

if (-not $ghExe) {
    Write-Host "GitHub CLI (gh) not found in PATH."
    Write-Host "Install: winget install --id GitHub.cli"
    Write-Host "Then open a new terminal and run: gh auth login"
    exit 1
}

$gitExe = Resolve-Tool -Name "git" -Candidates @(
    "$env:ProgramFiles\Git\cmd\git.exe",
    "${env:ProgramFiles(x86)}\Git\cmd\git.exe"
)

if (-not $gitExe) {
    Write-Host "Git not found in PATH."
    Write-Host "Install: winget install --id Git.Git"
    exit 1
}

function Gh {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & $ghExe @Args
}

function Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & $gitExe @safeDir @Args
}

Write-Host "Checking GitHub authentication..."
Gh auth status
if ($LASTEXITCODE -ne 0) {
    Write-Host "Run first: gh auth login"
    exit 1
}

if (-not (Test-Path "dist\KaliLauncher.exe")) {
    Write-Host "Building release executable..."
    cmd /c build_exe.bat
}

if (-not (Test-Path "dist\KaliLauncher.exe")) {
    Write-Host "dist\KaliLauncher.exe not found."
    exit 1
}

if (-not (Test-Path ".git")) {
    Git init
    Git branch -M main
}

Git add .
Git status
Git commit -m "Release $version" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Nothing new to commit."
}

$remote = Gh repo view $repoName --json url -q .url 2>$null
if (-not $remote) {
    Write-Host "Creating repository: $repoName"
    Gh repo create $repoName --public --source=. --remote=origin --description $desc --push
} else {
    Write-Host "Using existing repository: $remote"
    Git push -u origin main
}

Write-Host "Creating GitHub Release: $version"
Gh release create $version `
    "dist/KaliLauncher.exe" `
    --title "Kali Linux Portable $version" `
    --notes "WSL Kali portable launcher with Win-KeX TigerVNC start/stop and drive auto-detection."

Write-Host "Done."
Gh repo view --web
