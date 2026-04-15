import { useEffect, useState } from "react";
import { Character } from "./features/character/Character";
import { ChatPanel } from "./features/chat-panel/ChatPanel";
import { resolveDaemonInfo, type DaemonInfo } from "./rpc/bootstrap";
import { createRpcClient, type RpcClient, type RpcEvent } from "./rpc/client";
import {
  useChatStore,
  useCharacterStore,
  useConnectionStore,
  type Emotion,
} from "./store";

const VALID_EMOTIONS: ReadonlySet<Emotion> = new Set([
  "neutral",
  "smile",
  "think",
  "surprise",
  "sad",
  "angry",
]);

function isEmotion(value: unknown): value is Emotion {
  return typeof value === "string" && VALID_EMOTIONS.has(value as Emotion);
}

function handleEvent(evt: RpcEvent): void {
  const chat = useChatStore.getState();
  const character = useCharacterStore.getState();

  if (evt.method === "agent.say") {
    const params = evt.params as {
      text?: string;
      emotion?: unknown;
      is_thinking?: boolean;
    };
    const emotion: Emotion = isEmotion(params.emotion) ? params.emotion : "neutral";
    chat.applyAgentDelta({
      text: params.text ?? "",
      emotion,
      isThinking: Boolean(params.is_thinking),
    });
    character.setEmotion(emotion);
    character.setAgentState(params.is_thinking ? "thinking" : "talking");
  } else if (evt.method === "agent.say_end") {
    chat.finalizeAgent();
    character.setAgentState("idle");
  }
}

export function App() {
  const status = useConnectionStore((s) => s.state);
  const setStatus = useConnectionStore((s) => s.setState);
  const [client, setClient] = useState<RpcClient | null>(null);

  useEffect(() => {
    let cancelled = false;
    let currentClient: RpcClient | null = null;

    (async () => {
      const info: DaemonInfo | null = await resolveDaemonInfo();
      if (cancelled) return;
      if (!info) {
        setStatus("closed");
        return;
      }
      setStatus("connecting");
      currentClient = createRpcClient({
        url: `ws://127.0.0.1:${info.port}/ws`,
        token: info.token,
        onEvent: handleEvent,
        onStatus: setStatus,
      });
      setClient(currentClient);
    })();

    return () => {
      cancelled = true;
      currentClient?.close();
    };
  }, [setStatus]);

  return (
    <div
      style={{
        fontFamily: "system-ui",
        padding: 12,
        width: 380,
        background: "transparent",
      }}
    >
      <header style={{ marginBottom: 8 }}>
        <h1 style={{ fontSize: 14, margin: 0 }}>desktop-ai-agent</h1>
        <p data-testid="status" style={{ fontSize: 11, opacity: 0.6, margin: 0 }}>
          status: {status}
        </p>
      </header>
      <Character />
      <ChatPanel
        disabled={status !== "open"}
        onSend={(text) => client?.send("session.send_text", { text })}
      />
    </div>
  );
}
