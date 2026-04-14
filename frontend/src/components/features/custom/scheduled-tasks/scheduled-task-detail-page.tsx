/* eslint-disable i18next/no-literal-string, no-console, no-nested-ternary */
// HiClaw — Scheduled task detail + fire history page.

import React from "react";
import { useNavigate, useParams } from "react-router";
import {
  ScheduledTaskService,
  type ScheduledTaskFireInfo,
  type ScheduledTaskInfo,
} from "#/api/custom-skill-service/scheduled-task-service.api";
import { cn } from "#/utils/utils";

function formatDate(iso: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("zh-CN");
  } catch {
    return iso;
  }
}

function durationOf(startedAt: string, completedAt: string | null): string {
  if (!completedAt) return "(运行中)";
  try {
    const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime();
    const sec = Math.round(ms / 1000);
    return sec >= 60 ? `${Math.floor(sec / 60)}m ${sec % 60}s` : `${sec}s`;
  } catch {
    return "-";
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

export function ScheduledTaskDetailPage() {
  const { scheduleId } = useParams<{ scheduleId: string }>();
  const navigate = useNavigate();
  const [schedule, setSchedule] = React.useState<ScheduledTaskInfo | null>(
    null,
  );
  const [fires, setFires] = React.useState<ScheduledTaskFireInfo[]>([]);
  const [loading, setLoading] = React.useState(true);

  const refresh = React.useCallback(async () => {
    if (!scheduleId) return;
    setLoading(true);
    try {
      const [s, f] = await Promise.all([
        ScheduledTaskService.getSchedule(scheduleId),
        ScheduledTaskService.listFires(scheduleId, 100),
      ]);
      setSchedule(s);
      setFires(f);
    } catch (e) {
      console.error("Failed to load schedule", e);
    } finally {
      setLoading(false);
    }
  }, [scheduleId]);

  React.useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  }, [refresh]);

  const handleFireNow = async () => {
    if (!scheduleId) return;
    try {
      await ScheduledTaskService.fireNow(scheduleId);
      refresh();
    } catch (e) {
      console.error("Failed to fire now", e);
    }
  };

  if (loading && !schedule) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500">
        加载中...
      </div>
    );
  }

  if (!schedule) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-500">
        <p>定时任务未找到</p>
        <button
          type="button"
          onClick={() => navigate("/scheduled-tasks")}
          className="mt-4 text-[#58a6ff] hover:underline"
        >
          返回列表
        </button>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col p-6 text-white overflow-auto custom-scrollbar">
      {/* Back */}
      <button
        type="button"
        onClick={() => navigate("/scheduled-tasks")}
        className="text-sm text-gray-400 hover:text-white mb-4 self-start"
      >
        &larr; 返回列表
      </button>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">{schedule.name}</h1>
          <p className="text-sm text-gray-400 mt-1">
            {schedule.agent_name} · {schedule.schedule_description}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleFireNow}
            className="px-4 py-2 bg-[#58a6ff] hover:bg-[#4493f8] text-white rounded-lg text-sm font-medium"
          >
            立即执行
          </button>
        </div>
      </div>

      {/* Schedule info card */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4 mb-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-3">基本信息</h3>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500">启用状态</span>
            <span
              className={schedule.enabled ? "text-green-400" : "text-gray-500"}
            >
              {schedule.enabled ? "已启用" : "已停用"}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">上次执行</span>
            <span className="text-gray-300 text-xs">
              {formatDate(schedule.last_fire_at)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">下次执行</span>
            <span className="text-gray-300 text-xs">
              {formatDate(schedule.next_fire_at)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">创建时间</span>
            <span className="text-gray-300 text-xs">
              {formatDate(schedule.created_at)}
            </span>
          </div>
        </div>

        {/* Form values */}
        <div className="mt-4 pt-3 border-t border-[#30363d]/60">
          <div className="text-xs text-gray-500 mb-2">预设参数</div>
          <pre className="text-[11px] text-gray-400 bg-[#0d1117] p-2 rounded font-mono whitespace-pre-wrap break-all">
            {JSON.stringify(schedule.form_values, null, 2)}
          </pre>
        </div>
      </div>

      {/* Fire history */}
      <div className="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-[#30363d]">
          <h3 className="text-sm font-semibold text-gray-300">
            执行历史 ({fires.length})
          </h3>
        </div>
        {fires.length === 0 ? (
          <div className="p-4 text-xs text-gray-500">暂无执行记录</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#30363d] text-left text-gray-400">
                <th className="px-4 py-2 font-medium">开始时间</th>
                <th className="px-4 py-2 font-medium">耗时</th>
                <th className="px-4 py-2 font-medium">状态</th>
                <th className="px-4 py-2 font-medium">关联 Task</th>
                <th className="px-4 py-2 font-medium">错误</th>
              </tr>
            </thead>
            <tbody>
              {fires.map((f) => (
                <tr key={f.id} className="border-b border-[#30363d]/60">
                  <td className="px-4 py-2 text-gray-400 text-xs">
                    {formatDate(f.started_at)}
                  </td>
                  <td className="px-4 py-2 text-gray-400 text-xs">
                    {durationOf(f.started_at, f.completed_at)}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={cn(
                        "text-xs px-2 py-0.5 rounded",
                        STATUS_STYLES[f.status] ??
                          "bg-gray-700/30 text-gray-400",
                      )}
                    >
                      {STATUS_LABELS[f.status] ?? f.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs">
                    {f.task_id ? (
                      <button
                        type="button"
                        onClick={() => navigate(`/tasks/${f.task_id}`)}
                        className="text-[#58a6ff] hover:underline"
                      >
                        {f.task_id.slice(0, 8)}...
                      </button>
                    ) : (
                      <span className="text-gray-600">-</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs text-red-400 max-w-xs truncate">
                    {f.error_message ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
