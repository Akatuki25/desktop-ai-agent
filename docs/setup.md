# 環境構築 (Windows)

Windows 10/11 向け。**root を最大限汚さない** 方針で、自動化できる部分は `scripts/setup.ps1` 1 本にまとめてある。

このドキュメントは `main` ブランチでの実動作で検証済み。

## TL;DR

```powershell
# 1. 前提 3 つを済ませる (詳細は下の「前提」)
#    - Git for Windows
#    - Visual Studio Build Tools 2022 (C++ workload)
#    - Smart App Control が On の場合は Off にする  ← 開発機では必須

# 2. clone
git clone git@github.com:Akatuki25/desktop-ai-agent.git
cd desktop-ai-agent

# 3. セットアップ (rustup/fnm/uv/llama.cpp/.env まで自動)
.\scripts\setup.ps1

# 4. .env にシークレットを書く
notepad .env

# 5. 動作確認 (全部グリーンになるはず)
.\scripts\verify.ps1

# 6. 起動
. .\scripts\activate.ps1
cd frontend
pnpm tauri dev
```

初回は llama.cpp 展開と rustup インストールで数分。モデル (5GB) と VOICEVOX は既定で **skip** される — 必要になった時に `.\scripts\setup.ps1` を再実行すれば取得される。

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

| ステップ | 配置先 | 汚染範囲 |
|---------|--------|---------|
| ExecutionPolicy を `RemoteSigned` (`CurrentUser` scope) に設定 | HKCU | per-user |
| preflight: git / winget / VS Build Tools | — | 読むだけ |
| rustup + stable Rust toolchain (MSVC) | `%USERPROFILE%\.rustup`, `.cargo` | per-user |
| fnm (Node version manager) | winget 経由 | per-user |
| uv (Python manager、Python本体含む) | `%USERPROFILE%\.local\bin` | per-user |
| Node + pnpm (`fnm use` + `corepack enable`) | fnm 配下 | per-user |
| frontend deps (`pnpm install`) | `frontend/node_modules/` | project |
| agent deps (`uv sync`) | `agent/.venv/` | project |
| llama.cpp prebuilt (`b4000` AVX2) | `vendor/llama.cpp/` | project |
| Qwen3 8B GGUF モデル (既定 skip) | `models/` | project |
| Playwright Chromium (agent scaffold 後のみ) | `vendor/playwright-browsers/` | project |
| VOICEVOX engine portable (既定 skip) | `vendor/voicevox/` | project |
| `.env` を `.env.example` からコピー | `./.env` | project |

最後に warning があれば **summary として再表示** され、warning がある場合は exit code 2 で終了する。

### フラグ
```powershell
.\scripts\setup.ps1 -SkipToolchain   # rustup/fnm/uv を飛ばす
.\scripts\setup.ps1 -SkipModel       # Qwen3 GGUF (5GB) を飛ばす (既定)
.\scripts\setup.ps1 -SkipVoicevox    # VOICEVOX engine を飛ばす (既定)
.\scripts\setup.ps1 -NoExecPolicy    # ExecutionPolicy を触らない
```
既定でモデルと VOICEVOX は skip される構成にしてある (Phase 0 の開発では不要、必要になった時点で取得)。

### corepack の既知問題について
Node 22.11.0 同梱の corepack には `pnpm@latest` 取得時の署名キー検証バグがあり、そのまま `corepack enable` すると失敗する。`setup.ps1` は `npm install -g corepack@latest` で先に更新してから `corepack prepare pnpm@9.15.0 --activate` するため、この罠に当たらない。

---

## 動作確認 (`scripts/verify.ps1`)

setup 完了後に一発で 7 項目チェックするスクリプトを同梱している:

```powershell
.\scripts\verify.ps1
```

内訳:
1. `agent`: `uv sync --frozen`
2. `agent`: `ruff check .`
3. `agent`: `mypy --strict`
4. `agent`: `pytest`
5. `frontend`: `pnpm install --frozen-lockfile`
6. `frontend`: `pnpm typecheck`
7. `frontend`: `pnpm test` (vitest)
8. `tauri`: `cargo check --locked`

全部グリーンになれば Phase 0 の開発を始められる状態。

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
| `LLAMA_MODEL` | `./models/Qwen3-8B-Instruct-Q4_K_M.gguf` |
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
| `cargo check` が `link: extra operand` | Git Bash の `/usr/bin/link` が shadow | PowerShell または cmd から実行 (bash は NG) |
| `setup.ps1` が `rustc not found` でループ | rustup 直後で現シェルに PATH 未反映 | 新しい PowerShell で `.\scripts\setup.ps1 -SkipToolchain` |
| `corepack enable` が署名エラー | Node 22.11 同梱 corepack バグ | `npm install -g corepack@latest` してから再実行 (setup.ps1 は自動対応済み) |
| モデル DL 中断 | HTTPS タイムアウト | `setup.ps1` は `huggingface-cli download` を使うので再実行で resume |
| `. .\scripts\activate.ps1` が "スクリプトの実行が無効" | ExecutionPolicy | `setup.ps1` が自動で設定する。手動なら `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| VOICEVOX 展開が skip される | 7-Zip 未導入 | `setup.ps1` は `winget install 7zip.7zip` を自動で試みる。それでも失敗したら手動で 7-Zip を入れて再実行 |
| `llama-server.exe` が起動直後に落ちる | AVX2 非対応 CPU | `scripts/setup.ps1` 内の `$LLAMA_ZIP` を `llama-*-bin-win-avx-x64.zip` に変更 |

---

## 現状 (`main`) で何ができるか

`main` ブランチ時点で以下が全部グリーンで動く (この手順書通りにセットアップすれば再現する):

```
agent:
  ruff check        -> All checks passed!
  mypy --strict     -> Success: no issues found in 6 source files
  pytest            -> 5 passed

frontend:
  pnpm typecheck    -> ok
  pnpm test         -> 6 passed

tauri:
  cargo check       -> Finished `dev` profile
```

**Phase 0 の実装**: agent が `/ws` で echo daemon として立ち上がり、frontend の React App が daemon に接続すると text → `agent.say` の echo が帰ってくる。Tauri から daemon を spawn して token/port を橋渡しする配線は Phase 0b で実装予定。
