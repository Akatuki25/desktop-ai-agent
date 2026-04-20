import { useCallback, useEffect, useState } from "react";
import { Character } from "./features/character/Character";
import { ChatPanel } from "./features/chat-panel/ChatPanel";
import { Notification } from "./features/notification/Notification";
import { playWav } from "./features/voice/ttsPlayer";
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

interface ProactiveNote {
  text: string;
  urgency: "high" | "normal" | "low";
}

function handleEvent(
  evt: RpcEvent,
  setNotification: (n: ProactiveNote | null) => void,
): void {
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
  } else if (evt.method === "notification.proactive") {
    const p = evt.params as { text?: string; urgency?: string };
    setNotification({
      text: p.text ?? "",
      urgency: (["high", "normal", "low"].includes(p.urgency ?? "")
        ? p.urgency
        : "normal") as ProactiveNote["urgency"],
    });
  } else if (evt.method === "tool.request_confirm") {
    const p = evt.params as { tool?: string; args?: unknown; reason?: string };
    chat.applyAgentDelta({
      text: `[tool: ${p.tool}] ${JSON.stringify(p.args)}`,
      emotion: "think",
      isThinking: true,
    });
  } else if (evt.method === "tool.result") {
    const p = evt.params as { ok?: boolean; summary?: string };
    chat.applyAgentDelta({
      text: `[result: ${p.ok ? "ok" : "error"}] ${p.summary ?? ""}`,
      emotion: "neutral",
      isThinking: true,
    });
  }
}

export function App() {
  const status = useConnectionStore((s) => s.state);
  const setStatus = useConnectionStore((s) => s.setState);
  const [client, setClient] = useState<RpcClient | null>(null);
  const [notification, setNotification] = useState<ProactiveNote | null>(null);

  const eventHandler = useCallback(
    (evt: RpcEvent) => handleEvent(evt, setNotification),
    [],
  );

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
        onEvent: eventHandler,
        onStatus: setStatus,
        onBinary: (data: ArrayBuffer) => {
          // Tag byte 0x02 = TTS audio
          const view = new Uint8Array(data);
          if (view[0] === 0x02 && view.length > 9) {
            playWav(data.slice(9)).catch(console.error);
          }
        },
      });
      setClient(currentClient);
    })();

    return () => {
      cancelled = true;
      currentClient?.close();
    };
  }, [setStatus, eventHandler]);

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
      {notification && (
        <Notification
          text={notification.text}
          urgency={notification.urgency}
          onDismiss={() => setNotification(null)}
        />
      )}
      <Character />
      <ChatPanel
        disabled={status !== "open"}
        onSend={(text) => client?.send("session.send_text", { text })}
      />
    </div>
  );
}
