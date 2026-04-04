import React from "react";
import { useNavigate } from "react-router";
import { useTranslation } from "react-i18next";
import { BrandButton } from "../../settings/brand-button";
import { useCreateConversation } from "#/hooks/mutation/use-create-conversation";
import { useIsCreatingConversation } from "#/hooks/use-is-creating-conversation";
// >>> CUSTOM: HiClaw <<<
import { useRemoteWorkerStore } from "#/stores/remote-worker-store";
import { MachineProvisioningPanel } from "#/components/features/custom/machine-provisioning-panel";
import axios from "axios";
// >>> END CUSTOM <<<

// >>> CUSTOM: HiClaw — workspace autocomplete component <<<
function WorkspaceInput({
  value, onChange, config, workerManagerUrl, inputCls,
}: {
  value: string;
  onChange: (v: string) => void;
  config: { host: string; port: number; username: string; password: string };
  workerManagerUrl: string;
  inputCls: string;
}) {
  const [suggestions, setSuggestions] = React.useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const wrapperRef = React.useRef<HTMLDivElement>(null);

  const fetchDirs = React.useCallback(async () => {
    if (!config.host || !config.username || !config.password) {
      setError("Please fill in Host, Username and Password first");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp = await axios.post(`${workerManagerUrl}/api/list-dirs`, {
        host: config.host, port: config.port,
        username: config.username, password: config.password,
        mode: "host", template: "openhands", workspace: "",
      }, { timeout: 15000 });
      const dirs = resp.data?.dirs || [];
      setSuggestions(dirs);
      if (dirs.length === 0) setError("No directories found on remote machine");
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? e.response?.status === 401 || e.response?.status === 403
          ? "Authentication failed — check username/password"
          : e.code === "ECONNABORTED"
            ? "Connection timeout — check host IP and network"
            : e.response?.data?.detail || e.message || "Connection failed"
        : "Connection failed — check host IP and port";
      setError(msg);
      setSuggestions([]);
    } finally { setLoading(false); }
  }, [config.host, config.port, config.username, config.password, workerManagerUrl]);

  React.useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node))
        setShowSuggestions(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = value
    ? suggestions.filter((s) => s.toLowerCase().includes(value.toLowerCase()))
    : suggestions;

  const handleFocus = () => {
    if (suggestions.length === 0 && config.host && config.password) fetchDirs();
    setShowSuggestions(true);
  };

  const handleSelect = (dir: string) => {
    const now = new Date();
    const ts = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}_${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}`;
    onChange(`${dir}/workspace_${ts}`);
    setShowSuggestions(false);
  };

  return (
    <div className="flex-1" ref={wrapperRef}>
      <label className="block text-xs text-neutral-500 mb-1">Workspace</label>
      <div className="relative">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={handleFocus}
          placeholder="/home/user/project"
          className={inputCls}
        />
        {showSuggestions && (filtered.length > 0 || loading || error) && (
          <div className="absolute left-0 right-0 bottom-full mb-1 max-h-40 overflow-y-auto bg-neutral-800 border border-neutral-600 rounded-lg shadow-lg z-50">
            {loading && <div className="px-3 py-2 text-xs text-neutral-500">Connecting to {config.host}...</div>}
            {error && !loading && (
              <div className="px-3 py-2 text-xs text-red-400 flex items-center gap-1.5">
                <span className="shrink-0">&#9888;</span>
                <span>{error}</span>
              </div>
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
    </div>
  );
}
// >>> END CUSTOM <<<

export function CreateConversationButton() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // >>> CUSTOM: HiClaw <<<
  const [showModal, setShowModal] = React.useState(false);
  const {
    enabled, config, workerManagerUrl,
    machineId, machineStatus, proxyUrl, tunnelPort,
    setEnabled, setConfig, setMachineId, setMachineStatus,
    addProvisionEvent, setProxyUrl, setTunnelPort, setError, reset,
  } = useRemoteWorkerStore();
  // >>> END CUSTOM <<<

  const {
    mutate: createConversation,
    isPending,
    isSuccess,
  } = useCreateConversation();
  const isCreatingConversationElsewhere = useIsCreatingConversation();

  const isCreatingConversation =
    isPending || isSuccess || isCreatingConversationElsewhere;

  // >>> CUSTOM: HiClaw — subscribe to SSE events via fetch (no auto-reconnect) <<<
  const abortRef = React.useRef<AbortController | null>(null);

  React.useEffect(() => {
    if (!machineId || machineStatus === "ready" || machineStatus === "error") return;

    const controller = new AbortController();
    abortRef.current = controller;

    (async () => {
      try {
        const resp = await fetch(
          `${workerManagerUrl}/api/machines/${machineId}/events`,
          { signal: controller.signal },
        );
        if (!resp.body) return;
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // Parse SSE lines
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const json = line.slice(6).trim();
            if (!json || json === "{}") continue;
            try {
              const data = JSON.parse(json);
              if (data.step) {
                addProvisionEvent(data);
                if (data.step === "ssh_connect" && data.status === "completed") setMachineStatus("provisioning");
                if (data.step === "start_agent_server" && data.status === "started") setMachineStatus("starting");
              }
              if (data.status === "ready" && data.proxy_url) {
                setMachineStatus("ready");
                setProxyUrl(data.proxy_url);
                setTunnelPort(data.tunnel_port || null);
                reader.cancel();
                return;
              }
              if (data.status === "error" && data.id) {
                setMachineStatus("error");
                setError(data.error || "Unknown error");
                reader.cancel();
                return;
              }
            } catch { /* ignore parse errors */ }
          }
        }
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        // SSE stream ended/broken — fall back to polling until ready/error
        const pollStart = Date.now();
        const maxPollMs = 10 * 60 * 1000; // 10 minutes max
        while (Date.now() - pollStart < maxPollMs) {
          try {
            const resp = await axios.get(`${workerManagerUrl}/api/machines/${machineId}`, { timeout: 5000 });
            const st = resp.data?.status;
            if (st === "ready") {
              setMachineStatus("ready");
              setProxyUrl(resp.data.proxy_url || null);
              setTunnelPort(resp.data.tunnel_port || null);
              return;
            }
            if (st === "error") {
              setMachineStatus("error");
              setError(resp.data.error || "Unknown error");
              return;
            }
            // Still provisioning �� update status text and keep polling
            const steps = resp.data?.provision_steps;
            if (Array.isArray(steps) && steps.length > 0) {
              const latest = steps[steps.length - 1];
              addProvisionEvent({
                step: latest.step || "provisioning",
                status: latest.status || "started",
                detail: latest.detail || "Working...",
                timestamp: latest.timestamp || new Date().toISOString(),
              });
            }
          } catch { /* ignore poll error, retry */ }
          await new Promise((r) => setTimeout(r, 3000));
        }
        // Timeout
        setMachineStatus("error");
        setError("Provisioning timed out (10 min). Refresh and try again.");
      }
    })();

    return () => { controller.abort(); };
  }, [machineId, machineStatus]);

  // Auto-create conversation when machine becomes ready (only if modal is open)
  React.useEffect(() => {
    if (showModal && enabled && machineStatus === "ready" && proxyUrl && !isPending && !isSuccess) {
      doCreateConversation();
    }
  }, [machineStatus, proxyUrl, showModal]);
  // >>> END CUSTOM <<<

  const doCreateConversation = () => {
    setShowModal(false);
    createConversation(
      {},
      {
        onSuccess: (data) => navigate(`/conversations/${data.conversation_id}`),
      },
    );
  };

  const handleClick = () => {
    // Remote machine is always required — show connection modal
    reset();
    setShowModal(true);
  };

  const handleStartRemote = async () => {
    if (!config.host) return;
    setError(null);
    try {
      const resp = await axios.post(`${workerManagerUrl}/api/machines/connect`, {
        host: config.host,
        port: config.port,
        username: config.username,
        password: config.password,
        mode: config.mode,
        template: config.template,
        workspace: config.workspace,
      }, { timeout: 60000 });

      if (resp.data.status === "ready") {
        // Machine already provisioned — skip progress panel, go straight to conversation
        setProxyUrl(resp.data.proxy_url);
        setTunnelPort(resp.data.tunnel_port);
        setMachineStatus("ready");
        // doCreateConversation will be called by the useEffect
        return;
      }
      // Machine is provisioning — show progress panel
      setMachineId(resp.data.id);
      setMachineStatus(resp.data.status);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setMachineStatus("error");
      setError(`Failed to connect: ${msg}`);
    }
  };

  const inputCls =
    "w-full px-2.5 py-2 bg-neutral-900 border border-neutral-600 rounded text-neutral-200 text-sm focus:border-blue-500 focus:outline-none";

  const isProvisioning = machineStatus && !["ready", "error"].includes(machineStatus);

  return (
    <>
      <BrandButton
        testId="launch-new-conversation-button"
        variant="primary"
        type="button"
        onClick={handleClick}
        isDisabled={isCreatingConversation}
        className="w-auto absolute bottom-5 left-5 right-5 font-semibold"
      >
        {!isCreatingConversation && t("COMMON$NEW_CONVERSATION")}
        {isCreatingConversation && t("HOME$LOADING")}
      </BrandButton>

      {/* >>> CUSTOM: HiClaw — Remote connection modal <<< */}
      {showModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={(e) => {
            if (e.target === e.currentTarget && !isProvisioning) setShowModal(false);
          }}
        >
          <div className="bg-neutral-800 border border-neutral-600 rounded-xl p-6 w-[440px] max-w-[90vw] shadow-2xl">
            <h3 className="text-lg font-semibold text-neutral-100 mb-4">
              Connect to Remote Machine
            </h3>

            {!machineId && (
              <>
                <div className="flex flex-col gap-3 mb-4">
                  <div className="flex gap-2">
                    <div className="flex-1">
                      <label className="block text-xs text-neutral-500 mb-1">Host</label>
                      <input type="text" value={config.host}
                        onChange={(e) => setConfig({ host: e.target.value })}
                        placeholder="192.168.1.100" className={inputCls} />
                    </div>
                    <div className="w-20">
                      <label className="block text-xs text-neutral-500 mb-1">Port</label>
                      <input type="number" value={config.port}
                        onChange={(e) => setConfig({ port: parseInt(e.target.value) || 22 })}
                        className={inputCls} />
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <div className="flex-1">
                      <label className="block text-xs text-neutral-500 mb-1">Username</label>
                      <input type="text" value={config.username}
                        onChange={(e) => setConfig({ username: e.target.value })}
                        className={inputCls} />
                    </div>
                    <div className="flex-1">
                      <label className="block text-xs text-neutral-500 mb-1">Password</label>
                      <input type="password" value={config.password}
                        onChange={(e) => setConfig({ password: e.target.value })}
                        className={inputCls} />
                    </div>
                  </div>
                  {/* >>> CUSTOM: HiClaw — workspace autocomplete <<< */}
                  <WorkspaceInput
                    value={config.workspace}
                    onChange={(v: string) => setConfig({ workspace: v })}
                    config={config}
                    workerManagerUrl={workerManagerUrl}
                    inputCls={inputCls}
                  />
                  {/* >>> END CUSTOM <<< */}
                </div>
                <div className="flex justify-end gap-3">
                  <button type="button" onClick={() => setShowModal(false)}
                    className="px-4 py-2 text-sm text-neutral-400 hover:text-neutral-200 rounded">
                    Cancel
                  </button>
                  <button type="button" onClick={handleStartRemote}
                    disabled={!config.host}
                    className="px-5 py-2 text-sm font-semibold bg-blue-600 hover:bg-blue-500 disabled:bg-neutral-600 disabled:text-neutral-400 text-white rounded-lg transition-colors">
                    Connect
                  </button>
                </div>
              </>
            )}

            {machineId && (
              <>
                <MachineProvisioningPanel />
                <div className="flex justify-end gap-3 mt-4">
                  {machineStatus === "error" && (
                    <>
                      <button type="button" onClick={() => { reset(); }}
                        className="px-4 py-2 text-sm text-neutral-400 hover:text-neutral-200 rounded">
                        Back
                      </button>
                      <button type="button" onClick={handleStartRemote}
                        className="px-5 py-2 text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white rounded-lg">
                        Retry
                      </button>
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
      {/* >>> END CUSTOM <<< */}
    </>
  );
}
