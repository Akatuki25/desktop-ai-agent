# 環境構築 (Windows)

Windows 10/11 向け。**root を最大限汚さない** 方針で、自動化できる部分は `scripts/setup.ps1` 1 本にまとめてある。

## TL;DR

```powershell
# 1. 前提: Git と VS Build Tools を入れる (詳細は下の「前提」セクション)
# 2. clone してセットアップ実行
git clone git@github.com:Akatuki25/desktop-ai-agent.git
cd desktop-ai-agent
.\scripts\setup.ps1

# 3. .env にシークレットを書く
notepad .env

# 4. 起動
. .\scripts\activate.ps1
cd frontend
pnpm tauri dev
```

以上。初回は llama.cpp / モデル / Chromium / VOICEVOX のダウンロードで数 GB / 数十分かかる。2 回目以降の `setup.ps1` は既に入っているものを skip するので数秒で終わる。

---

## 前提 (手動、一度だけ)

`setup.ps1` は以下**だけは入れてくれない**。`setup.ps1` を走らせる前に用意する。

### 1. Git for Windows
```powershell
winget install --id Git.Git -e
```

### 2. Visual Studio Build Tools 2022 (C++ workload) ← **唯一 root を汚す**
Rust/Tauri のリンカ依存で、これだけは代替不可。
```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override `
  "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

### 3. WebView2 Runtime (Windows 10 のみ)
Windows 11 は標準搭載なのでスキップ。
```powershell
winget install --id Microsoft.EdgeWebView2Runtime -e
```

---

## `setup.ps1` が何をするか

`setup.ps1` は以下を順に実行する。全て冪等 (既に入っていれば skip)。

| ステップ | 配置先 | 汚染範囲 |
|---------|--------|---------|
| rustup (+ stable Rust toolchain) | `%USERPROFILE%\.rustup`, `.cargo` | per-user |
| fnm (Node version manager) | `%LOCALAPPDATA%\fnm` | per-user |
| uv (Python manager、Python本体含む) | `%USERPROFILE%\.local\bin` 他 | per-user |
| Node + pnpm (`fnm use` + `corepack enable`) | fnm 配下 | per-user |
| frontend deps (`pnpm install`) | `./frontend/node_modules/` | project |
| agent deps (`uv sync`) | `./.venv/` または `./agent/.venv/` | project |
| llama.cpp prebuilt | `./vendor/llama.cpp/` | project |
| Qwen3 8B GGUF モデル | `./models/` | project |
| Playwright Chromium (cache を repo に向ける) | `./vendor/playwright-browsers/` | project |
| VOICEVOX エンジン portable | `./vendor/voicevox/` | project |
| `.env` scaffold | `./.env` (`.env.example` から) | project |

**システム全体に残るのは VS Build Tools だけ**、それ以外は per-user か repo 内。repo を消せば project 列は全て消滅する。

### フラグ
```powershell
.\scripts\setup.ps1 -SkipToolchain   # rustup/fnm/uv は既に入っている場合
.\scripts\setup.ps1 -SkipModel       # 5GB の GGUF を後回しにする
.\scripts\setup.ps1 -SkipVoicevox    # 音声を使わない
```

### 7-Zip について
VOICEVOX の配布物は `.7z`。setup.ps1 は 7-Zip を見つけられないと voicevox 展開だけ warn で skip する。必要なら:
```powershell
winget install --id 7zip.7zip -e
.\scripts\setup.ps1           # 7z 検出後に再実行
```

---

## 起動

### 開発モード
```powershell
. .\scripts\activate.ps1      # 環境変数を Process scope でセット
cd frontend
pnpm tauri dev                # Tauri が agent daemon を spawn、daemon が llama-server を spawn
```
初回は Rust ビルドで数分。2 回目以降はインクリメンタル。

### daemon だけ (デバッグ用)
```powershell
. .\scripts\activate.ps1
cd agent
uv run python -m agent --port 0 --token dev
```

### llama-server だけ (LLM 疎通確認)
```powershell
. .\scripts\activate.ps1
& $env:LLAMA_SERVER_BIN -m $env:LLAMA_MODEL --jinja --port 8080 -c 8192
# 別シェルで
curl http://127.0.0.1:8080/v1/models
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
| `.env` の内容 | そのまま |

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

これらは **意図的に repo 外**。repo を消しても残る ↔ アンインストール時は別途削除が必要 (下記参照)。

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

残るのは VS Build Tools のみ。

---

## トラブルシュート

| 症状 | 原因 | 対処 |
|------|------|------|
| `setup.ps1` が `rustc not found` でループ | rustup インストール直後で PATH が未反映 | 新しい PowerShell を開いて `.\scripts\setup.ps1` を再実行 |
| `pnpm tauri dev` で MSVC リンクエラー | VS Build Tools 未導入 or C++ workload 欠落 | 前提 §2 をやり直す |
| モデル DL が途中で落ちる | HTTPS タイムアウト | `uv tool run --from huggingface_hub huggingface-cli download ...` (setup.ps1 内部でも使用) で resume が効く。再実行でよい |
| VOICEVOX 展開が skip される | 7-Zip 未導入 | `winget install 7zip.7zip -e` の後に再実行 |
| `. .\scripts\activate.ps1` が "スクリプトの実行が無効" | ExecutionPolicy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (user scope のみ変更) |
| `llama-server.exe` が落ちる | AVX2 非対応 CPU | llama.cpp を AVX 版に差し替え。`scripts/setup.ps1` の `$LLAMA_ZIP` を `llama-*-bin-win-avx-x64.zip` に変更 |
