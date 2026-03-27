// >>> CUSTOM: HiClaw — remote worker connection panel <<<
import React from "react";
import { useRemoteWorkerStore } from "#/stores/remote-worker-store";

export function RemoteWorkerPanel() {
  const { enabled, config, setEnabled, setConfig } = useRemoteWorkerStore();

  const inputCls =
    "w-full px-2 py-1 bg-neutral-900 border border-neutral-600 rounded text-neutral-200 text-xs focus:border-blue-500 focus:outline-none";

  return (
    <div className="flex flex-col gap-1.5">
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          className="accent-blue-500"
        />
        <span className="text-xs text-neutral-300">Remote Machine</span>
      </label>

      {enabled && (
        <div className="flex flex-col gap-1.5 p-2 bg-neutral-800 rounded border border-neutral-700 text-xs">
          {/* Row 1: Host + Port */}
          <div className="flex gap-1.5">
            <input
              type="text"
              value={config.host}
              onChange={(e) => setConfig({ host: e.target.value })}
              placeholder="Host IP"
              className={`${inputCls} flex-1`}
            />
            <input
              type="number"
              value={config.port}
              onChange={(e) => setConfig({ port: parseInt(e.target.value) || 22 })}
              placeholder="Port"
              className={`${inputCls} w-14`}
            />
          </div>
          {/* Row 2: User + Password */}
          <div className="flex gap-1.5">
            <input
              type="text"
              value={config.username}
              onChange={(e) => setConfig({ username: e.target.value })}
              placeholder="Username"
              className={`${inputCls} flex-1`}
            />
            <input
              type="password"
              value={config.password}
              onChange={(e) => setConfig({ password: e.target.value })}
              placeholder="Password"
              className={`${inputCls} flex-1`}
            />
          </div>
          {/* Row 3: Mode + Workspace */}
          <div className="flex gap-1.5">
            <select
              value={config.mode}
              onChange={(e) => setConfig({ mode: e.target.value as "docker" | "host" })}
              className={`${inputCls} w-24`}
            >
              <option value="host">Host</option>
              <option value="docker">Docker</option>
            </select>
            <input
              type="text"
              value={config.workspace}
              onChange={(e) => setConfig({ workspace: e.target.value })}
              placeholder="Workspace path"
              className={`${inputCls} flex-1`}
            />
          </div>
        </div>
      )}
    </div>
  );
}
// >>> END CUSTOM <<<
