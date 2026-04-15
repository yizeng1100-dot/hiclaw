/* eslint-disable i18next/no-literal-string */
import React from "react";
import {
  CommandSchedulerService,
  Holiday,
} from "#/api/custom-skill-service/command-scheduler.api";
import { cn } from "#/utils/utils";

export function MonthCalendar() {
  const now = new Date();
  const [year, setYear] = React.useState(now.getFullYear());
  const [month, setMonth] = React.useState(now.getMonth() + 1); // 1-12
  const [holidays, setHolidays] = React.useState<Holiday[]>([]);

  React.useEffect(() => {
    CommandSchedulerService.listHolidays(year)
      .then(setHolidays)
      .catch(() => setHolidays([]));
  }, [year]);

  const holidayByDate = React.useMemo(() => {
    const m = new Map<string, Holiday>();
    holidays.forEach((h) => m.set(h.date, h));
    return m;
  }, [holidays]);

  const firstDay = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDay; i += 1) cells.push(null);
  for (let d = 1; d <= daysInMonth; d += 1) cells.push(d);

  const labelOf = (d: number) =>
    `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;

  const prev = () => {
    if (month === 1) {
      setYear(year - 1);
      setMonth(12);
    } else {
      setMonth(month - 1);
    }
  };
  const next = () => {
    if (month === 12) {
      setYear(year + 1);
      setMonth(1);
    } else {
      setMonth(month + 1);
    }
  };

  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-3">
      <div className="flex items-center justify-between mb-2">
        <button
          type="button"
          onClick={prev}
          aria-label="上月"
          className="text-gray-400 hover:text-white px-1"
        >
          ‹
        </button>
        <div className="text-sm font-semibold">
          {year} 年 {month} 月
        </div>
        <button
          type="button"
          onClick={next}
          aria-label="下月"
          className="text-gray-400 hover:text-white px-1"
        >
          ›
        </button>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-[11px]">
        {"日 一 二 三 四 五 六".split(" ").map((w) => (
          <div key={w} className="text-center text-gray-500 py-1">
            {w}
          </div>
        ))}
        {cells.map((d, i) => {
          if (d === null) {
            // eslint-disable-next-line react/no-array-index-key
            return <div key={`empty-${i}`} />;
          }
          const h = holidayByDate.get(labelOf(d));
          const isHoliday = h?.kind === "holiday";
          const isMakeup = h?.kind === "makeup_workday";
          return (
            <div
              key={labelOf(d)}
              title={h?.name}
              className={cn(
                "aspect-square flex items-center justify-center rounded text-xs",
                isHoliday && "bg-red-900/30 text-red-300",
                isMakeup && "bg-yellow-900/30 text-yellow-300",
                !h && "text-gray-400",
              )}
            >
              {d}
            </div>
          );
        })}
      </div>
    </div>
  );
}
