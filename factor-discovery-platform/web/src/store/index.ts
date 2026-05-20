import { create } from "zustand";

interface AppState {
  activeDataset: string | null;
  activeExperiment: string | null;
  setActiveDataset: (id: string | null) => void;
  setActiveExperiment: (id: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  activeDataset: null,
  activeExperiment: null,
  setActiveDataset: (id) => set({ activeDataset: id }),
  setActiveExperiment: (id) => set({ activeExperiment: id }),
}));
