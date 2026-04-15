# 環境構築 (Windows)

Windows 10/11 向け。**root を最大限汚さない** 方針で、自動化できる部分は `scripts/setup.ps1` 1 本にまとめてある。

このドキュメントは `main` ブランチでの実動作で検証済み。

## TL;DR

```powershell
# 1. 前提 3 つを済ませる (詳細は下の「前提」)
#    - Git for Windows
#    - Visual Studio Build Tools 2022 (C++ workload)
#    - Smart App Control が On の場合は Off にする  ← Windows 11 開発機では必須

# 2. clone
git clone git@github.com:Akatuki25/desktop-ai-agent.git
cd desktop-ai-agent

# 3. セットアップ (rustup/fnm/uv/llama.cpp/Qwen3.5 GGUF/VOICEVOX/.env まで自動)
.\scripts\setup.ps1

# 4. .env にシークレット (Deepgram 等) を書く
notepad .env

# 5. 動作確認 (全部グリーンになるはず — agent / frontend / tauri 8 ステップ)
.\scripts\verify.ps1

# 6. 起動 (Tauri が daemon を spawn → daemon が llama-server を spawn → 窓が立つ)
. .\scripts\activate.ps1
cd frontend
pnpm tauri dev
```

初回は **モデル ~5GB / VOICEVOX ~2GB / llama.cpp ~80MB / rustup ~300MB** のダウンロードで合計 15-30 分程度。再実行は冪等で、既存のものは全て skip。

`-SkipModel` / `-SkipVoicevox` / `-SkipToolchain` フラグを付ければ重い段だけ後回しにできるが、**既定はフルセットアップ** ("ゼロから動く" を担保するため)。

---

## 前提 (手動、一度だけ)

`setup.ps1` は以下 3 点を自前では入れない。preflight で検出できなければ**先に進まず hard-fail** するので "知らずに中途半端な状態" にはならない。

### 1. Git for Windows
```powershell
winget install --id Git.Git -e
```

### 2. Visual Studio Build Tools 2022 (C++ workload) ← **唯一 root を汚す**
Rust/Tauri のリンカ依存。これだけは代替なし。
```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --accept-source-agreements --accept-package-agreements --override `
  "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```
UAC プロンプトが出る。ダウンロード ~3GB、所要時間 10–25 分。

### 3. Smart App Control を Off にする (Windows 11 限定)
Windows 11 には **Smart App Control (SAC)** という reputation-based な実行ブロック機能があり、**Rust の build script が生成する未署名 .exe を問答無用でブロック** する (`OS error 4551`)。Defender 除外で迂回できない。

状態確認:
```powershell
Get-MpComputerStatus | Format-List SmartAppControlState
```
`On` と出たら Off にする必要がある。

**Off 手順:**
1. 設定 → プライバシーとセキュリティ → Windows セキュリティ  
2. アプリ & ブラウザーコントロール  
3. Smart App Control の設定 → **Off**

**重要:** SAC は一度 Off にすると **Windows をクリーンインストールしない限り再 On できない** という一方通行の仕様。本プロジェクトのような開発用途では Off にする以外の選択肢がない。他のセキュリティ (Defender / SmartScreen / UAC) はそのまま残る。

### 4. WebView2 Runtime (Windows 10 のみ)
Windows 11 は標準搭載。10 の場合のみ:
```powershell
winget install --id Microsoft.EdgeWebView2Runtime -e
```

---

## `setup.ps1` が何をするか

以下を順に、冪等に実行する。既に入っているものは自動で skip。preflight で欠けている prerequisite を発見した場合は該当の winget コマンドを表示して **hard-fail** する (silent な warning は残さない)。

| ステップ | バージョン / repo | 配置先 | 汚染範囲 |
|---------|------------------|--------|---------|
| ExecutionPolicy を `RemoteSigned` (`CurrentUser` scope) に設定 | — | HKCU | per-user |
| preflight: git / winget / VS Build Tools | — | — | 読むだけ |
| rustup + stable Rust toolchain (MSVC) | latest stable | `%USERPROFILE%\.rustup`, `.cargo` | per-user |
| fnm (Node version manager) | winget 最新 | winget package dir | per-user |
| uv (Python manager、Python 本体含む) | latest | `%USERPROFILE%\.local\bin` | per-user |
| Node + pnpm (`fnm use` + corepack 更新 + activate) | Node 22.11.0 / pnpm 9.15.0 | fnm 配下 | per-user |
| frontend deps (`pnpm install`) | — | `frontend/node_modules/` | project |
| agent deps (`uv sync`) | — | `agent/.venv/` | project |
| llama.cpp prebuilt | **`b8798` cpu-x64** (`--jinja` と `delta.reasoning_content` 対応の最低ライン b8200) | `vendor/llama.cpp/` | project |
| Qwen3.5 9B GGUF モデル | **`unsloth/Qwen3.5-9B-GGUF` / Qwen3.5-9B-Q4_K_M.gguf** (~5.4 GB) | `models/` | project |
| 7-Zip (VOICEVOX 解凍に必要、未導入なら winget で自動取得) | winget 最新 | `C:\Program Files\7-Zip\` | system (winget) |
| Playwright Chromium | (Phase 4 — agent に依存が入った時のみ) | `vendor/playwright-browsers/` | project |
| VOICEVOX engine portable | **`0.25.1` windows-cpu** (~2 GB) | `vendor/voicevox/` | project |
| `.env` を `.env.example` からコピー | — | `./.env` | project |

各段で実体検証 (`llama-server.exe --version` の build 番号、モデルファイルサイズ、`run.exe` の存在) を行い、想定外の状態を検出したら hard-fail する。最後に warning があれば **summary として再表示** され exit code 2 で終わる。

### フラグ
```powershell
.\scripts\setup.ps1 -SkipToolchain   # rustup/fnm/uv を飛ばす (per-user 既導入時)
.\scripts\setup.ps1 -SkipModel       # Qwen3.5 GGUF DL を飛ばす (5GB節約)
.\scripts\setup.ps1 -SkipVoicevox    # VOICEVOX engine DL を飛ばす (2GB節約)
.\scripts\setup.ps1 -NoExecPolicy    # ExecutionPolicy を触らない
```
既定はフルセットアップ (no-skip)。"ゼロから動く" を担保するため。

### llama.cpp バージョンの強制
`b8200` 未満は `--jinja` フラグも `delta.reasoning_content` フィールドもサポートしておらず、Qwen3 系の thinking 出力を完全に取りこぼします。`setup.ps1` は cached `llama-server.exe` の build 番号を `cmd /c llama-server.exe --version` で読み、b8200 未満なら自動で削除して b8798 を再取得します。

### モデル DL について
旧 `huggingface-cli download` は deprecated。新しい `hf download` を `uv tool run --from huggingface_hub hf download` 経由で叩き、`--local-dir` には repo 直下の絶対パス (`models/`) を渡します (CWD 相対だとどこに落ちるか分からなくなるため)。ダウンロード後に 1GB 未満なら破損とみなして fail します。

### VOICEVOX
0.25 以降は `voicevox_engine-windows-cpu-<ver>.7z.001` という単一パート 7z 形式に変わっています。アーカイブ内のディレクトリ名はリリースごとに変わる (0.25.1 では `windows-cpu/`) ので、`setup.ps1` は `run.exe` を含むディレクトリを再帰で探して `vendor/voicevox/` にリネームします。7-Zip が無ければ winget で自動取得します。

### corepack の既知問題について
Node 22.11.0 同梱の corepack には `pnpm@latest` 取得時の署名キー検証バグがあり、そのまま `corepack enable` すると失敗する。`setup.ps1` は `npm install -g corepack@latest` で先に更新してから `corepack prepare pnpm@9.15.0 --activate` するため、この罠に当たらない。

---

## 動作確認 (`scripts/verify.ps1`)

setup 完了後に一発で 8 項目チェックするスクリプトを同梱している:

```powershell
.\scripts\verify.ps1
```

内訳:
1. `agent`: `uv sync --frozen`
2. `agent`: `ruff check .`
3. `agent`: `mypy --strict`
4. `agent`: `pytest` (memory / orchestrator / WS server / **LlamaServerBackend HTTP モック**)
5. `frontend`: `pnpm install --frozen-lockfile`
6. `frontend`: `pnpm typecheck`
7. `frontend`: `pnpm test` (vitest — store / RPC client / Bubble / Character / ChatPanel / App)
8. `tauri`: `cargo check --locked`

全部グリーンになれば Phase 0 の開発を始められる状態。

### 実 LLM を使う統合テスト (オプション)

`pytest` 既定セットには `LlamaServerBackend` の **HTTP モックテスト** が含まれており、`delta.content` と `delta.reasoning_content` 両方の経路を検証する (これは llama.cpp 8000 系で発生する thinking 取りこぼしバグの回帰防止)。

実機の llama-server に対して喋らせて確認したい場合は別ファイル `tests/test_llama_server_live.py` があり、以下のように叩く:

```powershell
. .\scripts\activate.ps1
# 別シェルで llama-server を起動
& $env:LLAMA_SERVER_BIN -m $env:LLAMA_MODEL --port 8765 --jinja -c 4096
# 元シェルで:
$env:LLAMA_SERVER_URL = "http://127.0.0.1:8765"
$env:RUN_LLM_INTEGRATION = "1"
cd agent
uv run pytest tests/test_llama_server_live.py -v
```

`RUN_LLM_INTEGRATION` 未設定だとこのテストは skip され、CI / `verify.ps1` には影響しない。

---

## 起動

### 開発モード
```powershell
. .\scripts\activate.ps1      # 環境変数を Process scope でセット
cd frontend
pnpm tauri dev                # Tauri 窓が立つ
```
初回 Rust コンパイルで数分。2 回目以降はインクリメンタル。

### 個別実行 (デバッグ用)

agent daemon 単体:
```powershell
. .\scripts\activate.ps1
cd agent
uv run python -m agent --port 0 --token dev
```

llama-server 単体 (LLM 疎通確認):
```powershell
. .\scripts\activate.ps1
& $env:LLAMA_SERVER_BIN -m $env:LLAMA_MODEL --jinja --port 8080 -c 8192
# 別シェルで
curl http://127.0.0.1:8080/v1/models
```

vitest を watch で:
```powershell
cd frontend
pnpm test:watch
```

pytest を watch で:
```powershell
cd agent
uv run pytest --looponfail  # or just re-run on save
```

---

## `activate.ps1` の効果

`. .\scripts\activate.ps1` (先頭のドット必須) を実行すると**現シェルにのみ**以下の環境変数がセットされる:

| 変数 | 値 |
|------|----|
| `REPO_ROOT` | repo の絶対パス |
| `PLAYWRIGHT_BROWSERS_PATH` | `./vendor/playwright-browsers` |
| `LLAMA_SERVER_BIN` | `./vendor/llama.cpp/llama-server.exe` |
| `LLAMA_MODEL` | `./models/Qwen3.5-9B-Q4_K_M.gguf` |
| `VOICEVOX_BIN` | `./vendor/voicevox/run.exe` |
| `AGENT_DATA_DIR` | `%APPDATA%/desktop-ai-agent` |
| `.env` の内容 | そのまま Process scope に展開 |

シェルを閉じれば全部消える (永続化しない)。

---

## `.env`

```powershell
copy .env.example .env
notepad .env
```
最低限 `DEEPGRAM_API_KEY` を埋める。それ以外は任意。

---

## 実行時データ (repo の外に置かれるもの)

daemon が起動時に作る:

- `%APPDATA%/desktop-ai-agent/db.sqlite` — メモリ DB
- `%APPDATA%/desktop-ai-agent/logs/` — ローテートログ
- `%APPDATA%/desktop-ai-agent/browser-profile/` — agent 専用 Chromium プロファイル
- `%APPDATA%/desktop-ai-agent/downloads/` — Playwright ダウンロード sandbox

これらは **意図的に repo 外**。repo 削除では消えない。完全アンインストール時は下記を参照。

---

## 完全アンインストール

```powershell
# 1. project-local は repo 削除で消滅
Remove-Item -Recurse -Force C:\path\to\desktop-ai-agent

# 2. 実行時データ
Remove-Item -Recurse -Force $env:APPDATA\desktop-ai-agent

# 3. per-user ツール (他で使っていなければ)
rustup self uninstall
winget uninstall Schniz.fnm
Remove-Item $env:USERPROFILE\.local\bin\uv.exe
```

残るのは VS Build Tools と (off にした) Smart App Control のみ。SAC は Windows クリーンインストール以外で元に戻せない。

---

## トラブルシュート

| 症状 | 原因 | 対処 |
|------|------|------|
| `setup.ps1` が VS Build Tools 未検出で exit | 前提 §2 が未了 | 前提 §2 の winget コマンドを elevated シェルで実行 |
| `cargo check` / `pnpm tauri dev` が `OS error 4551` | Smart App Control On | 前提 §3 の手順で Off |
| `cargo check` が `link: extra operand` | Git Bash の `/usr/bin/link` (coreutils) が MSVC の `link.exe` を shadow | PowerShell または cmd から実行 (bash は NG) |
| `setup.ps1` が `rustc not found` でループ | rustup 直後で現シェルに PATH 未反映 | 新しい PowerShell で `.\scripts\setup.ps1 -SkipToolchain` |
| `corepack enable` が署名エラー | Node 22.11 同梱 corepack バグ | `setup.ps1` が自動対応済み (内部で `npm install -g corepack@latest` → `corepack prepare pnpm@9.15.0 --activate`) |
| `hf download` が `Repository not found` | repo 名のタイプミス、もしくは古いキャッシュ | `setup.ps1` は `unsloth/Qwen3.5-9B-GGUF` を使う。手で `hf download` する場合は同 repo を指定 |
| llama.cpp / モデル DL 中断 | HTTPS タイムアウト | `setup.ps1` は `hf download` の resume 機構を使うので再実行で続きから |
| `llama-server.exe --version` が `b4000` のような古い番号を返す | 過去にハードコードしていた古い release が残存 | `setup.ps1` を再実行すると b8200 未満は自動削除して b8798 に置換 |
| llama-server に POST すると `chat_template_kwargs` が無視される / thinking が消える | b8200 未満を使っている | 上記と同じ。`b8798` 以降必須 |
| `. .\scripts\activate.ps1` が "スクリプトの実行が無効" | ExecutionPolicy | `setup.ps1` が自動で設定する。手動なら `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| VOICEVOX 解凍が "no such directory" で fail | 0.25 で内部ディレクトリ名が変わった | `setup.ps1` は `run.exe` を含むディレクトリを再帰探索するので最新の release を取得すれば動く |
| `llama-server.exe` が起動直後に落ちる | AVX2 非対応 CPU | `scripts/setup.ps1` 内の `$LLAMA_ZIP` を `llama-bin-win-cpu-x64.zip` (AVX 不要版) に変更 |

---

## 検証境界 (このドキュメントが本当に保証している範囲)

`main` ブランチで以下を **実走** で確認済み:

- `setup.ps1` を no-skip で完走させ、以下の DL/install/extract 経路がそれぞれ動くこと
  - llama.cpp b8798 cpu-x64 zip → `vendor/llama.cpp/llama-server.exe` (build 番号検出 8798)
  - `unsloth/Qwen3.5-9B-GGUF / Qwen3.5-9B-Q4_K_M.gguf` を `hf download` で `models/` 直下に 5417 MB
  - 7-Zip 未導入時は winget で自動取得
  - VOICEVOX `0.25.1` windows-cpu `7z.001` を取得 → 7z 展開 → `run.exe` を含むディレクトリを再帰検出 → `vendor/voicevox/`
  - `.env.example` → `.env`
  - `pnpm install --frozen-lockfile`、`uv sync` (既存 venv 再利用)
- rustup の install 経路 (per-user MSVC stable) は本セッション初期で実走確認
- fnm winget install + `fnm use` + corepack 9.15.0 activate 経路は同じく初期で実走確認
- `verify.ps1` の 8 ステップ全緑
- `pnpm tauri dev` で実際に Tauri 窓が立ち上がり、`daemon_info` invoke で port/token 取得 → WS 接続 → `session.send_text` → `LlamaServerBackend` → `delta.reasoning_content` 含む stream → `agent.say` deltas → bubble 表示までを実走 (Qwen3.5-9B が `Hello! How can I help you today?` を返した)

**未実走 (= 本セッションでは検証できなかった)**:
- `uv` の install 経路 (元から入っていたため、`setup.ps1` の uv 取得分岐に入らなかった)。コードは `astral.sh/uv/install.ps1` を `irm | iex` で叩く一行で、astral 公式の標準パスです
- VS Build Tools の自動 install (前提として要求し、不在なら hard-fail する仕様)

これら以外の設定 (Smart App Control off / `.env` 編集 / pnpm tauri dev の実起動) は手動操作前提です。

---

## 現状 (`main`) で何ができるか

`main` ブランチ時点で以下が全部グリーンで動く (この手順書通りにセットアップすれば再現する):

```
agent:
  ruff check        -> All checks passed!
  mypy --strict     -> Success: no issues found in 23 source files
  pytest            -> 28 passed         (memory / orchestrator / WS / LlamaServerBackend HTTP)
  pytest --live     -> 1 passed          (real Qwen3.5-9B reply via running llama-server)

frontend:
  pnpm typecheck    -> ok
  pnpm test         -> 22 passed         (store / RPC client / Bubble / Character / ChatPanel / App)

tauri:
  cargo check       -> Finished `dev` profile
```

**Phase 0 の実装** (実走確認済み):
1. `pnpm tauri dev` で透過 always-on-top の窓が立ち上がる
2. Tauri が `agent/.venv/Scripts/python.exe -m agent --port 0 --token <uuid>` で daemon を spawn
3. daemon は `LLAMA_SERVER_URL` (= `activate.ps1` 経由 or 既起動の llama-server) を検出して `LlamaServerBackend` で接続。なければ自分で `LLAMA_SERVER_BIN` から llama-server を spawn
4. daemon が `{"event": "ready", "port": N}` を stdout に出し、Tauri が parse して `daemon_info` Tauri command 経由で frontend に渡す
5. frontend は `invoke('daemon_info')` で port/token を取得、`ws://127.0.0.1:N/ws` に subprotocol `bearer.<token>` で接続
6. テキスト送信 → `session.send_text` → orchestrator (hot context: core_memory + behavior_config + 直近 session summaries) → `LlamaServerBackend.chat_stream` → Qwen3.5-9B → `delta.content` / `delta.reasoning_content` を `agent.say` deltas として stream → frontend bubble (本文/thinking 別レイヤ) と character sprite (emotion 反映)
7. 終了時に `agent.say_end`、メッセージは sqlite の `messages` テーブルに永続化

実 LLM 統合テストでは `Reply with the single word: pong` → `pong` が返ることを確認している (`tests/test_llama_server_live.py`)。
