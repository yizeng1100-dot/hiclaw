/* eslint-disable i18next/no-literal-string */
import React from "react";
import {
  CommandSchedule,
  CommandFire,
  CommandSchedulerService,
} from "#/api/custom-skill-service/command-scheduler.api";
import { cn } from "#/utils/utils";

const STATUS_COLOR: Record<string, string> = {
  success: "bg-green-900/40 text-green-400",
  failed: "bg-red-900/40 text-red-400",
  timeout: "bg-orange-900/40 text-orange-400",
  skipped: "bg-gray-800 text-gray-400",
  running: "bg-blue-900/40 text-blue-400",
  pending_runner: "bg-cyan-900/40 text-cyan-400",
};

export function TaskHistoryModal({
  schedule,
  onClose,
}: {
  schedule: CommandSchedule;
  onClose: () => void;
}) {
  const [fires, setFires] = React.useState<CommandFire[]>([]);
  const [selected, setSelected] = React.useState<CommandFire | null>(null);

  React.useEffect(() => {
    CommandSchedulerService.listFires(schedule.id, 50)
      .then(setFires)
      .catch(() => setFires([]));
  }, [schedule.id]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl w-[800px] max-h-[90vh] flex flex-col p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">
            {schedule.name} — 执行历史
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="text-gray-500 hover:text-white"
          >
            ✕
          </button>
        </div>
        <div className="grid grid-cols-[260px_1fr] gap-4 flex-1 overflow-hidden">
          <div className="overflow-y-auto custom-scrollbar space-y-1">
            {fires.map((f) => (
              <button
                type="button"
                key={f.id}
                onClick={() => setSelected(f)}
                className={cn(
                  "w-full text-left text-xs p-2 rounded hover:bg-[#222]",
                  selected?.id === f.id && "bg-[#222]",
                )}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "px-1.5 py-0.5 rounded text-[10px] font-semibold",
                      STATUS_COLOR[f.status],
                    )}
                  >
                    {f.status}
                  </span>
                  <span className="text-gray-500">
                    {new Date(f.started_at).toLocaleString("zh-CN")}
                  </span>
                </div>
                {f.skip_reason && (
                  <div className="text-gray-600 mt-0.5">
                    原因: {f.skip_reason}
                  </div>
                )}
              </button>
            ))}
            {fires.length === 0 && (
              <div className="text-xs text-gray-500 p-2">暂无执行记录</div>
            )}
          </div>
          <div className="overflow-y-auto custom-scrollbar bg-[#0d1117] rounded border border-[#30363d] p-3">
            {selected ? (
              <>
                <div className="text-xs text-gray-500 mb-2">
                  退出码: {selected.exit_code ?? "—"} · 开始:{" "}
                  {new Date(selected.started_at).toLocaleString("zh-CN")} ·
                  结束:{" "}
                  {selected.completed_at
                    ? new Date(selected.completed_at).toLocaleString("zh-CN")
                    : "(未结束)"}
                </div>
                {selected.log_file_path && (
                  <a
                    href={CommandSchedulerService.logUrl(selected.id)}
                    className="text-xs text-blue-400 hover:underline"
                    download
                  >
                    下载完整日志
                  </a>
                )}
                <div className="mt-3">
                  <div className="text-[10px] text-gray-600">STDOUT</div>
                  <pre className="text-[11px] whitespace-pre-wrap max-h-48 overflow-y-auto">
                    {selected.stdout_tail || "(空)"}
                  </pre>
                </div>
                <div className="mt-3">
                  <div className="text-[10px] text-gray-600">STDERR</div>
                  <pre className="text-[11px] whitespace-pre-wrap max-h-48 overflow-y-auto text-red-300">
                    {selected.stderr_tail || "(空)"}
                  </pre>
                </div>
              </>
            ) : (
              <div className="text-xs text-gray-500">
                从左侧选择一次执行查看详情
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
