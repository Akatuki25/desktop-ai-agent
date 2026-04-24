import { create } from "zustand";
import type { Emotion } from "./characterStore";

export type MessageRole = "user" | "agent";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
  thinking?: string;
  emotion?: Emotion;
  pending: boolean;
}

interface ChatStore {
  messages: ChatMessage[];

  /** Append a completed user message. */
  appendUser: (text: string) => void;

  /**
   * Apply a streaming agent.say delta. If the previous message is a
   * pending agent message, extend it; otherwise start a new pending
   * agent message. is_thinking deltas go into the thinking buffer
   * rather than the main text.
   */
  applyAgentDelta: (args: {
    text: string;
    emotion: Emotion;
    isThinking: boolean;
  }) => void;

  /** Mark the current pending agent message as final (agent.say_end). */
  finalizeAgent: () => void;

  reset: () => void;
}

let messageSeq = 0;
const nextId = (): string => `m${++messageSeq}`;

export const useChatStore = create<ChatStore>((set) => ({
  messages: [],

  appendUser: (text) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { id: nextId(), role: "user", text, pending: false },
      ],
    })),

  applyAgentDelta: ({ text, emotion, isThinking }) =>
    set((s) => {
      const last = s.messages[s.messages.length - 1];
      if (last && last.role === "agent" && last.pending) {
        const next: ChatMessage = {
          ...last,
          text: isThinking ? last.text : last.text + text,
          thinking: isThinking ? (last.thinking ?? "") + text : last.thinking,
          emotion,
        };
        return { messages: [...s.messages.slice(0, -1), next] };
      }
      return {
        messages: [
          ...s.messages,
          {
            id: nextId(),
            role: "agent",
            text: isThinking ? "" : text,
            thinking: isThinking ? text : undefined,
            emotion,
            pending: true,
          },
        ],
      };
    }),

  finalizeAgent: () =>
    set((s) => {
      const last = s.messages[s.messages.length - 1];
      if (!last || !last.pending) return s;
      return {
        messages: [...s.messages.slice(0, -1), { ...last, pending: false }],
      };
    }),

  reset: () => set({ messages: [] }),
}));
