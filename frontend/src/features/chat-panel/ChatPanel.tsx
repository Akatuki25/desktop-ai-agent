import { useState } from "react";
import { Bubble } from "../bubble/Bubble";
import { useChatStore } from "../../store";

interface ChatPanelProps {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export function ChatPanel({ onSend, disabled }: ChatPanelProps) {
  const messages = useChatStore((s) => s.messages);
  const appendUser = useChatStore((s) => s.appendUser);
  const [draft, setDraft] = useState("");

  const send = () => {
    const text = draft.trim();
    if (!text || disabled) return;
    appendUser(text);
    onSend(text);
    setDraft("");
  };

  return (
    <div data-testid="chat-panel">
      <ul
        data-testid="chat-history"
        style={{ listStyle: "none", padding: 0, margin: 0 }}
      >
        {messages.map((m) => (
          <li key={m.id}>
            <Bubble message={m} />
          </li>
        ))}
      </ul>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <input
          aria-label="message"
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          style={{ flex: 1 }}
        />
        <button type="button" onClick={send} disabled={disabled || !draft.trim()}>
          send
        </button>
      </div>
    </div>
  );
}
