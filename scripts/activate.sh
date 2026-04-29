#!/usr/bin/env bash
# scripts/activate.sh
# Repo-local environment activation for macOS / Linux. Process scope only —
# closing the shell restores the original environment.
#
# Usage:
#   source ./scripts/activate.sh
#
# Sets PLAYWRIGHT_BROWSERS_PATH, LLAMA_SERVER_BIN, LLAMA_MODEL, VOICEVOX_BIN,
# AGENT_DATA_DIR, surfaces fnm/node/pnpm/cargo/uv on PATH, and loads
# repo/.env (KEY=VALUE lines) into the current session.
#
# Mirrors scripts/activate.ps1.

# guard: must be sourced (env vars are pointless in a subprocess).
if [[ "${BASH_SOURCE[0]:-$0}" == "${0}" ]] && [[ -z "${ZSH_EVAL_CONTEXT:-}" ]]; then
    echo "activate.sh must be sourced: \`source ./scripts/activate.sh\`" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")/.." && pwd)"
export REPO_ROOT

# Pick the platform's user data dir so the daemon stores db.sqlite/logs/etc
# in a stable, OS-conventional location.
case "$(uname -s)" in
    Darwin) AGENT_DATA_DIR_DEFAULT="$HOME/Library/Application Support/desktop-ai-agent" ;;
    Linux)  AGENT_DATA_DIR_DEFAULT="${XDG_DATA_HOME:-$HOME/.local/share}/desktop-ai-agent" ;;
    *)      AGENT_DATA_DIR_DEFAULT="$HOME/.desktop-ai-agent" ;;
esac

export PLAYWRIGHT_BROWSERS_PATH="$REPO_ROOT/vendor/playwright-browsers"
export LLAMA_SERVER_BIN="$REPO_ROOT/vendor/llama.cpp/llama-server"
# VOICEVOX 0.20+ ships either `run` or `run.command` on macOS — pick whichever exists.
if [[ -x "$REPO_ROOT/vendor/voicevox/run" ]]; then
    export VOICEVOX_BIN="$REPO_ROOT/vendor/voicevox/run"
elif [[ -x "$REPO_ROOT/vendor/voicevox/run.command" ]]; then
    export VOICEVOX_BIN="$REPO_ROOT/vendor/voicevox/run.command"
else
    export VOICEVOX_BIN="$REPO_ROOT/vendor/voicevox/run"
fi
export AGENT_DATA_DIR="${AGENT_DATA_DIR:-$AGENT_DATA_DIR_DEFAULT}"

# ---- Load .env first so it can override LLAMA_MODEL / MODEL_SIZE below ----
# This file is sourced from the user's shell, which may be zsh (default on
# macOS) — bash-isms like BASH_REMATCH won't work there. `set -a` makes
# any plain `KEY=value` assignment exported, so we can just source the
# .env as if it were a script. Comments and blank lines are skipped by
# the shell parser; surrounding quotes are stripped automatically.
ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
    printf '  .env loaded\n'
else
    printf '  .env not found (copy .env.example to .env)\n' >&2
fi

# ---- LLAMA_MODEL resolution (mirrors activate.ps1 logic) ----
MODELS_DIR="$REPO_ROOT/models"
MODEL_9B="$MODELS_DIR/Qwen3.5-9B-Q4_K_M.gguf"
MODEL_4B="$MODELS_DIR/Qwen3.5-4B-Q4_K_M.gguf"

if [[ -n "${LLAMA_MODEL:-}" && -f "$LLAMA_MODEL" ]]; then
    : # honor explicit override
elif [[ "${MODEL_SIZE:-}" == "4B" && -f "$MODEL_4B" ]]; then
    export LLAMA_MODEL="$MODEL_4B"
elif [[ "${MODEL_SIZE:-}" == "9B" && -f "$MODEL_9B" ]]; then
    export LLAMA_MODEL="$MODEL_9B"
elif [[ -f "$MODEL_9B" ]]; then
    export LLAMA_MODEL="$MODEL_9B"
elif [[ -f "$MODEL_4B" ]]; then
    export LLAMA_MODEL="$MODEL_4B"
else
    ANY="$(ls "$MODELS_DIR"/Qwen3.5-*.gguf 2>/dev/null | head -n1 || true)"
    if [[ -n "$ANY" ]]; then
        export LLAMA_MODEL="$ANY"
    else
        export LLAMA_MODEL="$MODEL_9B"  # missing-asset warning below
    fi
fi

# ---- PATH: surface per-user toolchains ----
add_path_once() {
    local p="$1"
    [[ -d "$p" ]] || return 0
    case ":$PATH:" in *":$p:"*) ;; *) PATH="$p:$PATH" ;; esac
}
add_path_once "$HOME/.cargo/bin"
add_path_once "$HOME/.local/bin"
add_path_once "$HOME/.local/share/fnm"
# Homebrew (Apple Silicon) — fnm / p7zip lookup
add_path_once "/opt/homebrew/bin"
add_path_once "/usr/local/bin"
export PATH

# Activate fnm so node/pnpm resolve to the project-pinned version.
if command -v fnm >/dev/null 2>&1; then
    eval "$(fnm env --use-on-cd --shell bash 2>/dev/null || true)"
    if [[ -f "$REPO_ROOT/.node-version" ]]; then
        ( cd "$REPO_ROOT" && fnm use --install-if-missing >/dev/null 2>&1 || true )
    fi
    if command -v node >/dev/null 2>&1; then
        add_path_once "$(dirname "$(command -v node)")"
        export PATH
    fi
fi

# Warn (don't fail) about missing project-local assets — setup.sh handles install.
MISSING=()
[[ -x "$LLAMA_SERVER_BIN" ]]      || MISSING+=('llama-server')
[[ -f "$LLAMA_MODEL" ]]           || MISSING+=('Qwen3 GGUF model')
[[ -x "$VOICEVOX_BIN" ]]          || MISSING+=('voicevox run binary')
if (( ${#MISSING[@]} > 0 )); then
    printf '  missing: %s — run scripts/setup.sh\n' "$(IFS=', '; echo "${MISSING[*]}")"
fi

printf 'desktop-ai-agent env activated\n'
printf '  REPO_ROOT   = %s\n' "$REPO_ROOT"
printf '  LLAMA_MODEL = %s\n' "$(basename "$LLAMA_MODEL")"
