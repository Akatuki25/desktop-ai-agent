import { create } from "zustand";

export type AgentState = "idle" | "thinking" | "talking" | "listening" | "hidden";
export type Emotion = "neutral" | "smile" | "think" | "surprise" | "sad" | "angry";

interface CharacterStore {
  agentState: AgentState;
  emotion: Emotion;
  setAgentState: (s: AgentState) => void;
  setEmotion: (e: Emotion) => void;
}

export const useCharacterStore = create<CharacterStore>((set) => ({
  agentState: "idle",
  emotion: "neutral",
  setAgentState: (agentState) => set({ agentState }),
  setEmotion: (emotion) => set({ emotion }),
}));
