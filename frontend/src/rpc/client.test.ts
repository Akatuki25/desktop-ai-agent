import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { createRpcClient } from "./client";

type Listener = ((e: unknown) => void) | null;

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;

  url: string;
  protocols: string | string[] | undefined;
  readyState = 0;
  onopen: Listener = null;
  onclose: Listener = null;
  onerror: Listener = null;
  onmessage: Listener = null;
  sent: string[] = [];
  closed = false;

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.closed = true;
    this.readyState = 3;
    this.onclose?.({});
  }

  _open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.({});
  }

  _message(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createRpcClient", () => {
  it("passes the bearer token via the subprotocol channel", () => {
    createRpcClient({
      url: "ws://127.0.0.1:1/ws",
      token: "abc",
      onEvent: () => {},
    });
    const ws = FakeWebSocket.instances[0];
    expect(ws.protocols).toEqual(["bearer.abc"]);
  });

  it("serialises requests as JSON-RPC 2.0 once the socket is open", () => {
    const c = createRpcClient({
      url: "ws://127.0.0.1:1/ws",
      token: "t",
      onEvent: () => {},
    });
    const ws = FakeWebSocket.instances[0];
    ws._open();
    c.send("session.send_text", { text: "hi" });
    expect(ws.sent).toHaveLength(1);
    const parsed = JSON.parse(ws.sent[0]);
    expect(parsed).toMatchObject({
      jsonrpc: "2.0",
      method: "session.send_text",
      params: { text: "hi" },
    });
    expect(typeof parsed.id).toBe("number");
  });

  it("forwards events to onEvent", () => {
    const onEvent = vi.fn();
    createRpcClient({
      url: "ws://127.0.0.1:1/ws",
      token: "t",
      onEvent,
    });
    const ws = FakeWebSocket.instances[0];
    ws._open();
    ws._message({ jsonrpc: "2.0", method: "agent.say", params: { text: "hello" } });
    expect(onEvent).toHaveBeenCalledWith({ method: "agent.say", params: { text: "hello" } });
  });

  it("reports status transitions", () => {
    const onStatus = vi.fn();
    createRpcClient({
      url: "ws://127.0.0.1:1/ws",
      token: "t",
      onEvent: () => {},
      onStatus,
    });
    const ws = FakeWebSocket.instances[0];
    ws._open();
    ws.close();
    expect(onStatus).toHaveBeenCalledWith("open");
    expect(onStatus).toHaveBeenCalledWith("closed");
  });
});
