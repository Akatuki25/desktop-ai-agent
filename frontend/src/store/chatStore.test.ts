import { beforeEach, describe, expect, it } from "vitest";
import { useChatStore } from "./chatStore";

describe("chatStore", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
  });

  it("appends user messages as finalized entries", () => {
    useChatStore.getState().appendUser("hello");
    const msgs = useChatStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].role).toBe("user");
    expect(msgs[0].text).toBe("hello");
    expect(msgs[0].pending).toBe(false);
  });

  it("accumulates agent deltas into a single pending message", () => {
    const store = useChatStore.getState();
    store.applyAgentDelta({ text: "hel", emotion: "neutral", isThinking: false });
    store.applyAgentDelta({ text: "lo", emotion: "smile", isThinking: false });

    const msgs = useChatStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].role).toBe("agent");
    expect(msgs[0].text).toBe("hello");
    expect(msgs[0].emotion).toBe("smile");
    expect(msgs[0].pending).toBe(true);
  });

  it("routes is_thinking deltas into the thinking buffer", () => {
    const store = useChatStore.getState();
    store.applyAgentDelta({ text: "plan", emotion: "think", isThinking: true });
    store.applyAgentDelta({ text: "answer", emotion: "neutral", isThinking: false });

    const msgs = useChatStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].thinking).toBe("plan");
    expect(msgs[0].text).toBe("answer");
  });

  it("finalizes the pending agent message on end", () => {
    const store = useChatStore.getState();
    store.applyAgentDelta({ text: "hi", emotion: "neutral", isThinking: false });
    store.finalizeAgent();

    expect(useChatStore.getState().messages[0].pending).toBe(false);
  });

  it("starts a new agent message after finalize", () => {
    const store = useChatStore.getState();
    store.applyAgentDelta({ text: "one", emotion: "neutral", isThinking: false });
    store.finalizeAgent();
    store.applyAgentDelta({ text: "two", emotion: "neutral", isThinking: false });

    const msgs = useChatStore.getState().messages;
    expect(msgs).toHaveLength(2);
    expect(msgs[0].text).toBe("one");
    expect(msgs[1].text).toBe("two");
    expect(msgs[1].pending).toBe(true);
  });
});
