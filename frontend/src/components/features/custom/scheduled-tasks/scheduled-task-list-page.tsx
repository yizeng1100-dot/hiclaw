/* eslint-disable i18next/no-literal-string, no-console, no-nested-ternary */
// HiClaw — Scheduled tasks list page (/scheduled-tasks).

import React from "react";
import { useNavigate } from "react-router";
import {
  ScheduledTaskService,
  type ScheduledTaskInfo,
} from "#/api/custom-skill-service/scheduled-task-service.api";
import { cn } from "#/utils/utils";
import { ScheduledTaskForm } from "./scheduled-task-form";

function formatDate(iso: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("zh-CN");
  } catch {
    return iso;
  }
}

const STATUS_STYLES: Record<string, string> = {
  running: "bg-blue-900/30 text-blue-400",
  success: "bg-green-900/30 text-green-400",
  failed: "bg-red-900/30 text-red-400",
  skipped_concurrent: "bg-amber-900/30 text-amber-400",
};

const STATUS_LABELS: Record<string, string> = {
  running: "运行中",
  success: "成功",
  failed: "失败",
  skipped_concurrent: "已跳过",
};

export function ScheduledTaskListPage() {
  const navigate = useNavigate();
  const [schedules, setSchedules] = React.useState<ScheduledTaskInfo[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [showForm, setShowForm] = React.useState(false);
  const [editing, setEditing] = React.useState<ScheduledTaskInfo | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const list = await ScheduledTaskService.listSchedules();
      setSchedules(list);
    } catch (e) {
      console.error("Failed to list schedules", e);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const handleToggle = async (s: ScheduledTaskInfo) => {
    try {
      await ScheduledTaskService.updateSchedule(s.id, { enabled: !s.enabled });
      refresh();
    } catch (e) {
      console.error("Failed to toggle schedule", e);
    }
  };

  const handleDelete = async (s: ScheduledTaskInfo) => {
    // eslint-disable-next-line no-alert
    if (!window.confirm(`删除定时任务 "${s.name}"?`)) return;
    try {
      await ScheduledTaskService.deleteSchedule(s.id);
      refresh();
    } catch (e) {
      console.error("Failed to delete schedule", e);
    }
  };

  const handleFireNow = async (s: ScheduledTaskInfo) => {
    try {
      await ScheduledTaskService.fireNow(s.id);
      // eslint-disable-next-line no-alert
      window.alert(`已触发 "${s.name}"，进入详情页查看执行历史`);
      refresh();
    } catch (e) {
      console.error("Failed to fire now", e);
    }
  };

  return (
    <div className="h-full flex flex-col p-6 text-white overflow-auto custom-scrollbar">
      {/* Header */}
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">定时任务</h1>
          <p className="text-sm text-gray-400 mt-1">
            共 {schedules.length} 个任务
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => navigate("/tasks")}
            className="px-3 py-2 text-sm text-gray-400 hover:text-white border border-[#30363d] rounded-lg"
          >
            ← 返回任务中心
          </button>
          <button
            type="button"
            onClick={() => {
              setEditing(null);
              setShowForm(true);
            }}
            className="px-4 py-2 bg-[#58a6ff] hover:bg-[#4493f8] text-white rounded-lg text-sm font-medium"
          >
            + 新建定时任务
          </button>
        </div>
      </div>

      {/* Form modal — rendered inline above the table */}
      {showForm && (
        <div className="mb-6">
          <ScheduledTaskForm
            initialValue={editing ?? undefined}
            onSaved={() => {
              setShowForm(false);
              setEditing(null);
              refresh();
            }}
            onCancel={() => {
              setShowForm(false);
              setEditing(null);
            }}
          />
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center text-gray-500">
          加载中...
        </div>
      ) : schedules.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-500">
          <p>暂无定时任务</p>
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="mt-3 text-[#58a6ff] text-sm hover:underline"
          >
            新建一个
          </button>
        </div>
      ) : (
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#30363d] text-left text-gray-400">
                <th className="px-4 py-3 font-medium">名称</th>
                <th className="px-4 py-3 font-medium">Agent</th>
                <th className="px-4 py-3 font-medium">触发时间</th>
                <th className="px-4 py-3 font-medium">上次</th>
                <th className="px-4 py-3 font-medium">下次</th>
                <th className="px-4 py-3 font-medium">状态</th>
                <th className="px-4 py-3 font-medium">启用</th>
                <th className="px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((s) => (
                <tr
                  key={s.id}
                  className="border-b border-[#30363d] hover:bg-[#1c2128]"
                >
                  <td className="px-4 py-3 text-white">
                    <button
                      type="button"
                      onClick={() => navigate(`/scheduled-tasks/${s.id}`)}
                      className="hover:text-[#58a6ff] hover:underline"
                    >
                      {s.name}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-gray-400">
                    {s.agent_name ?? "-"}
                  </td>
                  <td className="px-4 py-3 text-gray-400">
                    {s.schedule_description}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {formatDate(s.last_fire_at)}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {formatDate(s.next_fire_at)}
                  </td>
                  <td className="px-4 py-3">
                    {s.last_status ? (
                      <span
                        className={cn(
                          "text-xs px-2 py-0.5 rounded",
                          STATUS_STYLES[s.last_status] ??
                            "bg-gray-700/30 text-gray-400",
                        )}
                      >
                        {STATUS_LABELS[s.last_status] ?? s.last_status}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-600">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => handleToggle(s)}
                      className={cn(
                        "text-xs px-2 py-0.5 rounded border",
                        s.enabled
                          ? "bg-green-900/30 text-green-400 border-green-800"
                          : "bg-gray-700/30 text-gray-500 border-gray-700",
                      )}
                    >
                      {s.enabled ? "已启用" : "已停用"}
                    </button>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2 text-xs">
                      <button
                        type="button"
                        onClick={() => handleFireNow(s)}
                        className="text-[#58a6ff] hover:text-[#79c0ff]"
                      >
                        立即执行
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setEditing(s);
                          setShowForm(true);
                        }}
                        className="text-gray-400 hover:text-white"
                      >
                        编辑
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(s)}
                        className="text-red-400 hover:text-red-300"
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
