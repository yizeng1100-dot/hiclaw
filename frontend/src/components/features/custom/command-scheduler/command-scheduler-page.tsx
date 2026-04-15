/* eslint-disable i18next/no-literal-string, no-alert */
import React from "react";
import {
  CommandSchedule,
  CommandSchedulerService,
} from "#/api/custom-skill-service/command-scheduler.api";
import { StatsBar } from "./stats-bar";
import { FilterBar } from "./filter-bar";
import { TaskGrid } from "./task-grid";
import { EditTaskModal } from "./edit-task-modal";
import { useCommandScheduler } from "./use-command-scheduler";

// `null` = modal closed, `undefined` = creating new, CommandSchedule = editing
type EditingState = CommandSchedule | undefined | null;

export function CommandSchedulerPage() {
  const {
    schedules,
    stats,
    loading,
    error,
    filter,
    setFilter,
    refresh,
    toggleEnabled,
    runNow,
    remove,
  } = useCommandScheduler();

  const [editing, setEditing] = React.useState<EditingState>(null);

  return (
    <div className="h-full flex flex-col text-white bg-[#0d1117]">
      <div className="px-5 py-3 border-b border-[#30363d]">
        <h1 className="text-base font-semibold">定时任务管理中心</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          配置和监控定时执行的 shell / python 脚本
        </p>
      </div>
      <StatsBar stats={stats} />
      <FilterBar
        envTag={filter.env_tag}
        q={filter.q || ""}
        onChange={setFilter}
        onNew={() => setEditing(undefined)}
        onHolidays={() => window.alert("节假日管理: 后续")}
        onPauseAll={async () => {
          if (window.confirm("确定暂停所有任务?")) {
            await CommandSchedulerService.pauseAll();
            await refresh();
          }
        }}
      />
      {error && (
        <div className="mx-5 mt-3 px-3 py-2 rounded bg-red-900/30 border border-red-900/50 text-xs text-red-400">
          错误: {error}
        </div>
      )}
      <div className="flex-1 overflow-hidden flex">
        <div className="flex-1 overflow-y-auto">
          <TaskGrid
            schedules={schedules}
            loading={loading}
            onRun={runNow}
            onEdit={(s) => setEditing(s)}
            onHistory={() => window.alert("历史 modal: 后续")}
            onToggle={toggleEnabled}
            onDelete={remove}
          />
        </div>
      </div>
      {editing !== null && (
        <EditTaskModal
          initial={editing || undefined}
          onClose={() => setEditing(null)}
          onSaved={refresh}
        />
      )}
    </div>
  );
}
