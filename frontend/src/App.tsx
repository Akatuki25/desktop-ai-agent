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

export function App() {
  const setStatus = useConnectionStore((s) => s.setState);
  const status = useConnectionStore((s) => s.state);
  const agentState = useCharacterStore((s) => s.agentState);
  const emotion = useCharacterStore((s) => s.emotion);

  const [client, setClient] = useState<RpcClient | null>(null);
  const [draft, setDraft] = useState("");

  // Main reply bubble — only the final LLM answer, not tool status.
  const [replyText, setReplyText] = useState("");
  const [replyPending, setReplyPending] = useState(false);

  // Separate tool status line (small, below the sprite).
  const [toolStatus, setToolStatus] = useState("");

  // Auto-hide bubble after conversation ends.
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearHide = () => { if (hideTimer.current) { clearTimeout(hideTimer.current); hideTimer.current = null; } };
  const scheduleHide = () => { clearHide(); hideTimer.current = setTimeout(() => { setReplyText(""); setToolStatus(""); }, 12000); };

  const handleEvent = useCallback((evt: RpcEvent) => {
    const character = useCharacterStore.getState();
    if (evt.method === "agent.say") {
      const p = evt.params as { text?: string; emotion?: unknown; is_thinking?: boolean };
      const em: Emotion = isEmotion(p.emotion) ? p.emotion : "neutral";
      character.setEmotion(em);
      character.setAgentState(p.is_thinking ? "thinking" : "talking");

      if (p.is_thinking) {
        // Tool status goes to the separate status line, not the bubble.
        setToolStatus((prev) => prev + (p.text ?? ""));
      } else {
        // Actual reply goes to the bubble.
        setReplyText((prev) => prev + (p.text ?? ""));
      }
      clearHide();
    } else if (evt.method === "agent.say_end") {
      character.setAgentState("idle");
      setReplyPending(false);
      setToolStatus("");
      scheduleHide();
    } else if (evt.method === "notification.proactive") {
      const p = evt.params as { text?: string };
      setReplyText(p.text ?? "");
      setReplyPending(false);
      setToolStatus("");
      scheduleHide();
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
    setReplyText("");
    setToolStatus("");
    setReplyPending(true);
    clearHide();
    useCharacterStore.getState().setAgentState("thinking");
    client.send("session.send_text", { text });
    setDraft("");
  };

  const sprite = resolveSprite(agentState, emotion);

  return (
    <div
      style={{
        position: "relative",
        width: 280,
        height: 400,
        display: "flex",
        flexDirection: "column",
        background: "transparent",
        userSelect: "none",
        overflow: "hidden",
      }}
    >
      {/* Fixed layout: bubble at top, character in middle, input at bottom */}

      {/* Reply bubble — fixed position above the character */}
      <div style={{ height: 100, display: "flex", alignItems: "flex-end", justifyContent: "center", padding: "0 10px" }}>
        {replyText ? (
          <div
            style={{
              maxWidth: 260,
              maxHeight: 96,
              overflowY: "auto",
              padding: "6px 10px",
              borderRadius: 10,
              background: "rgba(255,255,255,0.95)",
              border: "1px solid rgba(0,0,0,0.1)",
              boxShadow: "0 2px 6px rgba(0,0,0,0.06)",
              fontSize: 12,
              lineHeight: 1.5,
              wordBreak: "break-word",
              opacity: replyPending ? 0.8 : 1,
            }}
          >
            {replyText}
          </div>
        ) : replyPending ? (
          <div style={{ fontSize: 11, opacity: 0.5 }}>...</div>
        ) : null}
      </div>

      {/* Character sprite — fixed position, never moves */}
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
        {sprite && (
          <img
            src={sprite}
            alt=""
            draggable={false}
            style={{ width: 180, height: "auto", pointerEvents: "none" }}
          />
        )}
      </div>

      {/* Tool status — small text below sprite, separate from bubble */}
      {toolStatus && (
        <div style={{
          textAlign: "center",
          fontSize: 10,
          opacity: 0.5,
          fontStyle: "italic",
          padding: "0 10px 2px",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}>
          {toolStatus}
        </div>
      )}

      {/* Input — fixed at bottom */}
      {status === "open" && (
        <div style={{ padding: "4px 10px 8px" }}>
          <input
            aria-label="message"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="話しかける..."
            style={{
              width: "100%",
              border: "1px solid rgba(0,0,0,0.15)",
              borderRadius: 8,
              padding: "6px 10px",
              fontSize: 13,
              background: "rgba(255,255,255,0.9)",
              outline: "none",
              boxSizing: "border-box",
            }}
          />
        </div>
      )}
    </div>
  );
}
