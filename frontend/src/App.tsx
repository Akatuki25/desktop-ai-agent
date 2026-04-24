import { useCallback, useEffect, useRef, useState } from "react";
import { resolveSprite } from "./features/character/spriteMap";
import { playWav } from "./features/voice/ttsPlayer";
import { resolveDaemonInfo, type DaemonInfo } from "./rpc/bootstrap";
import { createRpcClient, type RpcClient, type RpcEvent } from "./rpc/client";
import {
  useCharacterStore,
  useConnectionStore,
  type Emotion,
} from "./store";

const VALID_EMOTIONS: ReadonlySet<Emotion> = new Set([
  "neutral", "smile", "think", "surprise", "sad", "angry",
]);
function isEmotion(v: unknown): v is Emotion {
  return typeof v === "string" && VALID_EMOTIONS.has(v as Emotion);
}

/** Only the latest agent reply is shown — not a chat history. */
interface LatestReply {
  text: string;
  thinking: string;
  pending: boolean;
}

export function App() {
  const setStatus = useConnectionStore((s) => s.setState);
  const status = useConnectionStore((s) => s.state);
  const agentState = useCharacterStore((s) => s.agentState);
  const emotion = useCharacterStore((s) => s.emotion);

  const [client, setClient] = useState<RpcClient | null>(null);
  const [draft, setDraft] = useState("");
  const [reply, setReply] = useState<LatestReply | null>(null);
  const [bubbleVisible, setBubbleVisible] = useState(false);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearHideTimer = () => {
    if (hideTimer.current) {
      clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  };

  const scheduleBubbleHide = () => {
    clearHideTimer();
    hideTimer.current = setTimeout(() => setBubbleVisible(false), 8000);
  };

  const handleEvent = useCallback((evt: RpcEvent) => {
    const character = useCharacterStore.getState();
    if (evt.method === "agent.say") {
      const p = evt.params as { text?: string; emotion?: unknown; is_thinking?: boolean };
      const em: Emotion = isEmotion(p.emotion) ? p.emotion : "neutral";
      character.setEmotion(em);
      character.setAgentState(p.is_thinking ? "thinking" : "talking");
      setReply((prev) => {
        const base = prev?.pending ? prev : { text: "", thinking: "", pending: true };
        if (p.is_thinking) {
          return { ...base, thinking: base.thinking + (p.text ?? "") };
        }
        return { ...base, text: base.text + (p.text ?? "") };
      });
      setBubbleVisible(true);
      clearHideTimer();
    } else if (evt.method === "agent.say_end") {
      character.setAgentState("idle");
      setReply((prev) => prev ? { ...prev, pending: false } : prev);
      scheduleBubbleHide();
    } else if (evt.method === "notification.proactive") {
      const p = evt.params as { text?: string };
      setReply({ text: p.text ?? "", thinking: "", pending: false });
      setBubbleVisible(true);
      scheduleBubbleHide();
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let cur: RpcClient | null = null;
    (async () => {
      const info: DaemonInfo | null = await resolveDaemonInfo();
      if (cancelled) return;
      if (!info) { setStatus("closed"); return; }
      setStatus("connecting");
      cur = createRpcClient({
        url: `ws://127.0.0.1:${info.port}/ws`,
        token: info.token,
        onEvent: handleEvent,
        onStatus: setStatus,
        onBinary: (data: ArrayBuffer) => {
          const view = new Uint8Array(data);
          if (view[0] === 0x02 && view.length > 9) {
            playWav(data.slice(9)).catch(console.error);
          }
        },
      });
      setClient(cur);
    })();
    return () => { cancelled = true; cur?.close(); };
  }, [setStatus, handleEvent]);

  const send = () => {
    const text = draft.trim();
    if (!text || !client || status !== "open") return;
    // Clear previous reply and show "thinking" state immediately.
    setReply({ text: "", thinking: "", pending: true });
    setBubbleVisible(true);
    clearHideTimer();
    useCharacterStore.getState().setAgentState("thinking");
    client.send("session.send_text", { text });
    setDraft("");
  };

  const sprite = resolveSprite(agentState, emotion);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: 0,
        background: "transparent",
        userSelect: "none",
        width: 280,
      }}
    >
      {/* Bubble — only the latest reply, fades out after 8s */}
      {bubbleVisible && reply && reply.text && (
        <div
          style={{
            maxWidth: 260,
            padding: "8px 12px",
            borderRadius: 12,
            background: "rgba(255,255,255,0.95)",
            border: "1px solid rgba(0,0,0,0.1)",
            boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
            fontSize: 13,
            lineHeight: 1.5,
            marginBottom: 4,
            wordBreak: "break-word",
            opacity: reply.pending ? 0.7 : 1,
            transition: "opacity 200ms",
          }}
        >
          {reply.text}
        </div>
      )}

      {/* Character sprite */}
      {sprite && (
        <img
          src={sprite}
          alt=""
          draggable={false}
          style={{
            width: 180,
            height: "auto",
            pointerEvents: "none",
          }}
        />
      )}

      {/* Compact input — only visible when connected */}
      {status === "open" && (
        <div style={{ display: "flex", gap: 4, marginTop: 4, width: "100%" }}>
          <input
            aria-label="message"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="話しかける..."
            style={{
              flex: 1,
              border: "1px solid rgba(0,0,0,0.15)",
              borderRadius: 8,
              padding: "6px 10px",
              fontSize: 13,
              background: "rgba(255,255,255,0.9)",
              outline: "none",
            }}
          />
        </div>
      )}
    </div>
  );
}
