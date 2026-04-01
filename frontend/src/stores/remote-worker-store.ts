// >>> CUSTOM: HiClaw — remote machine store <<<
import { create } from "zustand";

export interface RemoteMachineConfig {
  host: string;
  port: number;
  username: string;
  password: string;
  mode: "docker" | "host";
  workspace: string;
  template: string;
}

export interface ProvisionEvent {
  step: string;
  status: "started" | "completed" | "skipped" | "failed";
  detail: string;
  timestamp: string;
}

export type MachineStatus =
  | "connecting"
  | "provisioning"
  | "starting"
  | "ready"
  | "error"
  | "disconnected"
  | null;

// Persist SSH credentials to localStorage (except password which stays in memory)
const STORAGE_KEY = "hiclaw-remote-config";

function loadSavedConfig(): Partial<RemoteMachineConfig> {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return JSON.parse(saved);
  } catch { /* ignore */ }
  return {};
}

function saveConfig(config: RemoteMachineConfig) {
  try {
    // Save everything including password for convenience
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      host: config.host,
      port: config.port,
      username: config.username,
      password: config.password,
      workspace: config.workspace,
    }));
  } catch { /* ignore */ }
}

const savedConfig = loadSavedConfig();

interface RemoteMachineStore {
  enabled: boolean;
  config: RemoteMachineConfig;
  workerManagerUrl: string;

  // Machine provisioning state
  machineId: string | null;
  machineStatus: MachineStatus;
  provisionEvents: ProvisionEvent[];
  proxyUrl: string | null;
  tunnelPort: number | null;
  error: string | null;

  // Actions
  setEnabled: (enabled: boolean) => void;
  setConfig: (config: Partial<RemoteMachineConfig>) => void;
  setWorkerManagerUrl: (url: string) => void;
  setMachineId: (id: string | null) => void;
  setMachineStatus: (status: MachineStatus) => void;
  addProvisionEvent: (event: ProvisionEvent) => void;
  setProxyUrl: (url: string | null) => void;
  setTunnelPort: (port: number | null) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

export const useRemoteWorkerStore = create<RemoteMachineStore>((set) => ({
  enabled: true,
  config: {
    host: savedConfig.host || "",
    port: savedConfig.port || 22,
    username: savedConfig.username || "root",
    password: savedConfig.password || "",
    mode: "host",
    workspace: savedConfig.workspace || "",
    template: "openhands",
  },
  // Route through app-server proxy so browser doesn't need direct access to 9090
  workerManagerUrl: "/runtime/manager",
  machineId: null,
  machineStatus: null,
  provisionEvents: [],
  proxyUrl: null,
  tunnelPort: null,
  error: null,

  setEnabled: (enabled) => set({ enabled }),
  setConfig: (partial) =>
    set((state) => {
      const newConfig = { ...state.config, ...partial };
      saveConfig(newConfig);
      return { config: newConfig };
    }),
  setWorkerManagerUrl: (url) => set({ workerManagerUrl: url }),
  setMachineId: (id) => set({ machineId: id }),
  setMachineStatus: (status) => set({ machineStatus: status }),
  addProvisionEvent: (event) =>
    set((state) => ({ provisionEvents: [...state.provisionEvents, event] })),
  setProxyUrl: (url) => set({ proxyUrl: url }),
  setTunnelPort: (port) => set({ tunnelPort: port }),
  setError: (error) => set({ error }),
  reset: () =>
    set({
      machineId: null,
      machineStatus: null,
      provisionEvents: [],
      proxyUrl: null,
      tunnelPort: null,
      error: null,
    }),
}));
// >>> END CUSTOM <<<
