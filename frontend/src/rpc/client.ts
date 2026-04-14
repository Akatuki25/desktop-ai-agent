/**
 * Thin JSON-RPC 2.0 over WebSocket client for the agent daemon.
 *
 * The browser WebSocket API cannot set arbitrary headers, so the bearer
 * token is passed via the `Sec-WebSocket-Protocol` subprotocol channel on
 * the wire. The daemon accepts either mechanism.
 *
 * For Phase 0 the daemon only speaks echo — this file is just enough to
 * wire the UI through end-to-end.
 */

export type RpcStatus = "connecting" | "open" | "closed";

export interface RpcEvent {
  method: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  params: any;
}

export interface RpcClient {
  send(method: string, params: unknown): void;
  close(): void;
}

export interface RpcClientOptions {
  url: string;
  token: string;
  onEvent: (evt: RpcEvent) => void;
  onStatus?: (s: RpcStatus) => void;
}

export function createRpcClient(opts: RpcClientOptions): RpcClient {
  const ws = new WebSocket(opts.url, [`bearer.${opts.token}`]);
  let nextId = 1;

  ws.onopen = () => opts.onStatus?.("open");
  ws.onclose = () => opts.onStatus?.("closed");
  ws.onerror = () => opts.onStatus?.("closed");
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data as string);
      if (typeof msg.method === "string") {
        opts.onEvent({ method: msg.method, params: msg.params });
      }
    } catch {
      // ignore malformed frame
    }
  };

  return {
    send(method, params) {
      if (ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ jsonrpc: "2.0", id: nextId++, method, params }));
    },
    close() {
      ws.close();
    },
  };
}
