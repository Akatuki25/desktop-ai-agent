# Phase 0 を実際に動かす

`docs/setup.md` のセットアップが完了している前提で、現状の Phase 0
実装を起動して **デスクトップに窓が立ち、テキストで Qwen3.5 9B と
会話できる** 状態まで持っていく手順。

## 現状 Phase 0 の範囲 (= 何が動くか)

| | 状態 |
|---|---|
| Tauri 透過窓 (always-on-top, decorationless) | ✅ |
| Tauri が Python daemon を子プロセスで spawn し、token + port を frontend へ橋渡し | ✅ |
| daemon が `LLAMA_SERVER_URL` を見て既存 llama-server を再利用 / 無ければ自前で spawn | ✅ |
| `LlamaServerBackend` が OpenAI 互換 `/v1/chat/completions` で stream | ✅ |
| Qwen3.5-9B GGUF がリアルに応答を返す (`Hello! How can I help you today?` を実走確認済み) | ✅ |
| 立ち絵 (sprite placeholder) と吹き出し (本文 / thinking 二層) | ✅ (画像はまだプレースホルダ glyph) |
| SQLite (`messages` / `sessions` / `core_memory` / `behavior_config` / FTS5 indexes) | ✅ |
| hot context 注入 (core_memory + behavior_config + 直近 session summaries) を system prompt に挿す | ✅ |

## まだ動かないもの (= Phase 0 の範囲外)

これは Phase 1 以降で実装する予定。**期待しないでください**:

- 音声入力 / 出力 (STT / TTS / Pipecat / Deepgram / VOICEVOX) — コードレベルで何も繋がっていない
- LLM tools (calendar / web / windows / shell / memory.search / ask_user) — `agent/tools/` ディレクトリ自体が無い
- スケジューラ / 能動発話 / Google Calendar 連携 — `agent/scheduler/` 無し
- 設定 UI / 承認 modal / トレイアイコン / global hotkey
- session の idle close / summary の LLM 自動生成 / rolling summary
- 立ち絵の本物の PNG 差分 (今は `…` `^_^` 等のグリフ)

詳しくは設計と実装のギャップ表を参照 (将来 `docs/gaps.md` などにまとめ予定)。

## 起動手順 (推奨パス)

### 1. setup.ps1 を一度走らせ済みであること
```powershell
.\scripts\setup.ps1
```
完了後は `vendor/llama.cpp/llama-server.exe`, `models/Qwen3.5-9B-Q4_K_M.gguf`, `agent/.venv/`, `frontend/node_modules/` が揃っている状態。

### 2. (推奨) llama-server を別シェルで先に上げておく

毎回 daemon が llama-server を spawn するとモデルロードに 30 秒ほど
取られるので、開発中は別シェルで常駐させておくとリロードが速い。

```powershell
# Shell A
. .\scripts\activate.ps1
& $env:LLAMA_SERVER_BIN -m $env:LLAMA_MODEL --port 8765 -c 4096 --jinja
```

`/v1/models` が 200 で答えれば ready:
```powershell
curl http://127.0.0.1:8765/v1/models
```

### 3. Tauri アプリを起動

```powershell
# Shell B
. .\scripts\activate.ps1
$env:LLAMA_SERVER_URL = "http://127.0.0.1:8765"   # Shell A の llama-server を再利用
cd frontend
pnpm tauri dev
```

`LLAMA_SERVER_URL` を渡すと daemon は自前 spawn せず既存サーバを使う。
渡さなければ daemon が `LLAMA_SERVER_BIN` から自分で llama-server を立てる
(その場合は Shell A は不要)。

### 4. 期待される挙動

ターミナルに以下のような流れが出る:

```
[tauri] spawning daemon: ...\agent\.venv\Scripts\python.exe
[agent] using external llama-server at http://127.0.0.1:8765
[tauri] daemon ready line: {"event": "ready", "port": <N>}
INFO:     Started server process [...]
INFO:     Uvicorn running on http://127.0.0.1:<N>
INFO:     127.0.0.1:<...> - "WebSocket /ws" [accepted]
INFO:     connection open
```

デスクトップ右上あたりに **透過 / 枠なし / 常時最前面** の小さい窓が現れる。

中央に sprite glyph (例: `・_・`)、下にテキスト入力欄。何か打って Enter
すると Qwen3.5 が応答を返し、bubble に流れてくる。

### 5. 動作確認

純粋な agent daemon の単体 smoke test も用意してある:

```powershell
cd agent
$env:LLAMA_SERVER_URL = "http://127.0.0.1:8765"
$env:RUN_LLM_INTEGRATION = "1"
uv run pytest tests/test_llama_server_live.py -v
```

`Reply with the single word: pong` → `pong` が返れば実 LLM 経路が
通っている証拠。

## デバッグ用の単体起動

### daemon だけを直接立てる
```powershell
. .\scripts\activate.ps1
$env:LLAMA_SERVER_URL = "http://127.0.0.1:8765"
cd agent
uv run python -m agent --token testtok --port 9876
```
別シェルから WS で叩ける:
```python
import asyncio, json, websockets
async def main():
    async with websockets.connect(
        "ws://127.0.0.1:9876/ws",
        additional_headers={"Authorization": "Bearer testtok"},
    ) as ws:
        await ws.send(json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "session.send_text",
            "params": {"text": "Say hello in one short line."},
        }))
        while True:
            print(await ws.recv())
asyncio.run(main())
```

### frontend だけを vite で立てる (Tauri 抜き)
```powershell
cd frontend
pnpm dev
# http://localhost:1420/?port=9876&token=testtok
```
URL クエリで daemon 接続情報を渡せば Tauri なしでも UI を試せる。

## 既知の落とし穴

| 症状 | 原因 | 対処 |
|------|------|------|
| Tauri 窓は出るが status が `closed` のまま | Tauri が daemon を spawn できなかった (Python venv 不在 等) | `agent/.venv/Scripts/python.exe` の存在確認 → 無ければ `uv sync` |
| `failed to spawn agent daemon` | 上と同じ | 同上 |
| 窓は出るが応答が帰ってこない | llama-server が落ちている / `LLAMA_SERVER_URL` が間違い | `curl <url>/v1/models` で確認、daemon ログを確認 |
| 応答が出るが thinking が見えない | 既知挙動 (Qwen3.5 は既定 `enable_thinking=false`)。`reasoning_content` 経路は実装済みなのでサーバ側で thinking を有効化すれば bubble に出る | — |
| Tauri ビルドが OS error 4551 | Smart App Control On | `setup.md` 前提 §3 |
| `cargo check` が `link: extra operand` | Git Bash の coreutils link が shadow | PowerShell から実行 |
