# desktop-ai-agent

ローカル LLM (Qwen3.5) と Deepgram STT / VOICEVOX TTS を組み合わせた、
デスクトップ常駐型の AI コンパニオン。Tauri 製の小さな透過窓に立ち絵
が出て、テキストでも音声でも対話できる。

```
┌──────────────────────────────────────┐
│ Tauri (透過 / 枠なし / 常時最前面)   │
│  React UI ─ JSON-RPC over WebSocket  │
└────────────────┬─────────────────────┘
                 │ ws://127.0.0.1:<ephemeral>
┌────────────────┴─────────────────────┐
│ Python daemon (FastAPI + uvicorn)    │
│  ├ Orchestrator (TurnLoop / Session) │
│  ├ LLM client → llama-server         │
│  ├ Voice (Deepgram STT / VOICEVOX)   │
│  ├ Tools (memory / web / schedule)   │
│  └ Memory (SQLite + FTS5)            │
└────────────────┬─────────────────────┘
                 │
        llama-server + GGUF (Qwen3.5)
```

## いま動くもの

| | 状態 |
|---|---|
| Tauri 透過窓 (枠なし / 常時最前面 / ドラッグで移動) | ✅ |
| Tauri が daemon を spawn → port/token を渡して WS 接続 | ✅ |
| llama-server を daemon が spawn (Apple Silicon は Metal で `-ngl 99`) | ✅ |
| Qwen3.5 4B / 9B GGUF どちらでも切替可 (`MODEL_SIZE` 環境変数) | ✅ |
| テキスト対話 + 立ち絵 + 吹き出し (本文 / thinking 二層) | ✅ |
| 音声対話 (Deepgram STT → TurnLoop → VOICEVOX TTS) | ✅ |
| 連続会話モード — Deepgram の `UtteranceEnd` で turn 自動発火 | ✅ |
| 半二重制御 — 発話中は STT を遮断 (echo による自己 interrupt 防止) | ✅ |
| メモリ (`messages` / `sessions` / `core_memory` / `behavior_config` / FTS5) | ✅ |
| アイドル 10 分でセッション自動 close + LLM サマリ | ✅ |
| `session.close` tool (LLM が「保存して」と言われたら明示クローズ) | ✅ |
| 立ち絵の本物の差分 PNG | 🚧 (現在はプレースホルダ) |
| Calendar / Windows UIA / Playwright tool | 🚧 (Phase 4 以降) |

## クイックスタート

OS 別のセットアップ手順は別ドキュメントにある。どちらも 1 本の
スクリプトで Rust / Node / Python toolchain と llama.cpp / GGUF /
VOICEVOX まで一括で入る (15–30 分)。

| OS | ドキュメント | スクリプト |
|---|---|---|
| Windows 10/11 | [`docs/setup.md`](docs/setup.md) | `scripts\setup.ps1` |
| macOS (Apple Silicon / Intel) | [`docs/setup-macos.md`](docs/setup-macos.md) | `scripts/setup.sh` |

セットアップ後の起動は共通で:

```sh
# macOS / Linux
source ./scripts/activate.sh
cd frontend && pnpm tauri dev
```

```powershell
# Windows
. .\scripts\activate.ps1
cd frontend; pnpm tauri dev
```

`.env` に `DEEPGRAM_API_KEY` を入れると音声入力が有効になる
(キーが空なら text-only で動く)。

## アーキテクチャ要点

- **Tauri ↔ daemon は 1 本の WebSocket** (`ws://127.0.0.1:<port>/ws`)。
  Tauri が起動時に Python daemon を子プロセスとして spawn、daemon は
  ephemeral port を bind して `{"event":"ready","port":N}` を stdout
  に出す。Tauri はそれを read してフロントに `daemon_info` で渡す。
- **token-based 認証** — UUID トークンを起動毎に生成、ブラウザは
  `Sec-WebSocket-Protocol: bearer.<token>` で渡す (任意ヘッダが
  ブラウザ WS API では使えないため)。
- **Hot context** — system prompt には `core_memory` 全件 +
  `behavior_config` 全件 + 直近 N 件の `sessions.summary` + 当該
  session の直近 messages のみ詰める。古いログは入れず、LLM が
  必要なら `memory.search` tool で取りに行く (FTS5 trigram MATCH)。
- **Voice 半二重** — Deepgram に `vad_events=true&utterance_end_ms=1000`
  を設定して `UtteranceEnd` で自動 turn 発火。発話中は `feed_audio`
  が PCM を Deepgram に流さず、frontend が再生キュー drain で
  `voice.tts_done` を投げてゲート解除。
- **session lifecycle** — 60 秒間隔の watcher が `_last_activity` から
  10 分超のチャットを auto-close + サマリ生成 (`SessionManager.run_idle_watcher`)。
  シャットダウン時にも残った open chat を最終 close する
  (`@app.on_event("shutdown")`)。

詳しくは [`docs/architecture.md`](docs/architecture.md)。

## ディレクトリ構成 (要点のみ)

```
desktop-ai-agent/
├─ agent/                  # Python daemon (uv プロジェクト)
│  └─ src/agent/
│     ├─ interface/        # FastAPI + WebSocket
│     ├─ orchestrator/     # TurnLoop / SessionManager
│     ├─ llm/              # llama-server クライアント
│     ├─ tools/            # memory.search / session.close / web.* / schedule.*
│     ├─ memory/           # SQLite + FTS5
│     ├─ voice/            # Deepgram STT / VOICEVOX TTS / 半二重 pipeline
│     └─ scheduler/        # APScheduler (cron) + proactive
├─ frontend/               # Tauri (Rust) + Vite + React
│  ├─ src/                 # React (App, features/voice / character / chat-panel)
│  └─ src-tauri/           # Tauri shell (daemon spawn, Info.plist)
├─ shared/rpc/             # JSON-RPC schema (TS / Python の真実源)
├─ scripts/                # setup / activate / verify (ps1 + sh)
├─ docs/                   # spec / architecture / setup / setup-macos
├─ models/                 # GGUF モデル (gitignore)
└─ vendor/                 # llama.cpp prebuilt + VOICEVOX engine (gitignore)
```

詳しくは [`docs/directory-structure.md`](docs/directory-structure.md)。

## 開発コマンド

```sh
# 8 ステップ verify (agent ruff/mypy/pytest, frontend typecheck/test, tauri cargo check)
./scripts/verify.sh           # macOS / Linux
.\scripts\verify.ps1          # Windows

# agent 単体
cd agent
uv run pytest                 # ユニットテスト
uv run ruff check .           # lint
uv run mypy                   # 型検査

# frontend 単体
cd frontend
pnpm typecheck
pnpm test                     # vitest
pnpm tauri dev                # 実起動
```

実機 LLM を使う統合テストは別ファイル
(`agent/tests/test_llama_server_live.py`、`RUN_LLM_INTEGRATION=1` 必須)。
詳細は [`docs/setup.md`](docs/setup.md) の最終節。

## モデル切替

`.env` の `MODEL_SIZE` で 9B / 4B を切替 (両方 `models/` に置いておけば
シェル変数 1 つで往復できる)。setup スクリプト初回実行は既定 9B、
低スペック機向けに `--model 4B` (`-Model 4B`) フラグあり。

| サイズ | repo | ファイル | DL | 推奨 |
|---|---|---|---|---|
| 9B (default) | `unsloth/Qwen3.5-9B-GGUF` | `Qwen3.5-9B-Q4_K_M.gguf` | ~5.4GB | RAM 16GB+, GPU/Metal あり |
| 4B | `unsloth/Qwen3.5-4B-GGUF` | `Qwen3.5-4B-Q4_K_M.gguf` | ~2.4GB | 軽量機、CPU only |

Apple Silicon は llama.cpp の Metal prebuilt が自動的に全レイヤを
GPU にオフロード (`-ngl 99` を環境変数 `LLAMA_NGL` で上書き可能)。

## ドキュメント

| ファイル | 用途 |
|---|---|
| [`docs/spec.md`](docs/spec.md) | 当初の機能メモ (起源) |
| [`docs/spec-detailed.md`](docs/spec-detailed.md) | 詳細仕様 |
| [`docs/architecture.md`](docs/architecture.md) | レイヤ構成、ガードレール、ターン処理フロー |
| [`docs/directory-structure.md`](docs/directory-structure.md) | repo レイアウト |
| [`docs/setup.md`](docs/setup.md) | Windows セットアップ (PowerShell) |
| [`docs/setup-macos.md`](docs/setup-macos.md) | macOS セットアップ (bash / zsh) |
| [`docs/run.md`](docs/run.md) | Phase 0 を実際に動かす手順 |

## ライセンス

未定 (private / WIP)。
