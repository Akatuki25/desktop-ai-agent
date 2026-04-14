# アーキテクチャ & ガードレール

## 1. システム構成図 (論理)

```
┌─────────────────────────────────────────┐
│ Tauri App (frontend process)            │
│  ├─ React UI (character / bubble / panel)
│  ├─ Audio capture / playback            │
│  └─ JSON-RPC client (WebSocket)         │
└───────────────┬─────────────────────────┘
                │ ws://127.0.0.1
┌───────────────┴─────────────────────────┐
│ Python Daemon (agent-core)              │
│  ├─ Gateway (FastAPI + WS)              │
│  ├─ Orchestrator (session / turn loop)  │
│  ├─ LLM client (llama-server, OpenAI互換)│
│  ├─ Tool registry + executor            │
│  ├─ Scheduler (APScheduler)             │
│  ├─ Memory service (SQLite + vec)       │
│  ├─ Voice pipeline (Pipecat)            │
│  └─ Integrations (Calendar/Web/Win)     │
└─────────────────────────────────────────┘
```

プロセスモデル: Tauri が子プロセスとして Python daemon を spawn。daemon は単一プロセス (async)、重い操作 (Playwright, UIA) は別 subprocess worker に分離。

## 2. レイヤ構成 (daemon 内)

| レイヤ | 責務 | 依存先 |
|--------|------|--------|
| `interface/` | WS/JSON-RPC、Tauri との契約 | orchestrator |
| `orchestrator/` | 対話ターン、能動発話の駆動 | llm, tools, memory |
| `llm/` | llama-server 呼び出し (OpenAI互換)、prompt構築、tool schema 変換 | — |
| `tools/` | tool 実装 (`base.Tool` を継承) | integrations |
| `memory/` | SQLite + FTS5 (trigram) | — |
| `scheduler/` | cron/calendar driven trigger | orchestrator |
| `voice/` | Pipecat pipeline | — |
| `integrations/` | Playwright/UIA/Calendar adapter | — |
| `core/` | 設定/ログ/エラー/型 | — |

**依存方向**: `interface → orchestrator → (llm, tools, memory, voice)` 、`tools → integrations`。逆流禁止 (lint で検査)。

## 3. ターン処理フロー
1. `user.text` 受信 → Orchestrator が session load (無ければ新規作成)
2. **hot context を組み立て**: `core_memory` 全件 + `behavior_config` 全件 + 直近 N 件の `sessions.summary` + 当該 session の直近 messages
3. Prompt 構築 (persona + hot context + tool schema + history)。**cold な過去ログは prompt に入れず、LLM が必要なら `memory.search` tool で取りに行く** (grep 的な keyword 検索)
4. llama-server へ stream 要求 → `<think>` と本文を分離して都度 WS push、tool_calls は llama.cpp の Hermes パーサ経由で構造化済みで受信
5. tool call が返る → 危険度判定 → 必要なら `tool.request_confirm`
6. 実行 → 結果を context に注入 → 再度 LLM へ (最大 N=5 ステップ)
7. session クローズ時 (idle タイムアウト or 明示終了): LLM で `title` と `summary` を非同期生成して `sessions` を UPDATE、FTS5 インデックスに反映

## 3.1 memory.search の内部動作
- SQLite FTS5 (trigram tokenizer) で `messages_fts` と `sessions_fts` に MATCH クエリ
- BM25 スコア順、`kind` フィルタ可、既定 limit 10
- 埋め込み類似度は使わない。必要になった時点で内部実装だけ差し替える

## 4. ガードレール

### 4.1 権限と承認
- 全 tool に `risk: low|medium|high` と `requires_confirmation: bool` を宣言
- 設定で `auto_approve_level` を持ち、既定は `low` のみ自動
- 承認 UI は Tauri 側 modal、タイムアウト 60s で拒否扱い

### 4.2 実行サンドボックス
- `shell.run`: 許可コマンド allowlist + 引数 regex 検査、`cmd.exe`禁止、`-File` 実行のみ
- `web.browse`: ドメイン allowlist/blocklist、downloads は sandbox dir 固定
- `windows.ui_action`: 対象ウィンドウ title を明示、該当なしなら失敗

### 4.3 LLM 安全策
- System prompt に "tool 引数は必ず user 指示に裏付け" と明記
- Tool result 注入時は `role: tool` 固定、文字列長上限 8k で切詰め
- Prompt injection 対策: web/tool 由来テキストは `[UNTRUSTED]` タグで囲み、実行指示を無視するよう system で指定
- 無限ループ防止: 1 turn 内 tool 呼び出し回数 ≤ 5、連続同一 tool 呼び出しは失敗扱い

### 4.4 データ保護
- core_memory と tool_log は暗号化 (SQLCipher) オプション
- Google 認証 token は Windows Credential Manager に保存
- ログに PII マスキング (メール/電話)

### 4.5 リソース制御
- LLM 同時実行 1、キュー長 上限 4
- Playwright セッション 同時 1、idle 5 分で close
- 音声セッション中は背景 fetch を一時停止

### 4.6 監査
- 全 tool 呼び出しを `tool_calls` に append-only 記録 (args/result/status)
- 危険 tool は別ファイルにもミラー、手動監査用

## 5. エラー/障害設計
- llama-server 落ち: 指数バックオフ再接続、UI 上で "LLM 未接続" state。daemon が llama-server を子プロセスとして spawn/監視し、落ちたら再起動
- DB 破損: 起動時 integrity check、失敗で `db.corrupt.bak` に退避し新規作成
- Tauri ↔ daemon 切断: 双方ハートビート 5s、欠落で UI は "再接続中"

## 6. 設定
- `%APPDATA%/desktop-ai-agent/config.toml`
- セクション: `[llm] [voice] [character] [scheduler] [tools] [security]`
- hot reload 対応 (watchdog)

## 7. テスト戦略
- unit: tools/memory/llm prompt builder
- integration: orchestrator + fake LLM (録画リプレイ)
- e2e: Tauri devtools + Playwright で UI スモーク
- 安全性: prompt injection corpus で tool 実行が抑制されるか回帰
