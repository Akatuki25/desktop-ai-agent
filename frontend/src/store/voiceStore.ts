import { create } from "zustand";

interface VoiceStore {
  recording: boolean;
  partialText: string;
  setRecording: (recording: boolean) => void;
  setPartialText: (text: string) => void;
  clearPartial: () => void;
}

export const useVoiceStore = create<VoiceStore>((set) => ({
  recording: false,
  partialText: "",
  setRecording: (recording) => set({ recording }),
  setPartialText: (text) => set({ partialText: text }),
  clearPartial: () => set({ partialText: "" }),
}));
