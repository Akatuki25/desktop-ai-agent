必要な機能雑多に書いてみた
こんなもんすか

フロント: tauri, TS/React
エージェント: Python daemon
LLM: Qwen3.5 8B(Ollamaまたはlamma.cpp)
音声対話: Pipecat, Deepgram, VOICEVOX(to beで声質自由の場合)
Web操作:Playwright
Windows操作: Windows.Graphics.Capture + Microsoft UI Automation (UIA) + PowerShell / Windows Script Host + COM
DB: SQLite

要件
基本的にアニメーションで動く二頭身くらいのキャラクターがデスクトップにいる感じ
常時歩き回るか隠れてるかは設定によりけり
local llmでアクティブじゃなさそうな時間帯にllmにfetch、ユーザーの興味ある内容の取得など
エージェントから声をかける(基本タスク)
予定管理もしくはカスタム指示
機能イメージ
基本cronと任意のカレンダーサービスの併用
タスク用エージェントを起動して、目的に応じたフローを辿る
(前触れなく声をかけるかアイコンで主張するかは任意)
用途イメージ
予定入れてたらそれのリマインド
(カレンダーアプリのAPIとか？もしくは定期的な予定取得)
カスタム指示
(この時間に定期的にニュースくれとか)
押してテキスト入力 or 音声ボタンで音声対話
機能イメージ
テキスト対話(LLMエージェント)
toolを持たせてAgentic workflow(toolによる行動空間の定義だけでも良いかも)
音声対話
一般的なカスケード設計でモデルの選定は上記
音声出力は任意(UIで調整したい)
VADとかは一旦考慮しないで、Pipecat使って簡潔に書くかなー
TTSはVDしたものをローカルで推論できるとgood
STTはStreamabaleなもの
LLMは基本的にはthinking切った形？精度要検証
共通内容
LLMにtool持たせて、考えてることを思考マークつけて、返答を吹き出しで
ユーザーに対して質問するtoolなども含む
用途イメージ
タスクと予定の登録
記憶の検索
Web検索
ブラウザ操作の手伝い
ツール設計
カレンダー連携
予定登録
Web検索
ブラウザ操作
エージェントタスク登録
DB設計
コアメモリ
会話、タスク単位のセッションのサマリー
調査からの知識グラフ
tool群
エージェントの振る舞い設定