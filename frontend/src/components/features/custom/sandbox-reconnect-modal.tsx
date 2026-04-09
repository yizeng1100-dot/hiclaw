// >>> CUSTOM: HiClaw — sandbox reconnect modal <<<
import React from "react";
import axios from "axios";
import { SANDBOX_ERROR_EVENT, SandboxErrorKind } from "#/utils/sandbox-error-event";
import { useRemoteWorkerStore } from "#/stores/remote-worker-store";

type State =
  | { kind: "hidden" }
  | { kind: "stale"; message: string }       // auto-reconnect triggered, just inform
  | { kind: "need_password"; message: string } // need user to input password
  | { kind: "reconnecting"; message: string }
  | { kind: "error"; message: string };

export function SandboxReconnectModal() {
  const [state, setState] = React.useState<State>({ kind: "hidden" });
  const [password, setPassword] = React.useState("");
  const config = useRemoteWorkerStore((s) => s.config);
  const setConfig = useRemoteWorkerStore((s) => s.setConfig);
  const workerManagerUrl = useRemoteWorkerStore((s) => s.workerManagerUrl);

  // Track if we've shown the stale notice recently to avoid spamming
  const lastShownRef = React.useRef<number>(0);

  React.useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { kind: SandboxErrorKind };
      const now = Date.now();
      if (now - lastShownRef.current < 5000) return; // throttle
      lastShownRef.current = now;

      if (detail.kind === "sandbox_stale") {
        // Auto-reconnect was triggered server-side; show transient notice
        setState({
          kind: "stale",
          message: "沙箱连接异常，正在自动重连…请稍候后重试",
        });
        // Auto-hide after 4s
        setTimeout(() => setState({ kind: "hidden" }), 4000);
      } else if (detail.kind === "sandbox_disconnected") {
        // Tunnel completely gone — need user to reconnect manually
        if (config.password) {
          // We have a saved password, attempt reconnect immediately
          handleReconnect(config.password);
        } else {
          setState({
            kind: "need_password",
            message: "远程沙箱连接已断开。请输入 SSH 密码以重新连接。",
          });
        }
      }
    };
    window.addEventListener(SANDBOX_ERROR_EVENT, handler);
    return () => window.removeEventListener(SANDBOX_ERROR_EVENT, handler);
  }, [config.password]);

  const handleReconnect = async (pwd: string) => {
    setState({ kind: "reconnecting", message: "正在重连远程沙箱…" });
    try {
      const url = workerManagerUrl.startsWith("/")
        ? `${window.location.origin}${workerManagerUrl}`
        : workerManagerUrl;
      await axios.post(`${url}/api/machines/connect`, {
        host: config.host,
        port: config.port,
        username: config.username,
        password: pwd,
        mode: config.mode,
        template: config.template,
        workspace: config.workspace,
      }, { timeout: 60000 });
      // Save the (possibly new) password
      if (pwd !== config.password) {
        setConfig({ password: pwd });
      }
      setState({
        kind: "stale",
        message: "重连成功！请刷新页面查看历史。",
      });
      setTimeout(() => {
        setState({ kind: "hidden" });
        window.location.reload();
      }, 1500);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail || (e as { message?: string }).message || "未知错误";
      setState({ kind: "error", message: `重连失败：${msg}` });
    }
  };

  if (state.kind === "hidden") return null;

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50">
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6 max-w-md w-full mx-4 shadow-2xl">
        <h3 className="text-lg font-semibold text-white mb-2">
          {state.kind === "stale" && "沙箱重连中"}
          {state.kind === "need_password" && "需要重新连接沙箱"}
          {state.kind === "reconnecting" && "正在重连..."}
          {state.kind === "error" && "重连失败"}
        </h3>
        <p className="text-sm text-neutral-300 mb-4">{state.message}</p>

        {(state.kind === "need_password" || state.kind === "error") && (
          <>
            <div className="text-xs text-neutral-500 mb-2">
              主机: <span className="font-mono text-neutral-300">{config.username}@{config.host}</span>
            </div>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && password) handleReconnect(password);
              }}
              placeholder="SSH 密码"
              className="w-full px-3 py-2 bg-neutral-800 border border-neutral-600 rounded text-white text-sm focus:outline-none focus:border-blue-500 mb-3"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setState({ kind: "hidden" })}
                className="px-3 py-1.5 text-xs text-neutral-400 hover:text-white rounded border border-neutral-600"
              >
                取消
              </button>
              <button
                type="button"
                disabled={!password}
                onClick={() => handleReconnect(password)}
                className="px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded disabled:opacity-50"
              >
                重连
              </button>
            </div>
          </>
        )}

        {state.kind === "stale" && (
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => setState({ kind: "hidden" })}
              className="px-3 py-1.5 text-xs text-neutral-400 hover:text-white"
            >
              关闭
            </button>
          </div>
        )}

        {state.kind === "reconnecting" && (
          <div className="flex items-center justify-center py-2">
            <div className="animate-spin h-5 w-5 border-2 border-blue-500 border-t-transparent rounded-full" />
          </div>
        )}
      </div>
    </div>
  );
}
// >>> END CUSTOM <<<
