# 環境構築 (macOS)

macOS 13+ (Apple Silicon / Intel いずれも) 向け。**root を最大限汚さない**
方針で、自動化できる部分は `scripts/setup.sh` 1 本にまとめてある。

Windows 用は [`docs/setup.md`](./setup.md) を参照。

## TL;DR

```bash
# 1. 前提を済ませる (詳細は下の「前提」)
#    - Xcode Command Line Tools  (`xcode-select --install`)

# 2. clone
git clone git@github.com:Akatuki25/desktop-ai-agent.git
cd desktop-ai-agent

# 3. セットアップ (rustup/fnm/uv/llama.cpp/Qwen3.5 GGUF/VOICEVOX/.env まで自動)
./scripts/setup.sh

# 4. .env にシークレット (Deepgram 等) を書く
$EDITOR .env

# 5. 動作確認 (全部グリーンになるはず — agent / frontend / tauri 8 ステップ)
./scripts/verify.sh

# 6. 起動 (Tauri が daemon を spawn → daemon が llama-server を spawn → 窓が立つ)
source ./scripts/activate.sh
cd frontend
pnpm tauri dev
```

初回は **モデル ~5GB / VOICEVOX ~2GB / llama.cpp ~80MB / rustup ~300MB**
のダウンロードで合計 15-30 分程度。再実行は冪等で、既存のものは全て skip。

`--skip-model` / `--skip-voicevox` / `--skip-toolchain` フラグを付ければ
重い段だけ後回しにできるが、**既定はフルセットアップ** ("ゼロから動く" を担保するため)。

---

## 前提 (手動、一度だけ)

### Xcode Command Line Tools
Rust / Tauri / native deps のビルドに必要 (clang + linker)。
```bash
xcode-select --install
```
GUI のインストーラが出る。完了後に `setup.sh` を再実行。

これが入っていれば `git` も同梱されるので、明示的なインストールは不要。

### Homebrew (任意、推奨)
`brew` があれば fnm / p7zip を brew 経由で取れる。無ければ `setup.sh` は
`fnm` を curl 公式インストーラで入れ、p7zip は VOICEVOX セクションで案内のみ
(`brew install p7zip`)。

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

---

## `setup.sh` が何をするか

以下を順に、冪等に実行する。既に入っているものは自動で skip。preflight で
欠けている prerequisite を検出した場合は該当のコマンドを表示して **hard-fail**
する (silent な warning は残さない)。

| ステップ | バージョン / repo | 配置先 | 汚染範囲 |
|---------|------------------|--------|---------|
| preflight: git / Xcode CLT / curl | — | — | 読むだけ |
| rustup + stable Rust toolchain | latest stable | `~/.cargo`, `~/.rustup` | per-user |
| fnm (Node version manager) | brew or curl 最新 | `~/.local/share/fnm` or brew | per-user |
| uv (Python manager) | latest | `~/.local/bin` | per-user |
| Node + pnpm (`fnm use` + corepack 更新 + activate) | Node 22.11.0 / pnpm 9.15.0 | fnm 配下 | per-user |
| frontend deps (`pnpm install`) | — | `frontend/node_modules/` | project |
| agent deps (`uv sync`) | — | `agent/.venv/` | project |
| llama.cpp prebuilt | **`b8798` macos-arm64 or macos-x64** | `vendor/llama.cpp/` | project |
| Qwen3.5 9B GGUF モデル | **`unsloth/Qwen3.5-9B-GGUF` / Qwen3.5-9B-Q4_K_M.gguf** (~5.4 GB) | `models/` | project |
| 7-Zip (VOICEVOX 解凍に必要、未導入かつ brew があれば自動取得) | brew 最新 | brew prefix | per-user (brew) |
| VOICEVOX engine portable | **`0.25.1` macos-(arm64\|x64)** (~2 GB) | `vendor/voicevox/` | project |
| `.env` を `.env.example` からコピー | — | `./.env` | project |

各段で実体検証 (`llama-server --version` の build 番号、モデルファイルサイズ、
voicevox `run` の存在) を行い、想定外の状態を検出したら hard-fail する。
最後に warning があれば **summary として再表示** され exit code 2 で終わる。

### Gatekeeper (quarantine 属性)

macOS は curl でダウンロードした実行ファイルに `com.apple.quarantine` 属性を
付け、初回起動を `killed: 9` で止めることがある。`setup.sh` は llama.cpp
と VOICEVOX の展開後に `xattr -dr com.apple.quarantine` を当てるので、
追加操作は不要。

### フラグ
```bash
./scripts/setup.sh --skip-toolchain   # rustup/fnm/uv を飛ばす (per-user 既導入時)
./scripts/setup.sh --skip-model       # Qwen3.5 GGUF DL を飛ばす (5GB節約)
./scripts/setup.sh --skip-voicevox    # VOICEVOX engine DL を飛ばす (2GB節約)
./scripts/setup.sh --model 4B         # 9B (~5.4GB) ではなく 4B (~2.4GB) を使う
```

### モデルサイズの選択
低スペック機 (RAM 不足) で 9B が遅すぎる場合は `--model 4B` で軽量版に切り替える。
詳細は Windows 版 (`docs/setup.md`) の同名セクションと同じ。

---

## 動作確認 (`scripts/verify.sh`)

```bash
./scripts/verify.sh
```

内訳は Windows 版と同じ 8 項目 (agent ruff/mypy/pytest, frontend
typecheck/test, tauri cargo check)。

---

## 起動

### 開発モード
```bash
source ./scripts/activate.sh    # 環境変数を現シェルにセット
cd frontend
pnpm tauri dev                  # Tauri 窓が立つ
```
初回 Rust コンパイルで数分。2 回目以降はインクリメンタル。

### 個別実行 (デバッグ用)

agent daemon 単体:
```bash
source ./scripts/activate.sh
cd agent
uv run python -m agent --port 0 --token dev
```

llama-server 単体:
```bash
source ./scripts/activate.sh
"$LLAMA_SERVER_BIN" -m "$LLAMA_MODEL" --jinja --port 8080 -c 8192
# 別シェルで
curl http://127.0.0.1:8080/v1/models
```

---

## `activate.sh` の効果

`source ./scripts/activate.sh` を実行すると**現シェルにのみ**以下の
環境変数がセットされる:

| 変数 | 値 |
|------|----|
| `REPO_ROOT` | repo の絶対パス |
| `PLAYWRIGHT_BROWSERS_PATH` | `./vendor/playwright-browsers` |
| `LLAMA_SERVER_BIN` | `./vendor/llama.cpp/llama-server` (no `.exe`) |
| `LLAMA_MODEL` | `./models/Qwen3.5-9B-Q4_K_M.gguf` (or 4B / explicit override) |
| `VOICEVOX_BIN` | `./vendor/voicevox/run` (or `run.command`) |
| `AGENT_DATA_DIR` | `~/Library/Application Support/desktop-ai-agent` |
| `.env` の内容 | そのまま現シェルに展開 |

シェルを閉じれば全部消える (永続化しない)。

---

## 実行時データ (repo の外に置かれるもの)

daemon が起動時に作る:

- `~/Library/Application Support/desktop-ai-agent/db.sqlite` — メモリ DB
- `~/Library/Application Support/desktop-ai-agent/logs/` — ローテートログ
- `~/Library/Application Support/desktop-ai-agent/browser-profile/` — agent 専用 Chromium プロファイル
- `~/Library/Application Support/desktop-ai-agent/downloads/` — Playwright ダウンロード sandbox

これらは **意図的に repo 外**。repo 削除では消えない。完全アンインストール時は:

```bash
rm -rf ~/Library/Application\ Support/desktop-ai-agent
rustup self uninstall      # 他で Rust を使っていなければ
brew uninstall fnm         # 他で fnm を使っていなければ
rm -f ~/.local/bin/uv      # 他で uv を使っていなければ
```

---

## トラブルシュート

| 症状 | 原因 | 対処 |
|------|------|------|
| `setup.sh` が `xcode-select -p` で fail | Xcode CLT 未導入 | `xcode-select --install` 後に再実行 |
| `llama-server` が起動直後に `killed: 9` | Gatekeeper quarantine | `xattr -dr com.apple.quarantine vendor/llama.cpp` |
| `cargo check` が AppleClang 関連で fail | Xcode CLT が壊れている | `sudo rm -rf $(xcode-select -p) && xcode-select --install` |
| VOICEVOX 解凍が `7z: command not found` | p7zip 未導入 | `brew install p7zip` 後に `setup.sh` を再実行 |
| `pnpm tauri dev` で window が出るが daemon が closed | `agent/.venv/bin/python` 不在 | `cd agent && uv sync` |
| llama-server が AVX2 関連で落ちる | 古い Intel Mac | `--skip-model` 経由で別途軽量バックエンドを検討 |

---

## 検証境界

このドキュメント自体は **macOS 14 (Apple Silicon)** での実走を念頭に書かれている。
未実走の検証は Windows 版と同じ枠組みで、本セッション開始時点では:

- **未実走** : 本ブランチでの `./scripts/setup.sh` フル走、`pnpm tauri dev` の Tauri 窓表示
- **既走** : 既存 Python / Tauri 実装、ユニットテスト

実機で検証した結果は別途 PR / 実装記録に追記すること。
