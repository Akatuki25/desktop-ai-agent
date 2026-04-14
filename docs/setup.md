# 環境構築 (Windows)

Windows 10/11 を対象とした開発環境のセットアップ手順。**root (システム全体) を極力汚さない** ことを原則とする。

## 原則
- 管理者権限が必須なのは **Visual Studio Build Tools** のみ (Rust のリンカ依存、回避不可)
- それ以外は全て **per-user (`%USERPROFILE%` 配下)** または **プロジェクトローカル (`repo/` 配下)** に閉じ込める
- PATH 改変はユーザー環境変数のみ、システム PATH は触らない
- モデル・ブラウザ・外部バイナリは全て `vendor/` と `models/` にダウンロードし、repo を消せば痕跡が残らない状態を目指す
- API キー等の秘密は `.env` に置き、`.env.example` をコミット

## 全体像

| 層 | 配置 | 汚染範囲 |
|----|------|---------|
| Visual Studio Build Tools | `C:\Program Files\...` | **system** (不可避) |
| rustup / cargo | `%USERPROFILE%\.rustup`, `.cargo` | user |
| fnm (Node manager) | `%USERPROFILE%\AppData\Local\fnm` | user |
| uv (Python manager) | `%USERPROFILE%\.local\bin` | user |
| Python venv | `./.venv/` | project |
| Node modules | `./frontend/node_modules/` | project |
| llama.cpp 実行バイナリ | `./vendor/llama.cpp/` | project |
| Qwen3 GGUF モデル | `./models/` | project |
| Playwright Chromium | `./vendor/playwright-browsers/` | project |
| VOICEVOX エンジン | `./vendor/voicevox/` | project |
| DB / logs / browser profile | `%APPDATA%/desktop-ai-agent/` | user (実行時) |

---

## 1. 前提 (一度だけ、手動)

### 1.1 Git for Windows
[git-scm.com](https://git-scm.com/download/win) からインストーラー。既に入っていればスキップ。

### 1.2 Visual Studio Build Tools 2022
Tauri/Rust が MSVC リンカを要求するため必須。

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools -e `
  --override "--wait --passive --add Microsoft.VisualCppBuildTools --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

または手動で installer を落とし、**"Desktop development with C++"** ワークロードを選択。

**ここだけ root を汚す。** 他に代替は無い。

### 1.3 WebView2 Runtime
Windows 11 は標準搭載。10 の場合のみ:
```powershell
winget install --id Microsoft.EdgeWebView2Runtime -e
```

---

## 2. per-user ツール (管理者不要)

以下は全て `%USERPROFILE%` 配下にインストールされ、root を汚さない。

### 2.1 rustup (Rust toolchain)
```powershell
# 公式 installer を user scope で実行
Invoke-WebRequest https://win.rustup.rs/x86_64 -OutFile $env:TEMP\rustup-init.exe
& $env:TEMP\rustup-init.exe -y --default-toolchain stable --profile minimal
```
インストール先: `%USERPROFILE%\.rustup`, `%USERPROFILE%\.cargo`。PATH はユーザー環境変数にのみ追加される。

### 2.2 fnm (Node.js version manager)
```powershell
winget install Schniz.fnm -e
# 現シェルで有効化 + 自動 activation を profile に追加
fnm env --use-on-cd | Out-String | Invoke-Expression
Add-Content $PROFILE 'fnm env --use-on-cd | Out-String | Invoke-Expression'
```
`fnm` は `%LOCALAPPDATA%\fnm` に入り、Node 自体も per-user。

### 2.3 uv (Python package & project manager)
```powershell
# 公式 standalone installer (user scope、root 変更なし)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
インストール先: `%USERPROFILE%\.local\bin\uv.exe`。uv は Python 本体も自前で管理するので、システム Python を入れる必要はない。

---

## 3. リポジトリ初期化

```powershell
git clone git@github.com:Akatuki25/desktop-ai-agent.git
cd desktop-ai-agent
```

### 3.1 Node バージョン固定
```powershell
# .node-version を読んで必要な Node を fnm が自動取得
fnm use --install-if-missing
corepack enable        # pnpm を有効化 (Node 同梱機能)
```
`corepack enable` は Node インストール先にのみ影響し、system には触らない。

### 3.2 frontend 依存
```powershell
cd frontend
pnpm install
cd ..
```

### 3.3 Python 環境 (agent)
```powershell
cd agent
uv sync                # .venv を作って pyproject.toml から依存解決
cd ..
```
Python 本体が無ければ uv が `pyproject.toml` の `requires-python` を見て自動で落とし、`%USERPROFILE%\.local\share\uv\python` 配下に配置する。

---

## 4. プロジェクトローカルのバイナリ/モデル取得

全て repo 配下に閉じ込める。初回のみ数 GB ダウンロードが発生。

### 4.1 llama.cpp (prebuilt)
```powershell
# CUDA 版 or CPU 版を選ぶ (下は CPU 版例、GPU なら cudart を足す)
$ver = "b4000"   # scripts/versions.ps1 で固定管理
$url = "https://github.com/ggml-org/llama.cpp/releases/download/$ver/llama-$ver-bin-win-avx2-x64.zip"
New-Item -ItemType Directory -Force vendor\llama.cpp | Out-Null
Invoke-WebRequest $url -OutFile vendor\llama.cpp.zip
Expand-Archive vendor\llama.cpp.zip -DestinationPath vendor\llama.cpp -Force
Remove-Item vendor\llama.cpp.zip
```
`vendor\llama.cpp\llama-server.exe` が使えるようになる。アンインストールは `vendor\llama.cpp\` を消すだけ。

### 4.2 Qwen3 8B GGUF モデル
```powershell
New-Item -ItemType Directory -Force models | Out-Null
# 量子化は Q4_K_M が速度/品質バランス良
$model = "Qwen3-8B-Instruct-Q4_K_M.gguf"
Invoke-WebRequest "https://huggingface.co/Qwen/Qwen3-8B-Instruct-GGUF/resolve/main/$model" `
  -OutFile "models\$model"
```
4-5 GB 程度。ダウンロードが遅ければ `huggingface-cli` (uv 経由でインストール可) を使うと resume が効く:
```powershell
uv tool run --from huggingface_hub huggingface-cli download `
  Qwen/Qwen3-8B-Instruct-GGUF $model --local-dir models --local-dir-use-symlinks False
```

### 4.3 Playwright Chromium
`PLAYWRIGHT_BROWSERS_PATH` を repo 配下に向け、per-user キャッシュを汚さない。
```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\vendor\playwright-browsers"
cd agent
uv run playwright install chromium
cd ..
```
環境変数は後述の `scripts/activate.ps1` で常時 export する。

### 4.4 VOICEVOX エンジン (portable)
```powershell
# CPU 版 zip。GPU 版もある。
$vv = "voicevox_engine-windows-cpu-x64-0.24.1"
Invoke-WebRequest "https://github.com/VOICEVOX/voicevox_engine/releases/download/0.24.1/$vv.7z" `
  -OutFile vendor\voicevox.7z
# 7z 展開には 7-Zip が必要。未導入なら: winget install 7zip.7zip -e
7z x vendor\voicevox.7z -ovendor\
Rename-Item "vendor\$vv" vendor\voicevox
Remove-Item vendor\voicevox.7z
```
`vendor\voicevox\run.exe` を daemon から子プロセスで spawn する。

---

## 5. 環境変数 / シークレット

### 5.1 `.env` (コミットしない)
```env
# Deepgram STT
DEEPGRAM_API_KEY=sk-xxxx

# (任意) llama-server の外部起動を使う場合のみ
# LLAMA_SERVER_URL=http://127.0.0.1:8080

# 開発用ログレベル
AGENT_LOG_LEVEL=DEBUG
```
`.env.example` はコミット、`.env` は `.gitignore` 対象。

### 5.2 `scripts/activate.ps1`
現シェルのみに環境変数を設定する薄いスクリプト。repo root で `. .\scripts\activate.ps1` すると必要な PATH/env が揃う。

```powershell
# scripts/activate.ps1 (中身イメージ)
$repo = (Resolve-Path "$PSScriptRoot\..").Path
$env:PLAYWRIGHT_BROWSERS_PATH = "$repo\vendor\playwright-browsers"
$env:LLAMA_SERVER_BIN         = "$repo\vendor\llama.cpp\llama-server.exe"
$env:LLAMA_MODEL              = "$repo\models\Qwen3-8B-Instruct-Q4_K_M.gguf"
$env:VOICEVOX_BIN             = "$repo\vendor\voicevox\run.exe"
$env:AGENT_DATA_DIR           = "$env:APPDATA\desktop-ai-agent"
Get-Content "$repo\.env" | ForEach-Object {
  if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
    [Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
  }
}
Write-Host "desktop-ai-agent env activated ($repo)"
```

永続化しない (Process scope) ので、シェルを閉じれば環境変数も消える。

---

## 6. 実行時データ配置

実行時のみ `%APPDATA%/desktop-ai-agent/` に以下を作成 (repo を消しても残る):
- `db.sqlite` — メモリ DB
- `logs/` — ローテートログ
- `browser-profile/` — agent 専用 Chromium プロファイル
- `downloads/` — Playwright ダウンロード sandbox
- `credentials/` — Windows Credential Manager 経由で storage_state 保管 (ファイルではなく DPAPI 保存)

完全アンインストール時はこのディレクトリ削除 + rustup/fnm/uv の個別アンインストールで根こそぎ消える。

---

## 7. 開発実行

```powershell
. .\scripts\activate.ps1   # 環境変数を流し込む
cd frontend
pnpm tauri dev             # Tauri が agent daemon を spawn、daemon が llama-server を spawn
```

初回は Rust のコンパイルで数分かかる。2 回目以降はインクリメンタル。

### 7.1 daemon 単体起動 (デバッグ用)
```powershell
cd agent
uv run python -m agent --port 0 --token dev
```

### 7.2 llama-server 単体起動 (LLM 動作確認)
```powershell
& $env:LLAMA_SERVER_BIN -m $env:LLAMA_MODEL --jinja --port 8080 -c 8192
```
その後 `curl http://127.0.0.1:8080/v1/models` で疎通確認。

---

## 8. 一括 setup スクリプト

上記 2–4 節の作業を自動化する `scripts/setup.ps1` を用意する (TBD)。初回セットアップは:

```powershell
. .\scripts\setup.ps1
```

で rustup / fnm / uv の導入〜依存インストール〜llama.cpp・モデル・Playwright・VOICEVOX 取得まで一気通貫。冪等に作り、既に存在するものは skip。

---

## 9. アンインストール

```powershell
# 1. repo を消す (project-local は全消滅)
Remove-Item -Recurse -Force C:\path\to\desktop-ai-agent

# 2. 実行時データ
Remove-Item -Recurse -Force $env:APPDATA\desktop-ai-agent

# 3. per-user ツール (任意、他プロジェクトで使ってなければ)
rustup self uninstall
winget uninstall Schniz.fnm
Remove-Item -Recurse -Force $env:USERPROFILE\.local\bin\uv.exe
```

root が残るのは Visual Studio Build Tools のみ。それ以外はこの 3 ステップで痕跡ゼロ。

---

## 10. `.gitignore` 追加候補

```gitignore
# project-local vendor
vendor/
models/
.venv/
node_modules/
frontend/dist/
frontend/src-tauri/target/

# secrets / state
.env
```
