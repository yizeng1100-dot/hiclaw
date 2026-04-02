// >>> CUSTOM: HiClaw — remote worker connection panel <<<
import React from "react";
import { useRemoteWorkerStore } from "#/stores/remote-worker-store";

/**
 * Workspace path input with autocomplete from remote machine.
 * Fetches available directories via Worker Manager's list-dirs API.
 * Appends a datetime-named subdirectory to the selected path.
 */
function WorkspaceAutocomplete({
  value,
  onChange,
  config,
}: {
  value: string;
  onChange: (v: string) => void;
  config: { host: string; port: number; username: string; password: string };
}) {
  const [suggestions, setSuggestions] = React.useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const wrapperRef = React.useRef<HTMLDivElement>(null);

  // Fetch directories when input is focused and we have host info
  const fetchDirs = React.useCallback(async () => {
    if (!config.host || !config.username) return;
    setLoading(true);
    try {
      const resp = await fetch("/runtime/manager/api/list-dirs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host: config.host,
          port: config.port,
          username: config.username,
          password: config.password,
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setSuggestions(data.dirs || []);
      }
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [config.host, config.port, config.username, config.password]);

  // Close on click outside
  React.useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = value
    ? suggestions.filter((s) => s.toLowerCase().includes(value.toLowerCase()))
    : suggestions;

  const handleFocus = () => {
    if (suggestions.length === 0) fetchDirs();
    setShowSuggestions(true);
  };

  const handleSelect = (dir: string) => {
    // Append datetime workspace name
    const now = new Date();
    const ts = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}_${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}`;
    onChange(`${dir}/workspace_${ts}`);
    setShowSuggestions(false);
  };

  return (
    <div className="relative flex-1" ref={wrapperRef}>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={handleFocus}
        placeholder="Workspace path (type to search)"
        className="w-full px-3 py-1.5 bg-tertiary border border-neutral-600 rounded-lg text-sm text-content placeholder-neutral-500 focus:outline-none focus:border-blue-500 transition"
      />
      {showSuggestions && (filtered.length > 0 || loading) && (
        <div className="absolute bottom-full left-0 right-0 mb-1 max-h-48 overflow-y-auto bg-neutral-800 border border-neutral-600 rounded-lg shadow-lg z-50">
          {loading && (
            <div className="px-3 py-2 text-xs text-neutral-500">Loading directories...</div>
          )}
          {filtered.map((dir) => (
            <button
              key={dir}
              type="button"
              onClick={() => handleSelect(dir)}
              className="w-full text-left px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-700 transition truncate"
            >
              {dir}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function RemoteWorkerPanel() {
  const { enabled, config, setEnabled, setConfig } = useRemoteWorkerStore();

  return (
    <div className="flex flex-col gap-2">
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          className="accent-blue-500 w-3.5 h-3.5"
        />
        <span className="text-xs font-medium text-neutral-300">Remote Machine</span>
      </label>

      {enabled && (
        <div className="flex flex-col gap-2 p-3 bg-tertiary rounded-lg border border-neutral-700">
          {/* Row 1: Host + Port */}
          <div className="flex gap-2">
            <input
              type="text"
              value={config.host}
              onChange={(e) => setConfig({ host: e.target.value })}
              placeholder="Host IP"
              className="flex-1 px-3 py-1.5 bg-tertiary border border-neutral-600 rounded-lg text-sm text-content placeholder-neutral-500 focus:outline-none focus:border-blue-500 transition"
            />
            <input
              type="number"
              value={config.port}
              onChange={(e) => setConfig({ port: parseInt(e.target.value) || 22 })}
              placeholder="Port"
              className="w-16 px-3 py-1.5 bg-tertiary border border-neutral-600 rounded-lg text-sm text-content placeholder-neutral-500 focus:outline-none focus:border-blue-500 transition"
            />
          </div>
          {/* Row 2: User + Password */}
          <div className="flex gap-2">
            <input
              type="text"
              value={config.username}
              onChange={(e) => setConfig({ username: e.target.value })}
              placeholder="Username"
              className="flex-1 px-3 py-1.5 bg-tertiary border border-neutral-600 rounded-lg text-sm text-content placeholder-neutral-500 focus:outline-none focus:border-blue-500 transition"
            />
            <input
              type="password"
              value={config.password}
              onChange={(e) => setConfig({ password: e.target.value })}
              placeholder="Password"
              className="flex-1 px-3 py-1.5 bg-tertiary border border-neutral-600 rounded-lg text-sm text-content placeholder-neutral-500 focus:outline-none focus:border-blue-500 transition"
            />
          </div>
          {/* Row 3: Mode + Workspace with autocomplete */}
          <div className="flex gap-2">
            <select
              value={config.mode}
              onChange={(e) => setConfig({ mode: e.target.value as "docker" | "host" })}
              className="w-24 px-2 py-1.5 bg-tertiary border border-neutral-600 rounded-lg text-sm text-content focus:outline-none focus:border-blue-500 transition"
            >
              <option value="host">Host</option>
              <option value="docker">Docker</option>
            </select>
            <WorkspaceAutocomplete
              value={config.workspace}
              onChange={(v) => setConfig({ workspace: v })}
              config={config}
            />
          </div>
        </div>
      )}
    </div>
  );
}
// >>> END CUSTOM <<<
