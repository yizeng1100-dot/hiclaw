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
        // Stream ended without ready/error — poll machine status
        try {
          const resp = await axios.get(`${workerManagerUrl}/api/machines/${machineId}`);
          if (resp.data.status === "ready") {
            setMachineStatus("ready");
            setProxyUrl(resp.data.proxy_url || null);
            setTunnelPort(resp.data.tunnel_port || null);
          } else if (resp.data.status === "error") {
            setMachineStatus("error");
            setError(resp.data.error || "Unknown error");
          }
        } catch { /* ignore */ }
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
    if (enabled) {
      reset();
      setShowModal(true);
    } else {
      doCreateConversation();
    }
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
      }, { timeout: 10000 });

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
                  <div className="flex gap-2">
                    <div className="w-28">
                      <label className="block text-xs text-neutral-500 mb-1">Mode</label>
                      <select value={config.mode}
                        onChange={(e) => setConfig({ mode: e.target.value as "docker" | "host" })}
                        className={inputCls}>
                        <option value="host">Host</option>
                        <option value="docker">Docker</option>
                      </select>
                    </div>
                    <div className="flex-1">
                      <label className="block text-xs text-neutral-500 mb-1">Workspace</label>
                      <input type="text" value={config.workspace}
                        onChange={(e) => setConfig({ workspace: e.target.value })}
                        className={inputCls} />
                    </div>
                  </div>
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
