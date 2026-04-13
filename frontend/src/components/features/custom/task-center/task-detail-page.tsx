/* eslint-disable i18next/no-literal-string, no-nested-ternary, no-console, no-plusplus, consistent-return */
import React from "react";
import { useParams, useNavigate } from "react-router";
import {
  TaskService,
  type TaskInfo,
} from "#/api/custom-skill-service/task-service.api";
import V1ConversationService from "#/api/conversation-service/v1-conversation-service.api";
import type { TaskListItem } from "#/utils/parse-task-list";
import { cn } from "#/utils/utils";

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-yellow-900/30 text-yellow-400 border-yellow-700",
  running: "bg-blue-900/30 text-blue-400 border-blue-700",
  completed: "bg-green-900/30 text-green-400 border-green-700",
  failed: "bg-red-900/30 text-red-400 border-red-700",
  cancelled: "bg-gray-700/30 text-gray-400 border-gray-600",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "等待中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [task, setTask] = React.useState<TaskInfo | null>(null);
  const [loading, setLoading] = React.useState(true);
  // Execution progress comes straight from the LLM-emitted
  // TaskTrackerObservation events (same source as the right-panel
  // TaskListTab), so this page and the live task list always agree.
  const [taskList, setTaskList] = React.useState<TaskListItem[]>([]);

  // Load task record
  React.useEffect(() => {
    if (!taskId) return;
    setLoading(true);
    TaskService.getTask(taskId)
      .then(setTask)
      .catch((e) => console.error("Failed to load task:", e))
      .finally(() => setLoading(false));
  }, [taskId]);

  // Auto-refresh for running tasks
  React.useEffect(() => {
    if (!taskId || task?.status !== "running") return;
    const interval = setInterval(() => {
      TaskService.getTask(taskId)
        .then(setTask)
        .catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, [taskId, task?.status]);

  // Resolve real app_conversation_id from task- prefixed IDs
  const [resolvedConvId, setResolvedConvId] = React.useState<string | null>(
    null,
  );
  React.useEffect(() => {
    const convId = task?.conversation_id;
    if (!convId) {
      setResolvedConvId(null);
      return;
    }
    if (convId.startsWith("task-")) {
      const startTaskId = convId.slice(5);
      V1ConversationService.getStartTask(startTaskId)
        .then((st) => setResolvedConvId(st?.app_conversation_id ?? null))
        .catch(() => setResolvedConvId(null));
    } else {
      setResolvedConvId(convId);
    }
  }, [task?.conversation_id]);

  // Sync conversation terminal state back onto the task record so the
  // status badge matches reality even when nothing else refreshes it.
  React.useEffect(() => {
    if (!resolvedConvId || !taskId || task?.status !== "running") return;

    const syncStatus = async () => {
      try {
        const convs = await V1ConversationService.batchGetAppConversations([
          resolvedConvId,
        ]);
        const conv = convs?.[0];
        const execStatus = conv?.execution_status?.toLowerCase() ?? null;
        if (execStatus === "finished" || execStatus === "stopped") {
          await TaskService.updateTask(taskId, { status: "completed" });
          const updated = await TaskService.getTask(taskId);
          setTask(updated);
        }
      } catch {
        /* ignore */
      }
    };

    syncStatus();
    const interval = setInterval(syncStatus, 8000);
    return () => clearInterval(interval);
  }, [resolvedConvId, taskId, task?.status]);

  // Pull the conversation's TASKS.json (written by the task_tracker
  // agent action) and render it as the execution plan. This is the same
  // data the live TaskListTab in the chat panel displays, just read from
  // the per-conversation sandbox dir on disk rather than the in-memory
  // event store (which is only populated for the conversation the user
  // is actively connected to via WebSocket).
  React.useEffect(() => {
    if (
      !resolvedConvId ||
      task?.status === "pending" ||
      task?.status === "cancelled"
    )
      return;

    // Absolute path: per_conv_working_dir is /workspace/project/<hex>
    // from the agent-server's perspective but TASKS.json is persisted at
    // /workspace/conversations/<hex>/TASKS.json (the sandbox-data mount).
    // readConversationFile passes absolute paths through unchanged, so
    // we hit the real file directly.
    const tasksPath = `/workspace/conversations/${resolvedConvId}/TASKS.json`;

    let cancelled = false;
    const refresh = async () => {
      try {
        const raw = await V1ConversationService.readConversationFile(
          resolvedConvId,
          tasksPath,
        );
        if (cancelled || !raw) return;
        const arr = JSON.parse(raw) as Array<{
          title?: string;
          notes?: string;
          status?: string;
        }>;
        if (!Array.isArray(arr)) return;
        const normalized: TaskListItem[] = arr.map((t, i) => {
          const status = t.status as TaskListItem["status"] | undefined;
          return {
            id: String(i + 1),
            title: t.title || `Task ${i + 1}`,
            status:
              status === "done" || status === "in_progress" ? status : "todo",
            notes: t.notes || undefined,
          };
        });
        setTaskList(normalized);
      } catch {
        /* parse/read errors leave the list empty — rendered as "no plan" */
      }
    };

    refresh();
    if (task?.status === "running") {
      const interval = setInterval(refresh, 5000);
      return () => {
        cancelled = true;
        clearInterval(interval);
      };
    }
    return () => {
      cancelled = true;
    };
  }, [resolvedConvId, task?.status]);

  const handleCancel = async () => {
    if (!taskId) return;
    try {
      await TaskService.cancelTask(taskId);
      TaskService.getTask(taskId).then(setTask);
    } catch (e) {
      console.error("Failed to cancel:", e);
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500">
        加载中...
      </div>
    );
  }

  if (!task) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-500">
        <p>任务未找到</p>
        <button
          type="button"
          onClick={() => navigate("/tasks")}
          className="mt-4 text-blue-400 hover:underline"
        >
          返回任务列表
        </button>
      </div>
    );
  }

  const duration =
    task.started_at && (task.completed_at || task.status === "running")
      ? Math.round(
          ((task.completed_at
            ? new Date(task.completed_at).getTime()
            : Date.now()) -
            new Date(task.started_at).getTime()) /
            1000,
        )
      : null;

  return (
    <div className="h-full flex flex-col p-6 text-white overflow-auto custom-scrollbar">
      {/* Back */}
      <button
        type="button"
        onClick={() => navigate("/tasks")}
        className="text-sm text-gray-400 hover:text-white mb-4 self-start"
      >
        &larr; 返回任务列表
      </button>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">{task.name || "未命名任务"}</h1>
          <div className="flex items-center gap-3 mt-2">
            <span
              className={cn(
                "text-sm px-3 py-1 rounded border",
                STATUS_STYLES[task.status],
              )}
            >
              {STATUS_LABELS[task.status] || task.status}
            </span>
            {task.agent_name && (
              <span className="text-sm text-gray-400">
                Agent: {task.agent_name}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          {task.conversation_id && (
            <button
              type="button"
              onClick={() => navigate(`/conversations/${task.conversation_id}`)}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition"
            >
              查看对话
            </button>
          )}
          {task.status === "running" && (
            <button
              type="button"
              onClick={handleCancel}
              className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg text-sm font-medium transition"
            >
              取消任务
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Task Info */}
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-300 mb-3">
              任务信息
            </h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">任务 ID</span>
                <span className="text-gray-300 font-mono text-xs">
                  {task.id.slice(0, 8)}...
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">创建者</span>
                <span className="text-gray-300">
                  {task.created_by || "unknown"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">创建时间</span>
                <span className="text-gray-300">
                  {new Date(task.created_at).toLocaleString("zh-CN")}
                </span>
              </div>
              {task.started_at && (
                <div className="flex justify-between">
                  <span className="text-gray-500">开始时间</span>
                  <span className="text-gray-300">
                    {new Date(task.started_at).toLocaleString("zh-CN")}
                  </span>
                </div>
              )}
              {task.completed_at && (
                <div className="flex justify-between">
                  <span className="text-gray-500">完成时间</span>
                  <span className="text-gray-300">
                    {new Date(task.completed_at).toLocaleString("zh-CN")}
                  </span>
                </div>
              )}
              {duration !== null && (
                <div className="flex justify-between">
                  <span className="text-gray-500">耗时</span>
                  <span className="text-gray-300">
                    {duration >= 60
                      ? `${Math.floor(duration / 60)}m ${duration % 60}s`
                      : `${duration}s`}
                    {task.status === "running" && " (进行中)"}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Error message */}
          {task.error_message && (
            <div className="bg-[#161b22] border border-red-900/50 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-red-400 mb-2">
                错误信息
              </h3>
              <pre className="text-xs text-red-300 whitespace-pre-wrap font-mono bg-[#0d1117] p-2 rounded">
                {task.error_message}
              </pre>
            </div>
          )}
        </div>

        {/* Right: Execution Flow — reuses the same task_tracking data
            source as the live TaskListTab, so the two views are always
            in lock-step. */}
        <div className="lg:col-span-2">
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">
              执行流程
            </h3>

            {taskList.length === 0 ? (
              <p className="text-xs text-gray-500">
                {task.status === "running"
                  ? "等待 Agent 生成执行计划..."
                  : "本次任务未生成执行计划"}
              </p>
            ) : (
              <div className="flex flex-col">
                {taskList.map((item, i) => (
                  <div key={item.id} className="flex px-1">
                    {/* Connector line + node — mirrors task-list-tab.tsx */}
                    <div className="flex flex-col items-center mr-2 w-5 shrink-0">
                      {i > 0 && (
                        <div
                          className={cn(
                            "w-0.5 h-2",
                            item.status === "done"
                              ? "bg-green-500"
                              : item.status === "in_progress"
                                ? "bg-blue-500"
                                : "bg-gray-700",
                          )}
                        />
                      )}
                      <div
                        className={cn(
                          "w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold border-2 shrink-0",
                          item.status === "done"
                            ? "bg-green-900/50 border-green-500 text-green-400"
                            : item.status === "in_progress"
                              ? "bg-blue-900/50 border-blue-500 text-blue-400 animate-pulse"
                              : "bg-gray-800 border-gray-600 text-gray-500",
                        )}
                      >
                        {item.status === "done"
                          ? "✓"
                          : item.status === "in_progress"
                            ? "●"
                            : i + 1}
                      </div>
                      {i < taskList.length - 1 && (
                        <div
                          className={cn(
                            "w-0.5 h-2",
                            item.status === "done"
                              ? "bg-green-500"
                              : "bg-gray-700",
                          )}
                        />
                      )}
                    </div>

                    <div
                      className={cn(
                        "flex-1 py-1",
                        item.status === "in_progress" &&
                          "bg-blue-900/20 rounded px-2 -mx-1",
                      )}
                    >
                      <p
                        className={cn(
                          "text-sm font-medium leading-snug",
                          item.status === "done"
                            ? "text-green-400"
                            : item.status === "in_progress"
                              ? "text-blue-400"
                              : "text-gray-400",
                        )}
                      >
                        {item.title}
                      </p>
                      {item.notes && (
                        <p className="text-xs text-gray-500 mt-0.5">
                          {item.notes}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Real-time status hint */}
          {task.status === "running" && (
            <div className="mt-4 bg-[#161b22] border border-blue-900/50 rounded-lg p-4 flex items-center gap-3">
              <div className="w-3 h-3 bg-blue-500 rounded-full animate-pulse shrink-0" />
              <div>
                <p className="text-sm text-blue-400">任务正在执行中</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  每 5
                  秒同步对话事件。点击&ldquo;查看对话&rdquo;可查看实时输出。
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
