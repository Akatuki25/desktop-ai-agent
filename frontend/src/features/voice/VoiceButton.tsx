import { useCallback, useEffect } from "react";
import type { RpcClient } from "../../rpc/client";
import { useVoiceStore } from "../../store/voiceStore";
import { startCapture, stopCapture } from "./micCapture";

interface VoiceButtonProps {
  client: RpcClient | null;
  disabled?: boolean;
}

/**
 * Click-to-toggle voice button.
 *
 * Push-to-talk reads better on paper but is fragile in practice:
 * the first-time mic permission prompt eats pointer events, leaving
 * the button stuck in "recording" with no pointerup to escape. A
 * plain click toggles cleanly regardless of when the prompt fires,
 * and Escape gives a keyboard fallback.
 */
export function VoiceButton({ client, disabled }: VoiceButtonProps) {
  const recording = useVoiceStore((s) => s.recording);
  const setRecording = useVoiceStore((s) => s.setRecording);
  const clearPartial = useVoiceStore((s) => s.clearPartial);

  const begin = useCallback(async () => {
    if (!client || disabled) return;
    setRecording(true);
    try {
      // Tell the daemon first so the STT session is open before audio
      // arrives — otherwise initial frames get dropped.
      client.send("voice.start", {});
      await startCapture((data) => client.sendBinary(data));
    } catch (e) {
      console.error("[voice] startCapture failed:", e);
      setRecording(false);
      clearPartial();
      // Best-effort: tell the daemon to release its session even
      // though we never got mic data. Otherwise it would hang waiting.
      try {
        client.send("voice.stop", {});
      } catch {
        // ignore
      }
    }
  }, [client, disabled, setRecording, clearPartial]);

  const end = useCallback(async () => {
    setRecording(false);
    clearPartial();
    try {
      await stopCapture();
    } catch (e) {
      console.error("[voice] stopCapture failed:", e);
    }
    if (client) client.send("voice.stop", {});
  }, [client, setRecording, clearPartial]);

  const toggle = useCallback(() => {
    if (recording) void end();
    else void begin();
  }, [recording, begin, end]);

  // Escape key cancels recording. Cheap fallback in case the button
  // itself gets visually obscured or unresponsive.
  useEffect(() => {
    if (!recording) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") void end();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [recording, end]);

  return (
    <button
      type="button"
      aria-label={recording ? "stop recording" : "start recording"}
      aria-pressed={recording}
      title={recording ? "クリックで停止 (Esc)" : "クリックで音声入力を開始"}
      disabled={disabled || !client}
      onClick={toggle}
      style={{
        width: 32,
        height: 32,
        border: "1px solid rgba(0,0,0,0.15)",
        borderRadius: "50%",
        background: recording ? "#e74c3c" : "rgba(255,255,255,0.9)",
        cursor: disabled || !client ? "not-allowed" : "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 0,
        flexShrink: 0,
      }}
    >
      {recording ? (
        <span
          style={{
            display: "inline-block",
            width: 12,
            height: 12,
            background: "#fff",
            borderRadius: "50%",
          }}
        />
      ) : (
        <span style={{ fontSize: 14, lineHeight: 1 }} aria-hidden>
          🎙
        </span>
      )}
    </button>
  );
}
