#!/usr/bin/env bash
# scripts/verify.sh
# Run every static check + test suite in the repo on macOS / Linux.
# Mirrors scripts/verify.ps1.

set -uo pipefail

SKIP_TAURI=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-tauri) SKIP_TAURI=1 ;;
        -h|--help) sed -n '1,12p' "$0"; exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 1 ;;
    esac
    shift
done

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

FAILURES=()

run_step() {
    local name="$1" cwd="$2"; shift 2
    printf '\n==> %s\n' "$name"
    if ( cd "$cwd" && "$@" ); then
        printf '  [ok] %s\n' "$name"
    else
        printf '  [FAIL] %s\n' "$name"
        FAILURES+=("$name")
    fi
}

# Surface per-user tool dirs even if the caller forgot to source activate.sh.
add_path_once() {
    local p="$1"
    [[ -d "$p" ]] || return 0
    case ":$PATH:" in *":$p:"*) ;; *) PATH="$p:$PATH" ;; esac
}
add_path_once "$HOME/.cargo/bin"
add_path_once "$HOME/.local/bin"
add_path_once "$HOME/.local/share/fnm"
add_path_once "/opt/homebrew/bin"
add_path_once "/usr/local/bin"
export PATH

# Activate fnm so node/pnpm become usable in this session.
if command -v fnm >/dev/null 2>&1; then
    eval "$(fnm env --use-on-cd --shell bash 2>/dev/null || true)"
    if [[ -f "$REPO/.node-version" ]]; then
        ( cd "$REPO" && fnm use --install-if-missing >/dev/null 2>&1 || true )
    fi
    if command -v node >/dev/null 2>&1; then
        add_path_once "$(dirname "$(command -v node)")"
        export PATH
    fi
fi

run_step 'agent: uv sync --frozen' agent     uv sync --frozen
run_step 'agent: ruff check .'     agent     uv run ruff check .
run_step 'agent: mypy --strict'    agent     uv run mypy
run_step 'agent: pytest'           agent     uv run pytest -q

run_step 'frontend: pnpm install --frozen-lockfile' frontend pnpm install --frozen-lockfile
run_step 'frontend: pnpm typecheck'                 frontend pnpm typecheck
run_step 'frontend: pnpm test'                      frontend pnpm test

if (( SKIP_TAURI == 0 )); then
    run_step 'tauri: cargo check --locked' frontend/src-tauri cargo check --locked
fi

printf '\n================ verify summary ================\n'
if (( ${#FAILURES[@]} == 0 )); then
    printf '  all green.\n'
    exit 0
else
    printf '  %d failing step(s):\n' "${#FAILURES[@]}"
    for f in "${FAILURES[@]}"; do printf '    - %s\n' "$f"; done
    exit 1
fi
