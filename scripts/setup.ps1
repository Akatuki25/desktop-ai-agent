# scripts/setup.ps1
# Idempotent Windows setup for desktop-ai-agent.
#
# - root pollution is limited to Visual Studio Build Tools (Rust linker dep).
# - everything else is per-user or project-local under vendor/ and models/.
# - safe to re-run; existing assets are skipped.
# - designed to NEVER leave the caller in a half-working state: missing
#   prerequisites cause a hard failure with a precise remediation command.
#
# Usage:
#   .\scripts\setup.ps1                 # full setup
#   .\scripts\setup.ps1 -SkipToolchain  # skip rustup/fnm/uv install
#   .\scripts\setup.ps1 -SkipModel      # skip GGUF model download (~5GB)
#   .\scripts\setup.ps1 -SkipVoicevox   # skip VOICEVOX engine
#   .\scripts\setup.ps1 -NoExecPolicy   # do not touch ExecutionPolicy

[CmdletBinding()]
param(
    [switch]$SkipToolchain,
    [switch]$SkipModel,
    [switch]$SkipVoicevox,
    [switch]$NoExecPolicy
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repo

# ---- versions (single source of truth) ----
# llama.cpp must be >= b8200 because we depend on the --jinja flag and
# the new delta.reasoning_content streaming field for Qwen3-style
# thinking. b4000 (the previous pin) silently dropped both.
$LLAMA_RELEASE  = 'b8798'
$LLAMA_ZIP      = "llama-$LLAMA_RELEASE-bin-win-cpu-x64.zip"
$LLAMA_URL      = "https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_RELEASE/$LLAMA_ZIP"

# unsloth/Qwen3.5-9B-GGUF is the actual current GGUF release for the
# Qwen3.5 dense model family. The original spec said "Qwen3.5 8B" but
# the closest published dense size is 9B; we use that.
$MODEL_REPO     = 'unsloth/Qwen3.5-9B-GGUF'
$MODEL_FILE     = 'Qwen3.5-9B-Q4_K_M.gguf'

# VOICEVOX 0.25.1 ships windows-cpu as a single-part 7z named .7z.001.
# 7-Zip handles the .001 entry point natively.
$VOICEVOX_VER   = '0.25.1'
$VOICEVOX_BASE  = "voicevox_engine-windows-cpu-$VOICEVOX_VER"
$VOICEVOX_FILE  = "$VOICEVOX_BASE.7z.001"
$VOICEVOX_URL   = "https://github.com/VOICEVOX/voicevox_engine/releases/download/$VOICEVOX_VER/$VOICEVOX_FILE"

# ---- warning aggregator (shown again at the end) ----
$script:Warnings = @()
function Add-Warning { param([string]$msg) $script:Warnings += $msg; Write-Host "  [warn] $msg" -ForegroundColor Yellow }

function Write-Step { param([string]$msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Skip { param([string]$msg) Write-Host "  [skip] $msg" -ForegroundColor DarkGray }
function Write-Ok   { param([string]$msg) Write-Host "  [ok] $msg"   -ForegroundColor Green }
function Fail       { param([string]$msg) Write-Host "`n[FAIL] $msg" -ForegroundColor Red; exit 1 }

function Test-Command {
    param([string]$name)
    $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Ensure-Dir { param([string]$path) New-Item -ItemType Directory -Force -Path $path | Out-Null }

function Add-PathOnce {
    param([string]$p)
    if (-not (Test-Path $p)) { return }
    if (-not ($env:Path -split ';' | Where-Object { $_ -ieq $p })) {
        $env:Path = "$p;$env:Path"
    }
}

function Download-File {
    param([string]$url, [string]$out)
    if (Test-Path $out) { Write-Skip "already downloaded: $out"; return }
    Write-Host "  downloading $url" -ForegroundColor DarkGray
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
}

# ---- ExecutionPolicy (per-user only, so activate.ps1 can be dot-sourced) ----
if (-not $NoExecPolicy) {
    $current = Get-ExecutionPolicy -Scope CurrentUser
    if ($current -eq 'Restricted' -or $current -eq 'Undefined' -or $current -eq 'AllSigned') {
        Write-Host "  setting CurrentUser ExecutionPolicy to RemoteSigned (was: $current)" -ForegroundColor DarkGray
        try {
            Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force `
                -WarningAction SilentlyContinue -ErrorAction Stop
        } catch {
            # Process-scope policy (e.g. -ExecutionPolicy Bypass on the
            # current pwsh) shadows CurrentUser and surfaces here as a
            # SecurityException. Harmless: the user scope was still set.
            Write-Host "  (CurrentUser policy update warning ignored: $($_.Exception.Message))" -ForegroundColor DarkGray
        }
    }
}

# ---- 0. preflight (HARD failures, not warnings) ----
Write-Step '0. preflight'

if (-not (Test-Command git)) {
    Fail @"
git not found.

Install with:
    winget install --id Git.Git -e

Then re-run this script.
"@
}
Write-Ok 'git'

# Visual Studio Build Tools with the C++ workload is required by Rust/Tauri on
# Windows. This is the ONLY dependency that touches system state — but we
# refuse to proceed without it because every later step would silently break.
$vsCandidates = @(
    'C:\Program Files (x86)\Microsoft Visual Studio\*\BuildTools\VC\Tools\MSVC',
    'C:\Program Files\Microsoft Visual Studio\*\BuildTools\VC\Tools\MSVC',
    'C:\Program Files (x86)\Microsoft Visual Studio\*\Community\VC\Tools\MSVC',
    'C:\Program Files\Microsoft Visual Studio\*\Community\VC\Tools\MSVC'
)
$hasMsvc = $false
foreach ($pat in $vsCandidates) {
    if (Get-ChildItem $pat -ErrorAction SilentlyContinue) { $hasMsvc = $true; break }
}
if (-not $hasMsvc) {
    Fail @"
Visual Studio Build Tools (C++ workload) not detected.
This is required by Rust/Tauri on Windows and is the only system-level
dependency of this project. Install it with:

    winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override ``
      "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"

(The --passive installer is ~3GB and needs admin. Close this script, run
the command above in an elevated PowerShell, then re-run setup.ps1.)
"@
}
Write-Ok 'VS Build Tools detected'

if (-not (Test-Command winget)) {
    Fail @"
winget not found. This script uses winget for fnm/VS Build Tools.
Update Windows App Installer from the Microsoft Store, or run:

    https://aka.ms/getwinget

then re-run this script.
"@
}
Write-Ok 'winget'

# ---- 1. per-user toolchains ----
if (-not $SkipToolchain) {
    Write-Step '1a. rustup (per-user)'
    Add-PathOnce "$env:USERPROFILE\.cargo\bin"
    if (Test-Command rustc) {
        Write-Skip "rustc already available: $(rustc --version)"
    } else {
        $rustupInit = Join-Path $env:TEMP 'rustup-init.exe'
        Download-File 'https://win.rustup.rs/x86_64' $rustupInit
        & $rustupInit -y --default-toolchain stable --profile minimal
        if ($LASTEXITCODE -ne 0) { Fail 'rustup-init failed.' }
        Remove-Item $rustupInit -Force
        Add-PathOnce "$env:USERPROFILE\.cargo\bin"
        if (-not (Test-Command rustc)) { Fail 'rustc still not on PATH after rustup install.' }
        Write-Ok "rustup installed ($(rustc --version))"
    }

    Write-Step '1b. fnm (per-user Node manager)'
    Add-PathOnce "$env:LOCALAPPDATA\fnm"
    if (Test-Command fnm) {
        Write-Skip 'fnm already installed'
    } else {
        winget install --id Schniz.fnm -e --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) { Fail 'winget install Schniz.fnm failed.' }
        Add-PathOnce "$env:LOCALAPPDATA\fnm"
        # winget occasionally installs under a versioned path
        Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Directory -ErrorAction SilentlyContinue `
            | Where-Object { $_.Name -like 'Schniz.fnm*' } `
            | ForEach-Object { Add-PathOnce $_.FullName }
        if (-not (Test-Command fnm)) {
            Add-Warning 'fnm installed but not on PATH in this session. Open a new shell and re-run setup.ps1 -SkipToolchain to continue.'
        } else {
            Write-Ok 'fnm installed'
        }
    }

    Write-Step '1c. uv (per-user Python manager)'
    Add-PathOnce "$env:USERPROFILE\.local\bin"
    if (Test-Command uv) {
        Write-Skip "uv already available: $(uv --version)"
    } else {
        powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
        if ($LASTEXITCODE -ne 0) { Fail 'uv installer failed.' }
        Add-PathOnce "$env:USERPROFILE\.local\bin"
        if (-not (Test-Command uv)) { Fail 'uv still not on PATH after install.' }
        Write-Ok "uv installed ($(uv --version))"
    }
} else {
    Write-Step '1. per-user toolchains (skipped)'
    Add-PathOnce "$env:USERPROFILE\.cargo\bin"
    Add-PathOnce "$env:LOCALAPPDATA\fnm"
    Add-PathOnce "$env:USERPROFILE\.local\bin"
}

# ---- 2. project dependencies ----
Write-Step '2a. Node via fnm'
if (Test-Path (Join-Path $repo '.node-version')) {
    if (-not (Test-Command fnm)) {
        Add-Warning 'fnm not on PATH in this session — skipping fnm use. Open a new shell and re-run.'
    } else {
        # `fnm use` only works once `fnm env` has been evaluated in the
        # current shell so $env:FNM_DIR / $env:FNM_MULTISHELL_PATH are
        # set. We pipe that into Invoke-Expression here so a brand new
        # PowerShell session works without a profile.
        try {
            fnm env --use-on-cd | Out-String | Invoke-Expression
        } catch {
            Add-Warning "fnm env init failed: $($_.Exception.Message)"
        }

        Push-Location $repo
        fnm use --install-if-missing
        if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'fnm use failed.' }

        # Surface node + npm globals in this session so subsequent
        # corepack / pnpm / pnpm install steps find them.
        $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
        if ($nodeCmd) {
            Add-PathOnce ([System.IO.Path]::GetDirectoryName($nodeCmd.Source))
        }

        # Node 22.11's bundled corepack has a stale signing key; bumping
        # it to latest before enabling avoids a hard failure when it
        # tries to fetch pnpm.
        npm install -g corepack@latest 2>&1 | Out-Null
        corepack enable 2>&1 | Out-Null
        corepack prepare pnpm@9.15.0 --activate 2>&1 | Out-Null
        Pop-Location
        Write-Ok 'node + pnpm ready'
    }
} else {
    Add-Warning '.node-version not found at repo root — skipping fnm use.'
}

Write-Step '2b. frontend (pnpm install)'
$frontendDir = Join-Path $repo 'frontend'
if (Test-Path (Join-Path $frontendDir 'package.json')) {
    if (-not (Test-Command pnpm)) {
        Add-Warning 'pnpm not on PATH — open a new shell and re-run to install frontend deps.'
    } else {
        Push-Location $frontendDir
        pnpm install
        if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'pnpm install failed.' }
        Pop-Location
        Write-Ok 'frontend deps installed'
    }
} else {
    Write-Skip 'frontend/package.json not yet present'
}

Write-Step '2c. agent (uv sync)'
$agentDir = Join-Path $repo 'agent'
if (Test-Path (Join-Path $agentDir 'pyproject.toml')) {
    Push-Location $agentDir
    uv sync
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'uv sync failed.' }
    Pop-Location
    Write-Ok 'agent deps installed'
} else {
    Write-Skip 'agent/pyproject.toml not yet present'
}

# ---- 3. project-local binaries ----
Ensure-Dir (Join-Path $repo 'vendor')
Ensure-Dir (Join-Path $repo 'models')

Write-Step '3a. llama.cpp (prebuilt)'
$llamaDir = Join-Path $repo 'vendor\llama.cpp'
$llamaExe = Join-Path $llamaDir 'llama-server.exe'

function Get-LlamaServerBuild {
    param([string]$exe)
    if (-not (Test-Path $exe)) { return 0 }
    # Run via cmd /c so PowerShell does not parse stderr lines as
    # ErrorRecord objects (llama-server emits backend-load notices to
    # stderr before printing its version banner).
    $out = cmd /c "`"$exe`" --version 2>&1"
    $m = [regex]::Match($out, 'version:\s*(\d+)')
    if ($m.Success) { return [int]$m.Groups[1].Value }
    return 0
}

$needLlama = $true
if (Test-Path $llamaExe) {
    $build = Get-LlamaServerBuild $llamaExe
    if ($build -ge 8200) {
        Write-Skip "llama-server.exe already at $llamaExe (b$build)"
        $needLlama = $false
    } elseif ($build -gt 0) {
        Write-Host "  llama-server.exe is b$build (< b8200, missing --jinja) — replacing" -ForegroundColor DarkGray
        Remove-Item -Recurse -Force $llamaDir
    } else {
        Write-Host "  llama-server.exe present but version unreadable — replacing" -ForegroundColor DarkGray
        Remove-Item -Recurse -Force $llamaDir
    }
}

if ($needLlama) {
    Ensure-Dir $llamaDir
    $zipOut = Join-Path $env:TEMP $LLAMA_ZIP
    Download-File $LLAMA_URL $zipOut
    Expand-Archive -Path $zipOut -DestinationPath $llamaDir -Force
    Remove-Item $zipOut -Force
    if (-not (Test-Path $llamaExe)) { Fail "llama-server.exe missing after extraction ($llamaDir)." }
    $build = Get-LlamaServerBuild $llamaExe
    if ($build -lt 8200) {
        Fail "downloaded llama-server.exe is b$build (< b8200); update `$LLAMA_RELEASE."
    }
    Write-Ok "llama.cpp b$build extracted"
}

Write-Step '3b. Qwen3.5 GGUF model'
$modelsDir = Join-Path $repo 'models'
Ensure-Dir $modelsDir
$modelPath = Join-Path $modelsDir $MODEL_FILE
if ($SkipModel) {
    Write-Skip 'model download skipped (flag)'
} elseif (Test-Path $modelPath) {
    $sizeMb = [math]::Round((Get-Item $modelPath).Length / 1MB)
    Write-Skip "$MODEL_FILE already at $modelPath ($sizeMb MB)"
} else {
    Write-Host "  downloading $MODEL_REPO/$MODEL_FILE (~5GB) via hf-cli" -ForegroundColor DarkGray
    if (-not (Test-Command uv)) { Fail 'uv not on PATH; cannot drive hf download.' }
    # `huggingface-cli download` is deprecated; the new entry point is
    # `hf download`. We pass an absolute --local-dir so the file lands
    # under repo\models\ regardless of the caller's CWD (an earlier bug
    # let it land under whatever directory we happened to be in).
    uv tool run --from huggingface_hub hf download `
        $MODEL_REPO $MODEL_FILE `
        --local-dir $modelsDir
    if ($LASTEXITCODE -ne 0) { Fail 'hf download failed.' }
    if (-not (Test-Path $modelPath)) {
        Fail "model file missing after hf download (expected $modelPath)."
    }
    $sizeMb = [math]::Round((Get-Item $modelPath).Length / 1MB)
    if ($sizeMb -lt 1000) {
        Fail "model file is suspiciously small ($sizeMb MB) — refusing to continue."
    }
    Write-Ok "model downloaded ($sizeMb MB)"
}

Write-Step '3c. Playwright Chromium (project-local cache)'
$playwrightDir = Join-Path $repo 'vendor\playwright-browsers'
$env:PLAYWRIGHT_BROWSERS_PATH = $playwrightDir
if ((Test-Path $playwrightDir) -and (Get-ChildItem $playwrightDir -ErrorAction SilentlyContinue)) {
    Write-Skip 'playwright browsers already present'
} elseif (-not (Test-Path (Join-Path $agentDir 'pyproject.toml'))) {
    Write-Skip 'agent not yet scaffolded — run playwright install later'
} else {
    # Phase 4 wires the agent's playwright dependency in. Until then
    # the `playwright` CLI isn't in the venv and there's nothing to
    # install, so probe first instead of failing setup.
    Push-Location $agentDir
    cmd /c "uv run playwright --version > nul 2>&1"
    if ($LASTEXITCODE -eq 0) {
        uv run playwright install chromium
        if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'playwright install failed.' }
        Write-Ok 'chromium installed to vendor/'
    } else {
        Write-Skip 'playwright not in agent deps yet (Phase 4) — skipping browser install'
    }
    Pop-Location
}

Write-Step '3d. VOICEVOX engine (portable)'
$vvDir = Join-Path $repo 'vendor\voicevox'
$vvBin = Join-Path $vvDir 'run.exe'
if ($SkipVoicevox) {
    Write-Skip 'voicevox skipped (flag)'
} elseif (Test-Path $vvBin) {
    Write-Skip "voicevox already at $vvBin"
} else {
    if (-not (Test-Command 7z)) {
        Write-Host '  7-Zip not found — installing (winget)' -ForegroundColor DarkGray
        winget install --id 7zip.7zip -e --accept-source-agreements --accept-package-agreements
        Add-PathOnce 'C:\Program Files\7-Zip'
    }
    if (-not (Test-Command 7z)) {
        Fail '7-Zip install failed and is required to extract VOICEVOX. Install 7-Zip manually and re-run.'
    }
    # VOICEVOX 0.25+ packages windows-cpu as a single-part 7z named
    # `<base>.7z.001`. 7-Zip's CLI knows how to enter the .001 file
    # without explicit reassembly. The extracted directory name varies
    # across releases (e.g. 0.25.1 ships as `windows-cpu/`), so we
    # locate run.exe ourselves rather than guessing the path.
    $archive = Join-Path $env:TEMP $VOICEVOX_FILE
    Download-File $VOICEVOX_URL $archive
    $extractTo = Join-Path $repo 'vendor'
    & 7z x $archive "-o$extractTo" -y | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail 'voicevox extraction failed.' }

    $candidate = Get-ChildItem $extractTo -Directory `
        | Where-Object { Test-Path (Join-Path $_.FullName 'run.exe') } `
        | Select-Object -First 1
    if (-not $candidate) {
        Fail "voicevox extraction completed but run.exe is nowhere under $extractTo."
    }
    if (Test-Path $vvDir) { Remove-Item -Recurse -Force $vvDir }
    Rename-Item $candidate.FullName $vvDir
    Remove-Item $archive -Force
    if (-not (Test-Path $vvBin)) { Fail "voicevox run.exe missing after extraction ($vvDir)." }
    Write-Ok 'voicevox extracted'
}

# ---- 4. .env scaffold ----
Write-Step '4. .env scaffold'
$envFile = Join-Path $repo '.env'
$envExample = Join-Path $repo '.env.example'
if (-not (Test-Path $envFile) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envFile
    Write-Ok '.env created from .env.example — fill in secrets'
} elseif (Test-Path $envFile) {
    Write-Skip '.env already exists'
} else {
    Add-Warning '.env.example missing, .env not created'
}

# ---- final summary ----
Write-Host ''
Write-Host '================ summary ================' -ForegroundColor Cyan
if ($script:Warnings.Count -eq 0) {
    Write-Host '  all checks passed.' -ForegroundColor Green
} else {
    Write-Host "  $($script:Warnings.Count) warning(s):" -ForegroundColor Yellow
    foreach ($w in $script:Warnings) { Write-Host "    - $w" -ForegroundColor Yellow }
}
Write-Host ''
Write-Host 'next steps:' -ForegroundColor Cyan
Write-Host '  1.  fill in .env (DEEPGRAM_API_KEY etc.)'
Write-Host '  2.  . .\scripts\activate.ps1'
Write-Host '  3.  cd frontend; pnpm tauri dev'
if ($script:Warnings.Count -gt 0) { exit 2 }
