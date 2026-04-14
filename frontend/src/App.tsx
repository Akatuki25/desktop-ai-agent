import { useEffect, useState } from "react";
import { createRpcClient, type RpcClient } from "./rpc/client";

type Line = { role: "user" | "agent"; text: string };

export function App() {
  const [client, setClient] = useState<RpcClient | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<"connecting" | "open" | "closed">("connecting");

  useEffect(() => {
    // In dev standalone (no Tauri), read URL query for port/token.
    const params = new URLSearchParams(window.location.search);
    const port = Number(params.get("port") ?? "0");
    const token = params.get("token") ?? "";
    if (!port || !token) {
      setStatus("closed");
      return;
    }
    const c = createRpcClient({
      url: `ws://127.0.0.1:${port}/ws`,
      token,
      onEvent: (evt) => {
        if (evt.method === "agent.say") {
          setLines((prev) => [...prev, { role: "agent", text: evt.params.text }]);
        }
      },
      onStatus: setStatus,
    });
    setClient(c);
    return () => c.close();
  }, []);

  const send = () => {
    if (!draft.trim() || !client) return;
    setLines((prev) => [...prev, { role: "user", text: draft }]);
    client.send("session.send_text", { text: draft });
    setDraft("");
  };

  return (
    <div data-testid="app" style={{ fontFamily: "system-ui", padding: 16 }}>
      <header>
        <h1 style={{ fontSize: 16 }}>desktop-ai-agent</h1>
        <p data-testid="status">status: {status}</p>
      </header>
      <ul data-testid="lines" style={{ listStyle: "none", padding: 0 }}>
        {lines.map((l, i) => (
          <li key={i}>
            <strong>{l.role}:</strong> {l.text}
          </li>
        ))}
      </ul>
      <div>
        <input
          aria-label="message"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button onClick={send}>send</button>
      </div>
    </div>
  );
}
