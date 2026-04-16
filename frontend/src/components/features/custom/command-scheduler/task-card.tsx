/* eslint-disable i18next/no-literal-string */
import React from "react";
import { CommandSchedule } from "#/api/custom-skill-service/command-scheduler.api";
import { cn } from "#/utils/utils";

interface Props {
  schedule: CommandSchedule;
  onRun: () => void;
  onEdit: () => void;
  onHistory: () => void;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}

export function TaskCard({
  schedule,
  onRun,
  onEdit,
  onHistory,
  onToggle,
  onDelete,
}: Props) {
  const envBadge =
    schedule.env_tag === "formal"
      ? { bg: "bg-blue-900/40 text-blue-300", text: "【正式】" }
      : { bg: "bg-yellow-900/40 text-yellow-300", text: "【测试】" };
  const windowsBadge = schedule.shell_kind === "windows";

  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={cn(
                "text-[10px] font-semibold px-1.5 py-0.5 rounded",
                envBadge.bg,
              )}
            >
              {envBadge.text}
            </span>
            {windowsBadge && (
              <span
                className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-cyan-900/40 text-cyan-300"
                title="需要在 Windows 上跑 runner 才会执行"
              >
                Windows Runner
              </span>
            )}
          </div>
          <div className="font-semibold text-sm mt-1 truncate">
            {schedule.name}
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            {schedule.schedule_description}
          </div>
        </div>
        <label
          aria-label={schedule.enabled ? "禁用任务" : "启用任务"}
          className="relative inline-flex items-center cursor-pointer"
        >
          <input
            type="checkbox"
            checked={schedule.enabled}
            onChange={(e) => onToggle(e.target.checked)}
            className="sr-only peer"
          />
          <div className="w-9 h-5 bg-gray-700 rounded-full peer peer-checked:bg-green-600 transition-colors" />
          <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full peer-checked:translate-x-4 transition-transform" />
        </label>
      </div>
      <div className="text-[11px] text-gray-500 space-y-0.5">
        <div>
          下次:{" "}
          {schedule.next_fire_at
            ? new Date(schedule.next_fire_at).toLocaleString("zh-CN")
            : "(未调度)"}
        </div>
        <div>
          上次:{" "}
          {schedule.last_fire_at
            ? new Date(schedule.last_fire_at).toLocaleString("zh-CN")
            : "(从未)"}
        </div>
      </div>
      <div className="flex gap-2 mt-1">
        <button
          type="button"
          onClick={onRun}
          className="text-[11px] px-2 py-1 rounded bg-green-900/30 text-green-400 hover:bg-green-900/50"
        >
          ▶ 执行
        </button>
        <button
          type="button"
          onClick={onEdit}
          className="text-[11px] px-2 py-1 rounded bg-[#30363d] text-gray-300 hover:bg-[#444]"
        >
          📝 编辑
        </button>
        <button
          type="button"
          onClick={onHistory}
          className="text-[11px] px-2 py-1 rounded bg-[#30363d] text-gray-300 hover:bg-[#444]"
        >
          📜 历史
        </button>
        <button
          type="button"
          onClick={onDelete}
          className="text-[11px] px-2 py-1 rounded bg-red-900/30 text-red-400 hover:bg-red-900/50 ml-auto"
        >
          🗑
        </button>
      </div>
    </div>
  );
}
