# scripts/verify.ps1
# Run every static check + test suite in the repo. Intended to be the
# single command a contributor runs after .\scripts\setup.ps1 to confirm
# their environment is actually working.
#
# Mirrors the CI workflow in .github/workflows/ci.yml.

[CmdletBinding()]
param(
    [switch]$SkipTauri  # cargo check is slow on a cold target/ dir
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repo

$script:Failures = @()

function Run-Step {
    param([string]$name, [string]$cwd, [scriptblock]$body)
    Write-Host "`n==> $name" -ForegroundColor Cyan
    Push-Location $cwd
    try {
        & $body
        if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {
            throw "exit code $LASTEXITCODE"
        }
        Write-Host "  [ok] $name" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] $name -- $_" -ForegroundColor Red
        $script:Failures += $name
    } finally {
        Pop-Location
    }
}

# Make sure per-user tool dirs are on PATH even if the caller forgot.
foreach ($p in @(
    "$env:USERPROFILE\.cargo\bin",
    "$env:LOCALAPPDATA\fnm",
    "$env:USERPROFILE\.local\bin"
)) {
    if ((Test-Path $p) -and -not ($env:Path -split ';' | Where-Object { $_ -ieq $p })) {
        $env:Path = "$p;$env:Path"
    }
}

# Also pick up winget-installed fnm (versioned path) and the resolved Node bin.
Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Directory -ErrorAction SilentlyContinue `
    | Where-Object { $_.Name -like 'Schniz.fnm*' } `
    | ForEach-Object {
        if (-not ($env:Path -split ';' | Where-Object { $_ -ieq $_.FullName })) {
            $env:Path = "$($_.FullName);$env:Path"
        }
    }

# Activate fnm so node/pnpm become usable in this session.
if (Get-Command fnm -ErrorAction SilentlyContinue) {
    $fnmEnv = fnm env --use-on-cd 2>$null
    if ($fnmEnv) { $fnmEnv | Out-String | Invoke-Expression }
    # Pin to the .node-version entry if present.
    if (Test-Path (Join-Path $repo '.node-version')) {
        fnm use --install-if-missing 2>&1 | Out-Null
    }
    # Expose the active node dir (fnm resolves a per-shell symlink).
    $nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
    if ($nodeExe) {
        $env:Path = "$([System.IO.Path]::GetDirectoryName($nodeExe));$env:Path"
    }
}

Run-Step 'agent: uv sync --frozen' agent     { uv sync --frozen }
Run-Step 'agent: ruff check .'     agent     { uv run ruff check . }
Run-Step 'agent: mypy --strict'    agent     { uv run mypy }
Run-Step 'agent: pytest'           agent     { uv run pytest -q }

Run-Step 'frontend: pnpm install --frozen-lockfile' frontend { pnpm install --frozen-lockfile }
Run-Step 'frontend: pnpm typecheck'                 frontend { pnpm typecheck }
Run-Step 'frontend: pnpm test'                      frontend { pnpm test }

if (-not $SkipTauri) {
    Run-Step 'tauri: cargo check --locked' frontend/src-tauri { cargo check --locked }
}

Write-Host ''
Write-Host '================ verify summary ================' -ForegroundColor Cyan
if ($script:Failures.Count -eq 0) {
    Write-Host '  all green.' -ForegroundColor Green
    exit 0
} else {
    Write-Host "  $($script:Failures.Count) failing step(s):" -ForegroundColor Red
    foreach ($f in $script:Failures) { Write-Host "    - $f" -ForegroundColor Red }
    exit 1
}
