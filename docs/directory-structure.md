# ディレクトリ構成

monorepo 構成。`frontend/` は Tauri + React、`agent/` は Python daemon、`shared/` は JSON-RPC 契約 (JSON Schema) を格納。

```
desktop-ai-agent/
├─ README.md
├─ docs/
│  ├─ spec.md                  # 初期メモ
│  ├─ spec-detailed.md         # 詳細仕様
│  ├─ architecture.md          # アーキ & ガードレール
│  └─ directory-structure.md   # 本ファイル
│
├─ shared/
│  └─ rpc/
│     ├─ schema.json           # JSON-RPC メソッド/イベント定義
│     └─ events.md
│
├─ frontend/                   # Tauri + React/TS
│  ├─ package.json
│  ├─ vite.config.ts
│  ├─ tsconfig.json
│  ├─ src-tauri/
│  │  ├─ tauri.conf.json        # 複数 window 定義
│  │  ├─ Cargo.toml
│  │  └─ src/
│  │     ├─ main.rs             # エントリ、plugin 初期化
│  │     ├─ daemon.rs           # Python 子プロセス spawn/監視/token 発行
│  │     ├─ windows/
│  │     │  ├─ character.rs     # 透過/click-through/ドラッグ
│  │     │  ├─ chat.rs
│  │     │  ├─ confirm.rs
│  │     │  ├─ settings.rs
│  │     │  └─ login_helper.rs
│  │     ├─ shortcuts.rs        # global shortcut 登録
│  │     ├─ tray.rs             # タスクトレイ
│  │     └─ ipc.rs              # daemon stdout/stderr tee
│  └─ src/
│     ├─ main.tsx               # ルートは window 種別で分岐
│     ├─ app/
│     │  ├─ CharacterApp.tsx    # character window root
│     │  ├─ ChatApp.tsx         # chat window root
│     │  ├─ ConfirmApp.tsx      # confirm window root
│     │  ├─ SettingsApp.tsx     # settings window root
│     │  └─ LoginHelperApp.tsx
│     ├─ features/
│     │  ├─ character/
│     │  │  ├─ Character.tsx
│     │  │  ├─ useCharacterState.ts
│     │  │  ├─ spriteMap.ts     # state×emotion → image path
│     │  │  └─ sprites/         # PNG 差分
│     │  ├─ bubble/             # 本文/thinking 分離表示
│     │  ├─ chat-panel/         # テキスト入力 + 履歴 + tool 折畳
│     │  ├─ voice/              # 録音ボタン、VAD 無し push-to-talk
│     │  │  ├─ VoiceButton.tsx
│     │  │  ├─ micCapture.ts    # MediaStream → 16kHz PCM
│     │  │  └─ ttsPlayer.ts     # WebAudio で chunk 再生
│     │  ├─ confirm-dialog/     # tool 承認 modal (domain/step 粒度)
│     │  ├─ notification/       # proactive 通知の出し分け
│     │  └─ settings/
│     │     ├─ CharacterSettings.tsx
│     │     ├─ VoiceSettings.tsx
│     │     ├─ BehaviorSettings.tsx
│     │     ├─ SecuritySettings.tsx  # allowlist / storage_state 管理
│     │     ├─ SchedulerSettings.tsx
│     │     ├─ MemorySettings.tsx
│     │     └─ LlmSettings.tsx
│     ├─ rpc/
│     │  ├─ client.ts           # 単一 WS、reconnect、RPC+event
│     │  ├─ binaryFrames.ts     # 音声 frame エンコード/デコード
│     │  └─ types.ts            # shared/rpc から自動生成
│     ├─ store/                 # zustand store 群 (§8.3 参照)
│     │  ├─ connectionStore.ts
│     │  ├─ characterStore.ts
│     │  ├─ chatStore.ts
│     │  ├─ confirmStore.ts
│     │  ├─ settingsStore.ts
│     │  └─ voiceStore.ts
│     └─ styles/
│
├─ agent/                      # Python daemon
│  ├─ pyproject.toml
│  ├─ uv.lock
│  ├─ src/agent/
│  │  ├─ __main__.py           # entrypoint
│  │  ├─ core/
│  │  │  ├─ config.py
│  │  │  ├─ logging.py
│  │  │  ├─ errors.py
│  │  │  ├─ types.py
│  │  │  └─ paths.py
│  │  ├─ interface/
│  │  │  ├─ server.py          # FastAPI + WS
│  │  │  ├─ rpc.py             # JSON-RPC dispatch
│  │  │  └─ auth.py            # local token
│  │  ├─ orchestrator/
│  │  │  ├─ session.py
│  │  │  ├─ turn_loop.py       # LLM + tool ループ
│  │  │  ├─ proactive.py       # 能動発話駆動
│  │  │  └─ prompt.py          # system/persona 構築
│  │  ├─ llm/
│  │  │  ├─ backend.py         # LLMBackend Protocol
│  │  │  ├─ llama_server.py    # llama-server (OpenAI互換) 実装
│  │  │  ├─ server_manager.py  # llama-server の spawn/監視/再起動
│  │  │  ├─ tool_schema.py     # Pydantic → JSON Schema 変換
│  │  │  └─ stream_parser.py   # <think> と本文の分離
│  │  ├─ tools/
│  │  │  ├─ base.py            # Tool ABC, risk, schema
│  │  │  ├─ registry.py
│  │  │  ├─ memory_tools.py
│  │  │  ├─ calendar_tools.py
│  │  │  ├─ schedule_tools.py
│  │  │  ├─ web_tools.py
│  │  │  ├─ windows_tools.py
│  │  │  ├─ shell_tools.py
│  │  │  └─ ask_user.py
│  │  ├─ memory/
│  │  │  ├─ db.py              # sqlite + FTS5 (trigram)
│  │  │  ├─ migrations/
│  │  │  ├─ core.py            # core_memory
│  │  │  ├─ behavior.py        # behavior_config
│  │  │  ├─ sessions.py        # session / messages / summary
│  │  │  └─ search.py          # memory.search (FTS5 MATCH)
│  │  ├─ scheduler/
│  │  │  ├─ cron.py            # APScheduler
│  │  │  ├─ calendar_poll.py
│  │  │  └─ custom_parser.py   # 自然言語→cron
│  │  ├─ voice/
│  │  │  ├─ pipeline.py        # Pipecat 定義
│  │  │  ├─ stt_deepgram.py
│  │  │  └─ tts_voicevox.py
│  │  ├─ integrations/
│  │  │  ├─ google_calendar/
│  │  │  ├─ playwright_worker/ # 別プロセス
│  │  │  │  ├─ worker.py
│  │  │  │  └─ client.py
│  │  │  └─ windows_uia/
│  │  │     ├─ worker.py
│  │  │     └─ client.py
│  │  └─ security/
│  │     ├─ allowlist.py
│  │     ├─ sandbox.py
│  │     └─ injection_filter.py
│  └─ tests/
│     ├─ unit/
│     ├─ integration/
│     └─ safety/               # prompt injection corpus
│
├─ scripts/
│  ├─ dev.ps1                  # frontend+agent 同時起動
│  ├─ package.ps1              # リリースビルド
│  └─ init-db.py
│
└─ .github/workflows/
   ├─ ci.yml
   └─ release.yml
```

## 補足ルール
- `agent/src/agent/interface/` は `orchestrator` より上、tools/memory を直接触らない
- `tools/*` は `integrations/*` 経由でのみ外部接続 (直接 `requests` 等禁止、lint で検査)
- `frontend/src/features/*` は `rpc/client.ts` 経由でのみ daemon 通信
- `shared/rpc/schema.json` を真実源とし、TS 型と Python `pydantic` モデルを自動生成 (`scripts/gen-rpc.ps1`)
- Python は `uv` + `ruff` + `mypy --strict`、TS は `pnpm` + `biome` or `eslint`
```
