#!/usr/bin/env bash
# scripts/setup.sh
# Idempotent macOS setup for desktop-ai-agent. Mirrors scripts/setup.ps1.
#
# - root pollution is limited to Xcode Command Line Tools (Rust / native deps).
# - everything else is per-user (~/.cargo, ~/.local/bin, fnm) or project-local
#   under vendor/ and models/.
# - safe to re-run; existing assets are skipped.
# - missing prerequisites cause a hard failure with a precise remediation
#   command (no half-working states).
#
# Usage:
#   scripts/setup.sh                    # full setup with 9B model
#   scripts/setup.sh --model 4B         # use the lighter 4B model (~2.4GB)
#   scripts/setup.sh --skip-toolchain   # skip rustup/fnm/uv install
#   scripts/setup.sh --skip-model       # skip GGUF model download
#   scripts/setup.sh --skip-voicevox    # skip VOICEVOX engine

set -euo pipefail

# ---- arg parsing ----
SKIP_TOOLCHAIN=0
SKIP_MODEL=0
SKIP_VOICEVOX=0
MODEL_SIZE=9B

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-toolchain) SKIP_TOOLCHAIN=1 ;;
        --skip-model)     SKIP_MODEL=1 ;;
        --skip-voicevox)  SKIP_VOICEVOX=1 ;;
        --model)          MODEL_SIZE="${2:?--model needs 9B|4B}"; shift ;;
        --model=*)        MODEL_SIZE="${1#*=}" ;;
        -h|--help)
            sed -n '1,30p' "$0"; exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 1 ;;
    esac
    shift
done

if [[ "$MODEL_SIZE" != "9B" && "$MODEL_SIZE" != "4B" ]]; then
    echo "--model must be 9B or 4B (got: $MODEL_SIZE)" >&2; exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# ---- versions (single source of truth, mirror setup.ps1) ----
LLAMA_RELEASE='b8798'

case "$MODEL_SIZE" in
    9B) MODEL_REPO='unsloth/Qwen3.5-9B-GGUF'; MODEL_FILE='Qwen3.5-9B-Q4_K_M.gguf'; MODEL_SIZE_MB=5400 ;;
    4B) MODEL_REPO='unsloth/Qwen3.5-4B-GGUF'; MODEL_FILE='Qwen3.5-4B-Q4_K_M.gguf'; MODEL_SIZE_MB=2400 ;;
esac
MODEL_MIN_MB=$(( MODEL_SIZE_MB * 8 / 10 ))

VOICEVOX_VER='0.25.1'

# ---- detect arch ----
UNAME_M="$(uname -m)"
case "$UNAME_M" in
    arm64|aarch64) MAC_ARCH='arm64' ;;
    x86_64)        MAC_ARCH='x64' ;;
    *) echo "[FAIL] unsupported architecture: $UNAME_M" >&2; exit 1 ;;
esac

# macOS prebuilts are tar.gz (not zip like the windows artifacts).
LLAMA_TAR="llama-${LLAMA_RELEASE}-bin-macos-${MAC_ARCH}.tar.gz"
LLAMA_URL="https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_RELEASE}/${LLAMA_TAR}"

# VOICEVOX 0.25 ships macos as a single-part 7z named .7z.001.
VOICEVOX_FILE="voicevox_engine-macos-${MAC_ARCH}-${VOICEVOX_VER}.7z.001"
VOICEVOX_URL="https://github.com/VOICEVOX/voicevox_engine/releases/download/${VOICEVOX_VER}/${VOICEVOX_FILE}"

# ---- pretty printers ----
WARNINGS=()
have()      { command -v "$1" >/dev/null 2>&1; }
step()      { printf '\n==> %s\n' "$1"; }
ok()        { printf '  [ok] %s\n' "$1"; }
skip()      { printf '  [skip] %s\n' "$1"; }
warn()      { WARNINGS+=("$1"); printf '  [warn] %s\n' "$1"; }
fail()      { printf '\n[FAIL] %s\n' "$1" >&2; exit 1; }

add_path_once() {
    local p="$1"
    [[ -d "$p" ]] || return 0
    case ":$PATH:" in *":$p:"*) ;; *) PATH="$p:$PATH" ;; esac
}

download_file() {
    local url="$1" out="$2"
    if [[ -f "$out" ]]; then skip "already downloaded: $out"; return 0; fi
    printf '  downloading %s\n' "$url"
    curl -fL --retry 3 --retry-delay 2 -o "$out.part" "$url"
    mv "$out.part" "$out"
}

# ---- 0. preflight ----
step '0. preflight'

if [[ "$(uname -s)" != "Darwin" ]]; then
    fail "setup.sh is for macOS. On Linux, install rustup/uv/fnm manually then run with --skip-toolchain."
fi

if ! have git; then
    fail "git not found. Install Xcode Command Line Tools:
    xcode-select --install
then re-run this script."
fi
ok "git ($(git --version | awk '{print $3}'))"

# Xcode CLI tools — required for cc/clang and rustc linker.
if ! xcode-select -p >/dev/null 2>&1; then
    fail "Xcode Command Line Tools not installed.
Install with:
    xcode-select --install
A GUI installer pops up. After it finishes, re-run this script."
fi
ok "Xcode CLT ($(xcode-select -p))"

if ! have curl; then fail "curl not found (should come with macOS — check PATH)."; fi
ok 'curl'

# ---- 1. per-user toolchains ----
if [[ $SKIP_TOOLCHAIN -eq 0 ]]; then
    step '1a. rustup (per-user)'
    add_path_once "$HOME/.cargo/bin"
    if have rustc; then
        skip "rustc already available: $(rustc --version)"
    else
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- \
            -y --default-toolchain stable --profile minimal --no-modify-path
        add_path_once "$HOME/.cargo/bin"
        have rustc || fail 'rustc still not on PATH after rustup install.'
        ok "rustup installed ($(rustc --version))"
    fi

    step '1b. fnm (per-user Node manager)'
    if have fnm; then
        skip "fnm already installed ($(fnm --version))"
    else
        if have brew; then
            brew install fnm
        else
            # Official installer — drops fnm into ~/.local/share/fnm by default.
            curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell
            add_path_once "$HOME/.local/share/fnm"
        fi
        have fnm || warn 'fnm installed but not on PATH in this shell. Open a new terminal and re-run with --skip-toolchain.'
        have fnm && ok "fnm installed ($(fnm --version))"
    fi

    step '1c. uv (per-user Python manager)'
    add_path_once "$HOME/.local/bin"
    if have uv; then
        skip "uv already available: $(uv --version)"
    else
        curl -LsSf https://astral.sh/uv/install.sh | sh
        add_path_once "$HOME/.local/bin"
        have uv || fail 'uv still not on PATH after install.'
        ok "uv installed ($(uv --version))"
    fi
else
    step '1. per-user toolchains (skipped)'
    add_path_once "$HOME/.cargo/bin"
    add_path_once "$HOME/.local/bin"
    add_path_once "$HOME/.local/share/fnm"
fi

# ---- 2. project dependencies ----
step '2a. Node via fnm'
if [[ -f "$REPO/.node-version" ]]; then
    if ! have fnm; then
        warn 'fnm not on PATH in this shell — skipping fnm use.'
    else
        # `fnm env` exports FNM_DIR / FNM_MULTISHELL_PATH so subsequent
        # `fnm use` and `node` lookups work without a shell rc file.
        eval "$(fnm env --use-on-cd --shell bash)"
        ( cd "$REPO" && fnm use --install-if-missing )
        # Surface node bin in this script's PATH.
        if have node; then
            add_path_once "$(dirname "$(command -v node)")"
        fi
        # Refresh corepack: bundled corepack on Node 22.x has stale signing
        # keys for pnpm@latest fetches.
        npm install -g corepack@latest >/dev/null 2>&1 || true
        corepack enable >/dev/null 2>&1 || true
        corepack prepare pnpm@9.15.0 --activate >/dev/null 2>&1 || true
        ok 'node + pnpm ready'
    fi
else
    warn '.node-version not found at repo root — skipping fnm use.'
fi

step '2b. frontend (pnpm install)'
if [[ -f "$REPO/frontend/package.json" ]]; then
    if ! have pnpm; then
        warn 'pnpm not on PATH — open a new shell and re-run to install frontend deps.'
    else
        ( cd "$REPO/frontend" && pnpm install )
        ok 'frontend deps installed'
    fi
else
    skip 'frontend/package.json not yet present'
fi

step '2c. agent (uv sync)'
if [[ -f "$REPO/agent/pyproject.toml" ]]; then
    have uv || fail 'uv missing — re-run setup.sh without --skip-toolchain.'
    ( cd "$REPO/agent" && uv sync )
    ok 'agent deps installed'
else
    skip 'agent/pyproject.toml not yet present'
fi

# ---- 3. project-local binaries ----
mkdir -p "$REPO/vendor" "$REPO/models"

step '3a. llama.cpp (prebuilt)'
LLAMA_DIR="$REPO/vendor/llama.cpp"
LLAMA_BIN="$LLAMA_DIR/llama-server"

get_llama_build() {
    local exe="$1"
    [[ -x "$exe" ]] || { echo 0; return; }
    local out; out=$("$exe" --version 2>&1 || true)
    local m; m=$(printf '%s' "$out" | grep -oE 'version:[[:space:]]*[0-9]+' | head -n1 | grep -oE '[0-9]+' || true)
    echo "${m:-0}"
}

NEED_LLAMA=1
if [[ -x "$LLAMA_BIN" ]]; then
    BUILD=$(get_llama_build "$LLAMA_BIN")
    if (( BUILD >= 8200 )); then
        skip "llama-server already at $LLAMA_BIN (b$BUILD)"
        NEED_LLAMA=0
    else
        printf '  llama-server is b%s (< b8200) — replacing\n' "$BUILD"
        rm -rf "$LLAMA_DIR"
    fi
fi

if (( NEED_LLAMA )); then
    mkdir -p "$LLAMA_DIR"
    TAR_OUT="${TMPDIR:-/tmp}/$LLAMA_TAR"
    download_file "$LLAMA_URL" "$TAR_OUT"
    tar -xzf "$TAR_OUT" -C "$LLAMA_DIR"
    rm -f "$TAR_OUT"

    # Recent llama.cpp macOS zips put the binary under build/bin/. Hoist it
    # to a stable path so activate.sh / Tauri don't have to guess.
    if [[ ! -x "$LLAMA_BIN" ]]; then
        FOUND="$(find "$LLAMA_DIR" -type f -name 'llama-server' -perm -u+x | head -n1 || true)"
        [[ -n "$FOUND" ]] || fail "llama-server missing after extraction ($LLAMA_DIR)."
        # Symlink rather than move so adjacent dylibs (Frameworks/, ggml libs)
        # keep their original layout.
        ln -sf "$FOUND" "$LLAMA_BIN"
    fi

    # Mac Gatekeeper sometimes quarantines downloads — strip the attribute
    # so the first run isn't a "killed: 9" with no clear error.
    xattr -dr com.apple.quarantine "$LLAMA_DIR" 2>/dev/null || true

    BUILD=$(get_llama_build "$LLAMA_BIN")
    (( BUILD >= 8200 )) || fail "downloaded llama-server is b$BUILD (< b8200); update LLAMA_RELEASE."
    ok "llama.cpp b$BUILD extracted"
fi

step '3b. Qwen3.5 GGUF model'
MODELS_DIR="$REPO/models"
MODEL_PATH="$MODELS_DIR/$MODEL_FILE"
if (( SKIP_MODEL )); then
    skip 'model download skipped (flag)'
elif [[ -f "$MODEL_PATH" ]]; then
    SIZE_MB=$(( $(stat -f%z "$MODEL_PATH") / 1024 / 1024 ))
    skip "$MODEL_FILE already at $MODEL_PATH (${SIZE_MB} MB)"
else
    have uv || fail 'uv not on PATH; cannot drive hf download.'
    printf '  downloading %s/%s via hf-cli\n' "$MODEL_REPO" "$MODEL_FILE"
    uv tool run --from huggingface_hub hf download \
        "$MODEL_REPO" "$MODEL_FILE" \
        --local-dir "$MODELS_DIR"
    [[ -f "$MODEL_PATH" ]] || fail "model file missing after hf download (expected $MODEL_PATH)."
    SIZE_MB=$(( $(stat -f%z "$MODEL_PATH") / 1024 / 1024 ))
    if (( SIZE_MB < MODEL_MIN_MB )); then
        fail "model file is suspiciously small (${SIZE_MB} MB < expected ~${MODEL_SIZE_MB} MB) — refusing to continue."
    fi
    ok "model downloaded (${SIZE_MB} MB)"
fi

step '3c. Playwright Chromium (project-local cache, deferred to Phase 4)'
PLAYWRIGHT_DIR="$REPO/vendor/playwright-browsers"
export PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_DIR"
if [[ -d "$PLAYWRIGHT_DIR" ]] && [[ -n "$(ls -A "$PLAYWRIGHT_DIR" 2>/dev/null)" ]]; then
    skip 'playwright browsers already present'
elif [[ ! -f "$REPO/agent/pyproject.toml" ]]; then
    skip 'agent not yet scaffolded — run playwright install later'
else
    if ( cd "$REPO/agent" && uv run playwright --version >/dev/null 2>&1 ); then
        ( cd "$REPO/agent" && uv run playwright install chromium )
        ok 'chromium installed to vendor/'
    else
        skip 'playwright not in agent deps yet (Phase 4) — skipping browser install'
    fi
fi

step '3d. VOICEVOX engine (portable)'
VV_DIR="$REPO/vendor/voicevox"
# macOS uses run / run.command; we look for either via find later.
VV_BIN_HINT="$VV_DIR/run"
if (( SKIP_VOICEVOX )); then
    skip 'voicevox skipped (flag)'
elif [[ -x "$VV_BIN_HINT" ]] || [[ -x "$VV_DIR/run.command" ]]; then
    skip "voicevox already at $VV_DIR"
else
    if ! have 7z && ! have 7zz; then
        if have brew; then
            printf '  7-Zip not found — installing via brew\n'
            brew install p7zip
        else
            warn '7-Zip missing and Homebrew not installed — skipping VOICEVOX. Install with: brew install p7zip; then re-run.'
            SKIP_VOICEVOX=1
        fi
    fi

    if (( SKIP_VOICEVOX == 0 )); then
        ARCHIVE="${TMPDIR:-/tmp}/$VOICEVOX_FILE"
        if ! download_file "$VOICEVOX_URL" "$ARCHIVE"; then
            warn "VOICEVOX download failed (URL may have moved): $VOICEVOX_URL — skipping. Re-run with --skip-voicevox to silence."
        else
            EXTRACT_TO="$REPO/vendor"
            if have 7z; then
                7z x "$ARCHIVE" "-o$EXTRACT_TO" -y >/dev/null
            else
                7zz x "$ARCHIVE" "-o$EXTRACT_TO" -y >/dev/null
            fi

            # The extracted dir name varies by release; locate `run`/`run.command`.
            CANDIDATE=""
            for d in "$EXTRACT_TO"/*/; do
                [[ -d "$d" ]] || continue
                if [[ -x "${d}run" ]] || [[ -x "${d}run.command" ]]; then
                    CANDIDATE="${d%/}"
                    break
                fi
            done
            if [[ -z "$CANDIDATE" ]]; then
                warn "voicevox extracted but run binary not found under $EXTRACT_TO — skipping."
            else
                rm -rf "$VV_DIR"
                mv "$CANDIDATE" "$VV_DIR"
                rm -f "$ARCHIVE"
                xattr -dr com.apple.quarantine "$VV_DIR" 2>/dev/null || true
                if [[ -x "$VV_DIR/run" ]] || [[ -x "$VV_DIR/run.command" ]]; then
                    ok 'voicevox extracted'
                else
                    warn "voicevox installed but run binary missing — TTS will be disabled."
                fi
            fi
        fi
    fi
fi

# ---- 4. .env scaffold ----
step '4. .env scaffold'
if [[ ! -f "$REPO/.env" && -f "$REPO/.env.example" ]]; then
    cp "$REPO/.env.example" "$REPO/.env"
    ok '.env created from .env.example — fill in secrets'
elif [[ -f "$REPO/.env" ]]; then
    skip '.env already exists'
else
    warn '.env.example missing, .env not created'
fi

# ---- final summary ----
printf '\n================ summary ================\n'
if (( ${#WARNINGS[@]} == 0 )); then
    printf '  all checks passed.\n'
else
    printf '  %d warning(s):\n' "${#WARNINGS[@]}"
    for w in "${WARNINGS[@]}"; do printf '    - %s\n' "$w"; done
fi
printf '\nnext steps:\n'
printf '  1.  fill in .env (DEEPGRAM_API_KEY etc.)\n'
printf '  2.  source ./scripts/activate.sh\n'
printf '  3.  cd frontend && pnpm tauri dev\n'

if (( ${#WARNINGS[@]} > 0 )); then exit 2; fi
