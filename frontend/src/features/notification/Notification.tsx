import { useEffect, useState } from "react";

interface NotificationProps {
  text: string;
  urgency: "high" | "normal" | "low";
  onDismiss: () => void;
}

/**
 * Proactive notification banner.
 * - high: full bubble + border highlight
 * - normal: subtle bubble
 * - low: icon-only (click to expand)
 */
export function Notification({ text, urgency, onDismiss }: NotificationProps) {
  const [expanded, setExpanded] = useState(urgency !== "low");

  useEffect(() => {
    if (urgency !== "high") {
      const t = setTimeout(onDismiss, 8000);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [urgency, onDismiss]);

  if (!expanded) {
    return (
      <div
        data-testid="notification-icon"
        onClick={() => setExpanded(true)}
        style={{
          cursor: "pointer",
          fontSize: 20,
          textAlign: "center",
          animation: "pulse 1s infinite",
        }}
      >
        !
      </div>
    );
  }

  return (
    <div
      data-testid="notification"
      data-urgency={urgency}
      style={{
        padding: "8px 12px",
        borderRadius: 8,
        background:
          urgency === "high"
            ? "rgba(225, 29, 72, 0.15)"
            : "rgba(255,255,255,0.9)",
        border:
          urgency === "high" ? "2px solid #e11d48" : "1px solid rgba(0,0,0,0.1)",
        marginBottom: 8,
        fontSize: 13,
      }}
    >
      {text}
      <button
        onClick={onDismiss}
        style={{ marginLeft: 8, fontSize: 11, opacity: 0.6 }}
      >
        dismiss
      </button>
    </div>
  );
}
