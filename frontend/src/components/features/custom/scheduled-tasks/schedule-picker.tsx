/* eslint-disable i18next/no-literal-string, no-nested-ternary */
// HiClaw — friendly schedule picker for scheduled tasks.
//
// Renders a radio group of 5 schedule kinds plus the conditional
// inputs each kind needs. Emits a SchedulePayload upward via onChange
// so the parent form can validate + save.

import React from "react";
import type {
  ScheduleKind,
  SchedulePayload,
} from "#/api/custom-skill-service/scheduled-task-service.api";
import { cn } from "#/utils/utils";

interface SchedulePickerProps {
  value: SchedulePayload;
  onChange: (value: SchedulePayload) => void;
}

const KINDS: { value: ScheduleKind; label: string; hint: string }[] = [
  { value: "every_n_minutes", label: "每 N 分钟", hint: "间隔触发" },
  { value: "hourly", label: "每小时", hint: "每个整点的第 M 分钟" },
  { value: "daily", label: "每天", hint: "每天固定时间" },
  { value: "one_time", label: "一次性", hint: "指定某个时间点只跑一次" },
  { value: "weekly", label: "每周", hint: "选星期 + 时间" },
  { value: "custom_cron", label: "自定义 cron", hint: "5 字段格式" },
];

const DOW: { value: string; label: string }[] = [
  { value: "mon", label: "一" },
  { value: "tue", label: "二" },
  { value: "wed", label: "三" },
  { value: "thu", label: "四" },
  { value: "fri", label: "五" },
  { value: "sat", label: "六" },
  { value: "sun", label: "日" },
];

function describe(kind: ScheduleKind, params: Record<string, unknown>): string {
  try {
    if (kind === "every_n_minutes") return `每 ${params.minutes ?? 0} 分钟`;
    if (kind === "hourly") {
      const m = Number(params.minute ?? 0);
      return `每小时 xx:${String(m).padStart(2, "0")}`;
    }
    if (kind === "daily") {
      const h = Number(params.hour ?? 0);
      const m = Number(params.minute ?? 0);
      return `每天 ${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
    }
    if (kind === "weekly") {
      const days = String(params.day_of_week ?? "")
        .split(",")
        .filter(Boolean)
        .map((d) => DOW.find((x) => x.value === d.trim())?.label ?? d)
        .map((l) => `周${l}`);
      const h = Number(params.hour ?? 0);
      const m = Number(params.minute ?? 0);
      return `${days.join("、") || "每周"} ${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
    }
    if (kind === "custom_cron") return `cron: ${params.cron ?? ""}`;
    if (kind === "one_time") {
      const run = String(params.run_date ?? "");
      return run ? `一次性: ${run.replace("T", " ")}` : "一次性";
    }
  } catch {
    /* fallthrough */
  }
  return `${kind}[${JSON.stringify(params)}]`;
}

function defaultRunDate(): string {
  // Seed one_time picker with "now + 5 minutes" rounded to the minute,
  // formatted for <input type="datetime-local"> (local time, no tz).
  const d = new Date(Date.now() + 5 * 60_000);
  d.setSeconds(0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const DEFAULT_PARAMS: Record<ScheduleKind, Record<string, unknown>> = {
  every_n_minutes: { minutes: 15 },
  hourly: { minute: 0 },
  daily: { hour: 9, minute: 0 },
  weekly: { day_of_week: "mon", hour: 9, minute: 0 },
  one_time: { run_date: defaultRunDate() },
  custom_cron: { cron: "0 9 * * *" },
};

export function SchedulePicker({ value, onChange }: SchedulePickerProps) {
  const setKind = (kind: ScheduleKind) => {
    onChange({ kind, params: { ...DEFAULT_PARAMS[kind] } });
  };
  const setParam = (key: string, v: unknown) => {
    onChange({ kind: value.kind, params: { ...value.params, [key]: v } });
  };
  const toggleDow = (d: string) => {
    const current = String(value.params.day_of_week ?? "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    const next = current.includes(d)
      ? current.filter((x) => x !== d)
      : [...current, d];
    setParam("day_of_week", next.join(","));
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Kind radio pills */}
      <div className="flex flex-wrap gap-2">
        {KINDS.map((k) => {
          const selected = k.value === value.kind;
          return (
            <button
              key={k.value}
              type="button"
              onClick={() => setKind(k.value)}
              title={k.hint}
              className={cn(
                "px-3 py-1.5 rounded-full text-xs font-medium border transition-colors",
                selected
                  ? "bg-[#58a6ff]/20 text-[#58a6ff] border-[#58a6ff]/60"
                  : "bg-[#0d1117] text-gray-400 border-[#30363d] hover:border-[#525568]",
              )}
            >
              {k.label}
            </button>
          );
        })}
      </div>

      {/* Conditional inputs */}
      <div className="flex flex-col gap-2 p-3 bg-[#0d1117] border border-[#30363d] rounded-lg">
        {value.kind === "every_n_minutes" && (
          <label className="flex items-center gap-2 text-xs text-gray-300">
            间隔（分钟）
            <input
              type="number"
              min={1}
              max={1440}
              value={Number(value.params.minutes ?? 15)}
              onChange={(e) => setParam("minutes", Number(e.target.value))}
              className="w-24 px-2 py-1 bg-[#161b22] border border-[#30363d] rounded text-white text-xs"
            />
          </label>
        )}

        {value.kind === "hourly" && (
          <label className="flex items-center gap-2 text-xs text-gray-300">
            每小时的第
            <input
              type="number"
              min={0}
              max={59}
              value={Number(value.params.minute ?? 0)}
              onChange={(e) => setParam("minute", Number(e.target.value))}
              className="w-20 px-2 py-1 bg-[#161b22] border border-[#30363d] rounded text-white text-xs"
            />
            分钟
          </label>
        )}

        {value.kind === "daily" && (
          <div className="flex items-center gap-2 text-xs text-gray-300">
            每天
            <input
              type="number"
              min={0}
              max={23}
              value={Number(value.params.hour ?? 9)}
              onChange={(e) => setParam("hour", Number(e.target.value))}
              className="w-16 px-2 py-1 bg-[#161b22] border border-[#30363d] rounded text-white text-xs"
            />
            :
            <input
              type="number"
              min={0}
              max={59}
              value={Number(value.params.minute ?? 0)}
              onChange={(e) => setParam("minute", Number(e.target.value))}
              className="w-16 px-2 py-1 bg-[#161b22] border border-[#30363d] rounded text-white text-xs"
            />
          </div>
        )}

        {value.kind === "weekly" && (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-1.5">
              {DOW.map((d) => {
                const current = String(value.params.day_of_week ?? "")
                  .split(",")
                  .map((x) => x.trim());
                const selected = current.includes(d.value);
                return (
                  <button
                    key={d.value}
                    type="button"
                    onClick={() => toggleDow(d.value)}
                    className={cn(
                      "w-8 h-8 rounded-full text-xs font-medium border",
                      selected
                        ? "bg-[#58a6ff]/20 text-[#58a6ff] border-[#58a6ff]/60"
                        : "bg-[#161b22] text-gray-500 border-[#30363d]",
                    )}
                  >
                    {d.label}
                  </button>
                );
              })}
            </div>
            <div className="flex items-center gap-2 text-xs text-gray-300">
              时间
              <input
                type="number"
                min={0}
                max={23}
                value={Number(value.params.hour ?? 9)}
                onChange={(e) => setParam("hour", Number(e.target.value))}
                className="w-16 px-2 py-1 bg-[#161b22] border border-[#30363d] rounded text-white text-xs"
              />
              :
              <input
                type="number"
                min={0}
                max={59}
                value={Number(value.params.minute ?? 0)}
                onChange={(e) => setParam("minute", Number(e.target.value))}
                className="w-16 px-2 py-1 bg-[#161b22] border border-[#30363d] rounded text-white text-xs"
              />
            </div>
          </div>
        )}

        {value.kind === "one_time" && (
          <label className="flex flex-col gap-1 text-xs text-gray-300">
            执行时间（只跑一次，跑完就不再触发）
            <input
              type="datetime-local"
              value={String(value.params.run_date ?? defaultRunDate())}
              onChange={(e) => setParam("run_date", e.target.value)}
              className="w-fit px-2 py-1 bg-[#161b22] border border-[#30363d] rounded text-white text-xs"
            />
            <span className="text-[11px] text-gray-600">
              时间按服务器时区解析（当前 scheduler 环境为 UTC）。
            </span>
          </label>
        )}

        {value.kind === "custom_cron" && (
          <label className="flex flex-col gap-1 text-xs text-gray-300">
            cron 表达式（5 字段：分 时 日 月 周）
            <input
              type="text"
              placeholder="0 9 * * *"
              value={String(value.params.cron ?? "")}
              onChange={(e) => setParam("cron", e.target.value)}
              className="px-2 py-1 bg-[#161b22] border border-[#30363d] rounded text-white text-xs font-mono"
            />
            <span className="text-[11px] text-gray-600">
              示例：0 9 * * 1-5 = 工作日每天 09:00
            </span>
          </label>
        )}

        {/* Live preview */}
        <div className="mt-1 pt-2 border-t border-[#30363d]/60">
          <span className="text-[11px] text-gray-500">预览: </span>
          <span className="text-[11px] text-[#58a6ff] font-medium">
            {describe(value.kind, value.params)}
          </span>
        </div>
      </div>
    </div>
  );
}
