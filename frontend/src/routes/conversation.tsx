import React from "react";
import { useNavigate } from "react-router";
import { useTranslation } from "react-i18next";
import axios from "axios";

import { useConversationId } from "#/hooks/use-conversation-id";
import { useCommandStore } from "#/stores/command-store";
import { useConversationStore } from "#/stores/conversation-store";
import { useAgentStore } from "#/stores/agent-store";
import { AgentState } from "#/types/agent-state";

import { useBatchFeedback } from "#/hooks/query/use-batch-feedback";
import { EventHandler } from "../wrapper/event-handler";
import { useConversationConfig } from "#/hooks/query/use-conversation-config";

import { useActiveConversation } from "#/hooks/query/use-active-conversation";
import { useTaskPolling } from "#/hooks/query/use-task-polling";

import { displayErrorToast } from "#/utils/custom-toast-handlers";
import { useIsAuthed } from "#/hooks/query/use-is-authed";
import { ConversationSubscriptionsProvider } from "#/context/conversation-subscriptions-provider";

import { ConversationMain } from "#/components/features/conversation/conversation-main/conversation-main";
import { ConversationNameWithStatus } from "#/components/features/conversation/conversation-name-with-status";

import { ConversationTabs } from "#/components/features/conversation/conversation-tabs/conversation-tabs";
import { WebSocketProviderWrapper } from "#/contexts/websocket-provider-wrapper";
import { useErrorMessageStore } from "#/stores/error-message-store";
import { I18nKey } from "#/i18n/declaration";
import { useEventStore } from "#/stores/use-event-store";
// >>> CUSTOM: HiClaw <<<
import { useRemoteWorkerStore } from "#/stores/remote-worker-store";
// >>> END CUSTOM <<<

function AppContent() {
  useConversationConfig();
  const { t } = useTranslation();
  const { conversationId } = useConversationId();
  const clearEvents = useEventStore((state) => state.clearEvents);

  // Handle both task IDs (task-{uuid}) and regular conversation IDs
  const { isTask, taskStatus, taskDetail } = useTaskPolling();

  const { data: conversation, isFetched, refetch } = useActiveConversation();
  const { data: isAuthed } = useIsAuthed();
  const { resetConversationState } = useConversationStore();
  const navigate = useNavigate();
  const clearTerminal = useCommandStore((state) => state.clearTerminal);
  const setCurrentAgentState = useAgentStore(
    (state) => state.setCurrentAgentState,
  );
  const removeErrorMessage = useErrorMessageStore(
    (state) => state.removeErrorMessage,
  );

  // >>> CUSTOM: HiClaw — reconnect for remote conversations <<<
  const [needsReconnect, setNeedsReconnect] = React.useState(false);
  const [reconnectPassword, setReconnectPassword] = React.useState("");
  const [reconnectLoading, setReconnectLoading] = React.useState(false);
  const [reconnectError, setReconnectError] = React.useState<string | null>(null);
  const reconnectDoneRef = React.useRef(false); // prevents re-trigger after successful reconnect
  const { config, workerManagerUrl } = useRemoteWorkerStore();

  const handleReconnect = async () => {
    if (!reconnectPassword) return;
    setReconnectLoading(true);
    setReconnectError(null);
    try {
      await axios.post(`${workerManagerUrl}/api/machines/connect`, {
        host: config.host,
        port: config.port,
        username: config.username,
        password: reconnectPassword,
        mode: "host",
        template: "openhands",
        workspace: config.workspace,
      }, { timeout: 60000 });
      useRemoteWorkerStore.getState().setConfig({ password: reconnectPassword });
      reconnectDoneRef.current = true; // block useEffect from re-triggering
      setNeedsReconnect(false);
      // Refetch conversation with new tunnel
      setTimeout(() => refetch(), 1000);
    } catch (err) {
      setReconnectError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setReconnectLoading(false);
    }
  };
  // >>> END CUSTOM <<<

  // Fetch batch feedback data when conversation is loaded
  useBatchFeedback();

  // 1. Cleanup Effect - runs when navigating to a different conversation
  React.useEffect(() => {
    clearTerminal();
    resetConversationState();
    setCurrentAgentState(AgentState.LOADING);
    removeErrorMessage();
    clearEvents();
  }, [
    conversationId,
    clearTerminal,
    resetConversationState,
    setCurrentAgentState,
    removeErrorMessage,
    clearEvents,
  ]);

  // 2. Task Error Display Effect
  // >>> CUSTOM: HiClaw — suppress for remote sandboxes (they recover via Worker Manager) <<<
  const isRemoteConversation = conversation?.sandbox_id?.startsWith("remote-");
  React.useEffect(() => {
    if (isTask && taskStatus === "ERROR" && !isRemoteConversation) {
      displayErrorToast(
        taskDetail || t(I18nKey.CONVERSATION$FAILED_TO_START_FROM_TASK),
      );
    }
  }, [isTask, taskStatus, taskDetail, t, isRemoteConversation]);
  // >>> END CUSTOM <<<

  // 3. Handle conversation not found
  // NOTE: Resuming STOPPED conversations is handled by useSandboxRecovery in WebSocketProviderWrapper
  React.useEffect(() => {
    // Wait for data to be fetched
    if (!isFetched || !isAuthed) return;
    // After a successful reconnect, don't re-trigger until conversation has url
    if (reconnectDoneRef.current) {
      if (conversation?.url) {
        reconnectDoneRef.current = false; // reset for future disconnects
      }
      return;
    }

    if (!conversation) {
      // >>> CUSTOM: HiClaw — check if this might be a remote conversation needing reconnect <<<
      if (config.host) {
        setNeedsReconnect(true);
        setReconnectPassword(config.password || "");
      } else {
        displayErrorToast(t(I18nKey.CONVERSATION$NOT_EXIST_OR_NO_PERMISSION));
        navigate("/");
      }
    } else if (
      // Remote conversation with no active tunnel (STOPPED/PAUSED after restart)
      conversation.sandbox_id?.startsWith("remote-") &&
      (conversation.status === "STOPPED" || conversation.runtime_status === null) &&
      !conversation.url &&
      config.host
    ) {
      setNeedsReconnect(true);
      setReconnectPassword(config.password || "");
      // >>> END CUSTOM <<<
    } else {
      setNeedsReconnect(false);
    }
  }, [conversation, isFetched, isAuthed, navigate, t, config.host]);
  // Note: config.password intentionally excluded from deps — including it causes
  // the reconnect modal to re-trigger after password submission (setConfig updates
  // password → deps change → effect re-runs → conversation not yet refetched →
  // needsReconnect set to true again → modal loop)

  // >>> CUSTOM: HiClaw — reconnect UI <<<
  if (needsReconnect) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="bg-neutral-800 border border-neutral-600 rounded-xl p-6 w-[380px] shadow-2xl">
          <h3 className="text-base font-semibold text-neutral-100 mb-2">Reconnect Required</h3>
          <p className="text-xs text-neutral-400 mb-3">
            SSH connection to {config.username}@{config.host} needs to be re-established.
          </p>
          <input
            type="password"
            value={reconnectPassword}
            onChange={(e) => setReconnectPassword(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleReconnect(); }}
            placeholder="SSH Password"
            autoFocus
            className="w-full px-3 py-2 bg-neutral-900 border border-neutral-600 rounded text-neutral-200 text-sm focus:border-blue-500 focus:outline-none mb-3"
          />
          {reconnectError && (
            <p className="text-xs text-red-400 mb-3">{reconnectError}</p>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => navigate("/")}
              className="px-4 py-2 text-sm text-neutral-400 hover:text-neutral-200 rounded"
            >
              Back
            </button>
            <button
              type="button"
              onClick={handleReconnect}
              disabled={!reconnectPassword || reconnectLoading}
              className="px-5 py-2 text-sm font-semibold bg-blue-600 hover:bg-blue-500 disabled:bg-neutral-600 disabled:text-neutral-400 text-white rounded-lg"
            >
              {reconnectLoading ? "Connecting..." : "Connect"}
            </button>
          </div>
        </div>
      </div>
    );
  }
  // >>> END CUSTOM <<<

  const isV0Conversation = conversation?.conversation_version === "V0";

  const content = (
    <ConversationSubscriptionsProvider>
      <EventHandler>
        <div
          data-testid="app-route"
          className="p-3 md:p-0 flex flex-col h-full gap-3"
        >
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4.5 pt-2 lg:pt-0">
            <ConversationNameWithStatus />
            <ConversationTabs />
          </div>

          <ConversationMain />
        </div>
      </EventHandler>
    </ConversationSubscriptionsProvider>
  );

  // Render WebSocket provider immediately to avoid mount/remount cycles
  // The providers internally handle waiting for conversation data to be ready
  return (
    <WebSocketProviderWrapper
      version={isV0Conversation ? 0 : 1}
      conversationId={conversationId}
    >
      {content}
    </WebSocketProviderWrapper>
  );
}

function App() {
  return <AppContent />;
}

export default App;
