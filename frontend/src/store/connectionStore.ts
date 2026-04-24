import { create } from "zustand";

export type ConnectionState = "idle" | "connecting" | "open" | "closed";

interface ConnectionStore {
  state: ConnectionState;
  setState: (s: ConnectionState) => void;
}

export const useConnectionStore = create<ConnectionStore>((set) => ({
  state: "idle",
  setState: (state) => set({ state }),
}));
