# Publish to GitHub
# Prerequisites: gh auth login

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$repoName = "wsl-kali-portable-launcher"
$version = "v1.1.1"
$desc = "Windows portable WSL Kali Linux GUI launcher (Win-KeX / TigerVNC)"
$repoPath = (Resolve-Path $PSScriptRoot).Path -replace '\\', '/'
$gitSafeDir = "-c", "safe.directory=$repoPath"

# Allow git/gh on external or portable drives without changing global git config.
$env:GIT_CONFIG_COUNT = "1"
$env:GIT_CONFIG_KEY_0 = "safe.directory"
$env:GIT_CONFIG_VALUE_0 = $repoPath

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

function Invoke-External {
    param(
        [string]$Exe,
        [string[]]$ArgumentList
    )

    $argText = ($ArgumentList | ForEach-Object {
        if ($_ -match '\s|"') {
            '"' + ($_.Replace('"', '\"')) + '"'
        } else {
            $_
        }
    }) -join ' '

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = $argText
    $psi.WorkingDirectory = $PSScriptRoot
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($psi)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    return [PSCustomObject]@{
        Output   = $stdout.Trim()
        Error    = $stderr.Trim()
        ExitCode = $process.ExitCode
    }
}

function Gh {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ToolArgs)

    $result = Invoke-External -Exe $ghExe -ArgumentList $ToolArgs
    if ($result.ExitCode -ne 0) {
        if ($result.Error) {
            Write-Host $result.Error
        }
        throw "gh failed (exit $($result.ExitCode)): gh $($ToolArgs -join ' ')"
    }

    if ($result.Output) {
        Write-Output $result.Output
    }
}

function GhTry {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ToolArgs)
    Invoke-External -Exe $ghExe -ArgumentList $ToolArgs
}

function GitTry {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ToolArgs)
    Invoke-External -Exe $gitExe -ArgumentList (@($gitSafeDir) + $ToolArgs)
}

function Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ToolArgs)

    $result = GitTry @ToolArgs
    if ($result.ExitCode -ne 0) {
        if ($result.Error) {
            Write-Host $result.Error
        }
        throw "git failed (exit $($result.ExitCode)): git $($ToolArgs -join ' ')"
    }

    if ($result.Output) {
        Write-Output $result.Output
    }
}

function Ensure-GitRepository {
    $inside = GitTry rev-parse --is-inside-work-tree
    if ($inside.ExitCode -ne 0 -or $inside.Output -ne "true") {
        Write-Host "Initializing local git repository..."
        Git init
        Git branch -M main
    }
}

function Ensure-GitHubRepository {
    $repoView = GhTry repo view $repoName --json url -q .url
    if ($repoView.ExitCode -eq 0 -and $repoView.Output) {
        return $repoView.Output.Trim()
    }

    Write-Host "Creating repository: $repoName"
    Gh repo create $repoName --public --description $desc | Out-Null

    $repoView = GhTry repo view $repoName --json url -q .url
    if ($repoView.ExitCode -ne 0 -or -not $repoView.Output) {
        throw "Could not resolve repository URL for $repoName"
    }

    return $repoView.Output.Trim()
}

Write-Host "Checking GitHub authentication..."
$auth = GhTry auth status
if ($auth.ExitCode -ne 0) {
    if ($auth.Error) {
        Write-Host $auth.Error
    }
    Write-Host "Run first: gh auth login"
    exit 1
}
if ($auth.Output) {
    Write-Host $auth.Output
}

if (-not (Test-Path "dist\KaliLauncher.exe")) {
    Write-Host "Building release executable..."
    cmd /c build_exe.bat
}

if (-not (Test-Path "dist\KaliLauncher.exe")) {
    Write-Host "dist\KaliLauncher.exe not found."
    exit 1
}

Ensure-GitRepository

Git add .
Git status
$commit = GitTry commit -m "Release $version"
if ($commit.ExitCode -ne 0) {
    Write-Host "Nothing new to commit."
}

$remoteCheck = GitTry remote get-url origin
if ($remoteCheck.ExitCode -ne 0 -or -not $remoteCheck.Output) {
    $repoUrl = Ensure-GitHubRepository
    Write-Host "Adding remote origin: $repoUrl"
    Git remote add origin $repoUrl
} else {
    Write-Host "Using existing remote: $($remoteCheck.Output.Trim())"
}

Write-Host "Pushing to GitHub..."
Git push -u origin main

Write-Host "Creating GitHub Release: $version"
$releaseView = GhTry release view $version
if ($releaseView.ExitCode -eq 0) {
    Write-Host "Release $version already exists. Uploading executable..."
    Gh release upload $version "dist/KaliLauncher.exe" --clobber
} else {
    Gh release create $version `
        "dist/KaliLauncher.exe" `
        --title "Kali Linux Portable $version" `
        --notes "WSL Kali portable launcher with Win-KeX TigerVNC start/stop and drive auto-detection."
}

Write-Host "Done."
Gh repo view --web
