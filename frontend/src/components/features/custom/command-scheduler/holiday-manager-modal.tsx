/* eslint-disable i18next/no-literal-string, no-alert */
import React from "react";
import {
  CommandSchedulerService,
  Holiday,
  HolidayCheck,
} from "#/api/custom-skill-service/command-scheduler.api";

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-4">
      <div className="text-xs text-gray-500 mb-2">{title}</div>
      {children}
    </div>
  );
}

function dateLabel(c: HolidayCheck): string {
  if (c.is_holiday) return "节假日";
  if (c.is_makeup_workday) return "调休上班";
  if (c.is_workday) return "工作日";
  return "周末";
}

export function HolidayManagerModal({ onClose }: { onClose: () => void }) {
  const now = new Date();
  const [year, setYear] = React.useState(now.getFullYear());
  const [holidays, setHolidays] = React.useState<Holiday[]>([]);
  const [checkDate, setCheckDate] = React.useState(
    now.toISOString().slice(0, 10),
  );
  const [checkResult, setCheckResult] = React.useState<HolidayCheck | null>(
    null,
  );
  const [addDate, setAddDate] = React.useState("");
  const [addName, setAddName] = React.useState("");
  const [addKind, setAddKind] = React.useState("holiday");

  const refresh = React.useCallback(() => {
    CommandSchedulerService.listHolidays(year)
      .then(setHolidays)
      .catch(() => setHolidays([]));
  }, [year]);
  React.useEffect(refresh, [refresh]);

  const doCheck = async () => {
    try {
      setCheckResult(await CommandSchedulerService.checkDate(checkDate));
    } catch (e) {
      window.alert((e as Error).message);
    }
  };

  const doAdd = async () => {
    if (!addDate || !addName) return;
    try {
      await CommandSchedulerService.addHoliday({
        date: addDate,
        name: addName,
        kind: addKind,
      });
      setAddDate("");
      setAddName("");
      refresh();
    } catch (e) {
      window.alert((e as Error).message);
    }
  };

  const doDelete = async (date: string) => {
    if (!window.confirm(`删除 ${date}?`)) return;
    try {
      await CommandSchedulerService.deleteHoliday(date);
      refresh();
    } catch (e) {
      window.alert((e as Error).message);
    }
  };

  const presets = holidays.filter((h) => h.source === "preset");
  const userRows = holidays.filter((h) => h.source === "user");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl w-[800px] max-h-[90vh] overflow-y-auto p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">节假日管理</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="text-gray-500 hover:text-white"
          >
            ✕
          </button>
        </div>

        <div className="flex items-center gap-3 mb-4">
          <span className="text-xs text-gray-500">年份:</span>
          <input
            type="number"
            value={year}
            onChange={(e) => setYear(parseInt(e.target.value, 10))}
            className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 w-20 text-xs"
          />
        </div>

        <Section title={`预置节假日 (${presets.length})`}>
          <div className="max-h-32 overflow-y-auto text-xs grid grid-cols-3 gap-1">
            {presets.map((h) => (
              <div key={h.date} className="px-2 py-1 bg-[#0d1117] rounded">
                <span className="text-gray-500">{h.date}</span>{" "}
                <span>{h.name}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section title={`自定义节假日 (${userRows.length})`}>
          <div className="space-y-2">
            {userRows.map((h) => (
              <div key={h.date} className="flex items-center gap-2 text-xs">
                <span className="text-gray-500">{h.date}</span>
                <span>{h.name}</span>
                <span className="text-gray-600">· {h.kind}</span>
                <button
                  type="button"
                  onClick={() => doDelete(h.date)}
                  className="ml-auto text-red-400 hover:text-red-300"
                >
                  删除
                </button>
              </div>
            ))}
            <div className="flex items-center gap-2 mt-2">
              <input
                type="date"
                value={addDate}
                onChange={(e) => setAddDate(e.target.value)}
                className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-xs"
              />
              <input
                type="text"
                value={addName}
                onChange={(e) => setAddName(e.target.value)}
                placeholder="名称"
                className="flex-1 bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-xs"
              />
              <select
                value={addKind}
                onChange={(e) => setAddKind(e.target.value)}
                className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-xs"
              >
                <option value="holiday">节假日</option>
                <option value="makeup_workday">调休上班</option>
              </select>
              <button
                type="button"
                onClick={doAdd}
                className="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-500"
              >
                添加
              </button>
            </div>
          </div>
        </Section>

        <Section title="日期检查">
          <div className="flex items-center gap-2 text-xs">
            <input
              type="date"
              value={checkDate}
              onChange={(e) => setCheckDate(e.target.value)}
              className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1"
            />
            <button
              type="button"
              onClick={doCheck}
              className="text-xs px-3 py-1 rounded bg-[#30363d] text-gray-300 hover:bg-[#444]"
            >
              检查
            </button>
            {checkResult && (
              <span className="text-gray-400">
                {dateLabel(checkResult)}
                {checkResult.name ? ` · ${checkResult.name}` : ""}
              </span>
            )}
          </div>
        </Section>
      </div>
    </div>
  );
}
