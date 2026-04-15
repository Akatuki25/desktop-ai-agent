import type { ChatMessage } from "../../store";

interface BubbleProps {
  message: ChatMessage;
}

/**
 * Two-layer bubble:
 *   - thinking layer: dim, italic, only rendered when the message has
 *     any thinking content
 *   - main layer: the text the user sees as "speech"
 */
export function Bubble({ message }: BubbleProps) {
  const isAgent = message.role === "agent";
  return (
    <div
      data-testid="bubble"
      data-role={message.role}
      data-pending={message.pending}
      data-emotion={message.emotion}
      style={{
        padding: "8px 12px",
        borderRadius: 12,
        background: isAgent ? "rgba(255,255,255,0.92)" : "rgba(40,110,255,0.15)",
        border: "1px solid rgba(0,0,0,0.08)",
        marginBottom: 6,
      }}
    >
      {message.thinking ? (
        <div
          data-testid="bubble-thinking"
          style={{
            fontStyle: "italic",
            opacity: 0.55,
            fontSize: 12,
            marginBottom: 4,
          }}
        >
          {message.thinking}
        </div>
      ) : null}
      <div data-testid="bubble-text">{message.text}</div>
    </div>
  );
}
