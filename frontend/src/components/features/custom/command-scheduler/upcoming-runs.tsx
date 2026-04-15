/* eslint-disable i18next/no-literal-string */
import React from "react";
import { CommandSchedule } from "#/api/custom-skill-service/command-scheduler.api";

export function UpcomingRuns({ schedules }: { schedules: CommandSchedule[] }) {
  const upcoming = schedules
    .filter((s) => s.enabled && s.next_fire_at)
    .map((s) => ({ s, t: new Date(s.next_fire_at as string) }))
    .sort((a, b) => a.t.getTime() - b.t.getTime())
    .slice(0, 8);

  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-3 mt-3">
      <div className="text-sm font-semibold mb-2">近期执行</div>
      {upcoming.length === 0 ? (
        <div className="text-xs text-gray-500">暂无计划</div>
      ) : (
        <div className="space-y-1.5 text-xs">
          {upcoming.map(({ s, t }) => (
            <div key={s.id} className="flex gap-2">
              <span className="text-gray-500 shrink-0">
                {t.toLocaleString("zh-CN", {
                  month: "2-digit",
                  day: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
              <span className="truncate">{s.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
