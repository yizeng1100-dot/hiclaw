/* eslint-disable i18next/no-literal-string */
import React from "react";
import { Stats } from "#/api/custom-skill-service/command-scheduler.api";
import { cn } from "#/utils/utils";

export function StatsBar({ stats }: { stats: Stats }) {
  const cells: { label: string; value: number; color: string }[] = [
    { label: "总任务", value: stats.total, color: "text-white" },
    { label: "执行中", value: stats.running, color: "text-blue-400" },
    { label: "已启用", value: stats.enabled, color: "text-green-400" },
    { label: "已停用", value: stats.disabled, color: "text-gray-500" },
  ];
  return (
    <div className="grid grid-cols-4 gap-3 px-5 py-3 border-b border-[#30363d]">
      {cells.map((c) => (
        <div
          key={c.label}
          className="bg-[#161b22] border border-[#30363d] rounded-lg px-4 py-3"
        >
          <div className="text-xs text-gray-500">{c.label}</div>
          <div className={cn("text-2xl font-semibold mt-1", c.color)}>
            {c.value}
          </div>
        </div>
      ))}
    </div>
  );
}
