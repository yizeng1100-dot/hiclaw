/* eslint-disable i18next/no-literal-string, no-alert */
import React from "react";
import { CommandSchedule } from "#/api/custom-skill-service/command-scheduler.api";
import { TaskCard } from "./task-card";

interface Props {
  schedules: CommandSchedule[];
  loading: boolean;
  onRun: (id: string) => void;
  onEdit: (s: CommandSchedule) => void;
  onHistory: (s: CommandSchedule) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
}

export function TaskGrid({
  schedules,
  loading,
  onRun,
  onEdit,
  onHistory,
  onToggle,
  onDelete,
}: Props) {
  if (loading && schedules.length === 0) {
    return <div className="p-6 text-sm text-gray-500">加载中…</div>;
  }
  if (schedules.length === 0) {
    return (
      <div className="p-10 text-center text-sm text-gray-500">
        还没有任务，点右上角 &quot;+新建任务&quot; 创建
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 p-5 overflow-y-auto custom-scrollbar">
      {schedules.map((s) => (
        <TaskCard
          key={s.id}
          schedule={s}
          onRun={() => onRun(s.id)}
          onEdit={() => onEdit(s)}
          onHistory={() => onHistory(s)}
          onToggle={(e) => onToggle(s.id, e)}
          onDelete={() => {
            if (window.confirm(`确定删除 "${s.name}"?`)) onDelete(s.id);
          }}
        />
      ))}
    </div>
  );
}
