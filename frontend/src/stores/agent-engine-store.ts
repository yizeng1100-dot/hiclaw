// >>> CUSTOM: HiClaw <<<
import { create } from "zustand";

export type AgentEngine = "openhands_sdk" | "claude_sdk";

interface AgentEngineStore {
  engine: AgentEngine;
  setEngine: (engine: AgentEngine) => void;
}

export const useAgentEngineStore = create<AgentEngineStore>((set) => ({
  engine: "openhands_sdk",
  setEngine: (engine) => set({ engine }),
}));
// >>> END CUSTOM <<<
