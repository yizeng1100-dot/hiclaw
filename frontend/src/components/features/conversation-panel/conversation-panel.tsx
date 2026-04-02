import React from "react";
import { NavLink, useParams, useNavigate } from "react-router";
import { useTranslation } from "react-i18next";
import axios from "axios";
import { I18nKey } from "#/i18n/declaration";
import { usePaginatedConversations } from "#/hooks/query/use-paginated-conversations";
import { useStartTasks } from "#/hooks/query/use-start-tasks";
import { useInfiniteScroll } from "#/hooks/use-infinite-scroll";
import { useDeleteConversation } from "#/hooks/mutation/use-delete-conversation";
import { useUnifiedPauseConversationSandbox } from "#/hooks/mutation/use-unified-stop-conversation";
import { ConfirmDeleteModal } from "./confirm-delete-modal";
import { ConfirmStopModal } from "./confirm-stop-modal";
import { LoadingSpinner } from "#/components/shared/loading-spinner";
import { ExitConversationModal } from "./exit-conversation-modal";
import { useClickOutsideElement } from "#/hooks/use-click-outside-element";
import { Provider } from "#/types/settings";
import { useUpdateConversation } from "#/hooks/mutation/use-update-conversation";
import { displaySuccessToast } from "#/utils/custom-toast-handlers";
import { ConversationCard } from "./conversation-card/conversation-card";
import { StartTaskCard } from "./start-task-card/start-task-card";
import { ConversationCardSkeleton } from "./conversation-card/conversation-card-skeleton";
// >>> CUSTOM: HiClaw <<<
import { useRemoteWorkerStore } from "#/stores/remote-worker-store";
// >>> END CUSTOM <<<

interface ConversationPanelProps {
  onClose: () => void;
}

export function ConversationPanel({ onClose }: ConversationPanelProps) {
  const { t } = useTranslation();
  const { conversationId: currentConversationId } = useParams();
  const ref = useClickOutsideElement<HTMLDivElement>(onClose);
  const navigate = useNavigate();

  const [confirmDeleteModalVisible, setConfirmDeleteModalVisible] =
    React.useState(false);
  const [confirmStopModalVisible, setConfirmStopModalVisible] =
    React.useState(false);
  const [
    confirmExitConversationModalVisible,
    setConfirmExitConversationModalVisible,
  ] = React.useState(false);
  const [selectedConversationId, setSelectedConversationId] = React.useState<
    string | null
  >(null);
  const [selectedConversationTitle, setSelectedConversationTitle] =
    React.useState<string | null>(null);
  const [selectedConversationVersion, setSelectedConversationVersion] =
    React.useState<"V0" | "V1" | undefined>(undefined);
  const [selectedSandboxId, setSelectedSandboxId] = React.useState<
    string | null
  >(null);
  const [openContextMenuId, setOpenContextMenuId] = React.useState<
    string | null
  >(null);

  // >>> CUSTOM: HiClaw — reconnect modal for remote conversations <<<
  const [reconnectModalVisible, setReconnectModalVisible] = React.useState(false);
  const [reconnectPassword, setReconnectPassword] = React.useState("");
  const [reconnectConversationId, setReconnectConversationId] = React.useState<string | null>(null);
  const [reconnectLoading, setReconnectLoading] = React.useState(false);
  const [reconnectError, setReconnectError] = React.useState<string | null>(null);
  const { config, workerManagerUrl } = useRemoteWorkerStore();

  const handleRemoteConversationClick = (conversationId: string, e: React.MouseEvent) => {
    e.preventDefault();
    setReconnectConversationId(conversationId);
    setReconnectPassword(config.password || "");
    setReconnectError(null);
    setReconnectModalVisible(true);
  };

  const handleReconnect = async () => {
    if (!reconnectPassword || !reconnectConversationId) return;
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
      }, { timeout: 30000 });
      // Save password for next time
      useRemoteWorkerStore.getState().setConfig({ password: reconnectPassword });
      setReconnectModalVisible(false);
      onClose();
      navigate(`/conversations/${reconnectConversationId}`);
    } catch (err) {
      setReconnectError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setReconnectLoading(false);
    }
  };
  // >>> END CUSTOM <<<

  // >>> CUSTOM: HiClaw — batch delete <<<
  const [batchMode, setBatchMode] = React.useState(false);
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (selectedIds.size === conversations.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(conversations.map((c) => c.conversation_id)));
    }
  };

  const handleBatchDelete = () => {
    const count = selectedIds.size;
    let completed = 0;
    selectedIds.forEach((id) => {
      deleteConversation(
        { conversationId: id },
        {
          onSuccess: () => {
            completed++;
            if (id === currentConversationId) navigate("/");
            if (completed === count) {
              // Show feedback when all deletions complete
              import("#/utils/custom-toast-handlers").then(({ displaySuccessToast }) => {
                displaySuccessToast(`Deleted ${count} conversation${count > 1 ? "s" : ""}`);
              });
            }
          },
        },
      );
    });
    setSelectedIds(new Set());
    setBatchMode(false);
  };
  // >>> END CUSTOM <<<

  const {
    data,
    isFetching,
    error,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = usePaginatedConversations();

  // Fetch in-progress start tasks
  const { data: startTasks } = useStartTasks();

  // Flatten all pages into a single array of conversations
  const conversations = data?.pages.flatMap((page) => page.results) ?? [];

  const { mutate: deleteConversation } = useDeleteConversation();
  const { mutate: pauseConversationSandbox } =
    useUnifiedPauseConversationSandbox();
  const { mutate: updateConversation } = useUpdateConversation();

  // Set up infinite scroll
  const scrollContainerRef = useInfiniteScroll({
    hasNextPage: !!hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    threshold: 200, // Load more when 200px from bottom
  });

  const handleDeleteProject = (conversationId: string, title: string) => {
    setConfirmDeleteModalVisible(true);
    setSelectedConversationId(conversationId);
    setSelectedConversationTitle(title);
  };

  const handleStopConversation = (
    conversationId: string,
    version?: "V0" | "V1",
    sandboxId?: string | null,
  ) => {
    setConfirmStopModalVisible(true);
    setSelectedConversationId(conversationId);
    setSelectedConversationVersion(version);
    setSelectedSandboxId(sandboxId ?? null);
  };

  const handleConversationTitleChange = async (
    conversationId: string,
    newTitle: string,
  ) => {
    updateConversation(
      { conversationId, newTitle },
      {
        onSuccess: () => {
          displaySuccessToast(t(I18nKey.CONVERSATION$TITLE_UPDATED));
        },
      },
    );
  };

  const handleConfirmDelete = () => {
    if (selectedConversationId) {
      deleteConversation(
        { conversationId: selectedConversationId },
        {
          onSuccess: () => {
            if (selectedConversationId === currentConversationId) {
              navigate("/");
            }
          },
        },
      );
    }
  };

  const handleConfirmStop = () => {
    if (selectedConversationId) {
      pauseConversationSandbox({
        conversationId: selectedConversationId,
        version: selectedConversationVersion,
      });
    }
  };

  return (
    <div
      ref={(node) => {
        // TODO: Combine both refs somehow
        if (ref.current !== node) ref.current = node;
        if (scrollContainerRef.current !== node)
          scrollContainerRef.current = node;
      }}
      data-testid="conversation-panel"
      className="w-full md:w-[400px] h-full border border-[#525252] bg-[#25272D] rounded-lg overflow-y-auto absolute custom-scrollbar-always"
    >
      {/* >>> CUSTOM: HiClaw — batch delete toolbar <<< */}
      {conversations.length > 0 && (
        <div className="sticky top-0 z-10 bg-tertiary border-b border-neutral-600 px-3 py-2">
          {!batchMode ? (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); e.preventDefault(); setBatchMode(true); }}
              className="text-xs text-neutral-500 hover:text-neutral-300 transition"
            >
              Manage
            </button>
          ) : (
            <div className="flex items-center gap-3 w-full">
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); selectAll(); }}
                className="text-xs text-blue-400 hover:text-blue-300 transition"
              >
                {selectedIds.size === conversations.length ? "Deselect" : "All"}
              </button>
              <span className="text-xs text-neutral-500 flex-1">
                {selectedIds.size} selected
              </span>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); handleBatchDelete(); }}
                disabled={selectedIds.size === 0}
                className="text-xs px-2 py-0.5 rounded-md bg-danger/10 text-danger hover:bg-danger/20 disabled:opacity-30 disabled:cursor-not-allowed transition"
              >
                Delete
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setBatchMode(false); setSelectedIds(new Set()); }}
                className="text-xs text-neutral-500 hover:text-neutral-300 transition"
              >
                Done
              </button>
            </div>
          )}
        </div>
      )}
      {/* >>> END CUSTOM <<< */}

      {isFetching && conversations.length === 0 && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, index) => (
            <ConversationCardSkeleton key={index} />
          ))}
        </div>
      )}

      {error && (
        <div className="flex flex-col items-center justify-center h-full">
          <p className="text-danger">{error.message}</p>
        </div>
      )}
      {!isFetching && conversations?.length === 0 && !startTasks?.length && (
        <div className="flex flex-col items-center justify-center h-full">
          <p className="text-neutral-400">
            {t(I18nKey.CONVERSATION$NO_CONVERSATIONS)}
          </p>
        </div>
      )}
      {/* Render in-progress start tasks first */}
      {startTasks?.map((task) => (
        <NavLink
          key={task.id}
          to={`/conversations/task-${task.id}`}
          onClick={onClose}
        >
          <StartTaskCard task={task} />
        </NavLink>
      ))}
      {/* Then render completed conversations */}
      {conversations?.map((project) => (
        batchMode ? (
          <div
            key={project.conversation_id}
            onClick={() => toggleSelect(project.conversation_id)}
            className={`cursor-pointer flex items-center gap-2 ${selectedIds.has(project.conversation_id) ? "bg-blue-900/30" : ""}`}
          >
            <div className="shrink-0 pl-2">
              <input
                type="checkbox"
                checked={selectedIds.has(project.conversation_id)}
                onChange={() => toggleSelect(project.conversation_id)}
                className="accent-blue-500 w-3.5 h-3.5"
              />
            </div>
            <div className="flex-1 min-w-0">
              <ConversationCard
                onDelete={() => {}}
                onStop={() => {}}
                onChangeTitle={() => {}}
                title={project.title}
                selectedRepository={{
                  selected_repository: project.selected_repository,
                  selected_branch: project.selected_branch,
                  git_provider: project.git_provider as Provider,
                }}
                lastUpdatedAt={project.last_updated_at}
                createdAt={project.created_at}
                conversationStatus={project.status}
                conversationId={project.conversation_id}
                conversationVersion={project.conversation_version}
                contextMenuOpen={false}
                onContextMenuToggle={() => {}}
              />
            </div>
          </div>
        ) : (
        <NavLink
          key={project.conversation_id}
          to={`/conversations/${project.conversation_id}`}
          onClick={(e) => {
            // >>> CUSTOM: HiClaw — remote conversations require password <<<
            if (project.sandbox_id?.startsWith("remote-")) {
              handleRemoteConversationClick(project.conversation_id, e);
              return;
            }
            // >>> END CUSTOM <<<
            onClose();
          }}
        >
          <ConversationCard
            onDelete={() =>
              handleDeleteProject(project.conversation_id, project.title)
            }
            onStop={() =>
              handleStopConversation(
                project.conversation_id,
                project.conversation_version,
                project.sandbox_id,
              )
            }
            onChangeTitle={(title) =>
              handleConversationTitleChange(project.conversation_id, title)
            }
            title={project.title}
            selectedRepository={{
              selected_repository: project.selected_repository,
              selected_branch: project.selected_branch,
              git_provider: project.git_provider as Provider,
            }}
            lastUpdatedAt={project.last_updated_at}
            createdAt={project.created_at}
            conversationStatus={project.status}
            conversationId={project.conversation_id}
            conversationVersion={project.conversation_version}
            contextMenuOpen={openContextMenuId === project.conversation_id}
            onContextMenuToggle={(isOpen) =>
              setOpenContextMenuId(isOpen ? project.conversation_id : null)
            }
          />
        </NavLink>
        )
      ))}

      {/* Loading indicator for fetching more conversations */}
      {isFetchingNextPage && (
        <div className="flex justify-center py-4">
          <LoadingSpinner size="small" />
        </div>
      )}

      {confirmDeleteModalVisible && (
        <ConfirmDeleteModal
          onConfirm={() => {
            handleConfirmDelete();
            setConfirmDeleteModalVisible(false);
            setSelectedConversationTitle(null);
          }}
          onCancel={() => {
            setConfirmDeleteModalVisible(false);
            setSelectedConversationTitle(null);
          }}
          conversationTitle={selectedConversationTitle ?? undefined}
        />
      )}

      {confirmStopModalVisible && (
        <ConfirmStopModal
          onConfirm={() => {
            handleConfirmStop();
            setConfirmStopModalVisible(false);
          }}
          onCancel={() => setConfirmStopModalVisible(false)}
          sandboxId={selectedSandboxId}
        />
      )}

      {confirmExitConversationModalVisible && (
        <ExitConversationModal
          onConfirm={() => {
            onClose();
          }}
          onClose={() => setConfirmExitConversationModalVisible(false)}
          onCancel={() => setConfirmExitConversationModalVisible(false)}
        />
      )}

      {/* >>> CUSTOM: HiClaw — reconnect password modal <<< */}
      {reconnectModalVisible && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={(e) => { if (e.target === e.currentTarget) setReconnectModalVisible(false); }}
        >
          <div className="bg-neutral-800 border border-neutral-600 rounded-xl p-6 w-[360px] shadow-2xl">
            <h3 className="text-base font-semibold text-neutral-100 mb-3">SSH Password</h3>
            <p className="text-xs text-neutral-400 mb-3">
              {config.username}@{config.host}
            </p>
            <input
              type="password"
              value={reconnectPassword}
              onChange={(e) => setReconnectPassword(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleReconnect(); }}
              placeholder="Password"
              autoFocus
              className="w-full px-3 py-2 bg-neutral-900 border border-neutral-600 rounded text-neutral-200 text-sm focus:border-blue-500 focus:outline-none mb-3"
            />
            {reconnectError && (
              <p className="text-xs text-red-400 mb-3">{reconnectError}</p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setReconnectModalVisible(false)}
                className="px-4 py-2 text-sm text-neutral-400 hover:text-neutral-200 rounded"
              >
                Cancel
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
      )}
      {/* >>> END CUSTOM <<< */}
    </div>
  );
}
