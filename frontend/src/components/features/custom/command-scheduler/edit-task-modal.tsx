/* eslint-disable i18next/no-literal-string */
import React from "react";
import {
  CommandSchedule,
  CommandScheduleInput,
  CommandSchedulerService,
  ScheduleKind,
  ShellKind,
  HolidayPolicy,
  EnvTag,
} from "#/api/custom-skill-service/command-scheduler.api";

interface Props {
  initial?: CommandSchedule;
  onClose: () => void;
  onSaved: () => void;
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-[11px] text-gray-500 mb-1">{label}</div>
      {children}
    </div>
  );
}

const DEFAULT: CommandScheduleInput = {
  name: "",
  env_tag: "formal",
  shell_kind: "linux",
  kind: "daily",
  cron_expr: "0 9 * * *",
  run_at: null,
  command: "",
  working_dir: null,
  max_duration_sec: 300,
  holiday_policy: "normal",
  enabled: true,
};

export function EditTaskModal({ initial, onClose, onSaved }: Props) {
  const [form, setForm] = React.useState<CommandScheduleInput>(() => {
    if (!initial) return DEFAULT;
    return {
      name: initial.name,
      env_tag: initial.env_tag,
      shell_kind: initial.shell_kind,
      kind: initial.kind,
      cron_expr: initial.cron_expr,
      run_at: initial.run_at,
      command: initial.command,
      working_dir: initial.working_dir,
      max_duration_sec: initial.max_duration_sec,
      holiday_policy: initial.holiday_policy,
      enabled: initial.enabled,
    };
  });
  const [saving, setSaving] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  const update = <K extends keyof CommandScheduleInput>(
    k: K,
    v: CommandScheduleInput[K],
  ) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      if (initial) {
        await CommandSchedulerService.update(initial.id, form);
      } else {
        await CommandSchedulerService.create(form);
      }
      onSaved();
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl w-[600px] max-h-[90vh] overflow-y-auto p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">
            {initial ? "编辑任务" : "新建任务"}
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
        <div className="space-y-3 text-sm">
          <Field label="任务名称">
            <input
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5"
            />
          </Field>
          <Field label="环境标签">
            <div className="flex gap-4">
              {(["formal", "test"] as EnvTag[]).map((v) => (
                <label key={v} className="flex items-center gap-1">
                  <input
                    type="radio"
                    checked={form.env_tag === v}
                    onChange={() => update("env_tag", v)}
                  />
                  {v === "formal" ? "正式" : "测试"}
                </label>
              ))}
            </div>
          </Field>
          <Field label="命令类型">
            <div className="flex gap-4">
              {(["linux", "windows"] as ShellKind[]).map((v) => (
                <label key={v} className="flex items-center gap-1">
                  <input
                    type="radio"
                    checked={form.shell_kind === v}
                    onChange={() => update("shell_kind", v)}
                  />
                  {v === "linux" ? "Linux" : "Windows (暂存)"}
                </label>
              ))}
            </div>
          </Field>
          <Field label="调度类型">
            <select
              value={form.kind}
              onChange={(e) => update("kind", e.target.value as ScheduleKind)}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5"
            >
              <option value="one_time">一次性</option>
              <option value="daily">每天</option>
              <option value="weekly">每周</option>
              <option value="monthly">每月</option>
              <option value="yearly">每年</option>
            </select>
          </Field>
          {form.kind === "one_time" ? (
            <Field label="执行时间">
              <input
                type="datetime-local"
                value={form.run_at?.slice(0, 16) || ""}
                onChange={(e) =>
                  update(
                    "run_at",
                    e.target.value
                      ? new Date(e.target.value).toISOString()
                      : null,
                  )
                }
                className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5"
              />
            </Field>
          ) : (
            <Field label="Cron 表达式">
              <input
                value={form.cron_expr || ""}
                onChange={(e) => update("cron_expr", e.target.value)}
                placeholder="例: 0 9 * * * (每天 09:00)"
                className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5 font-mono text-xs"
              />
            </Field>
          )}
          <Field label="节假日策略">
            <select
              value={form.holiday_policy}
              onChange={(e) =>
                update("holiday_policy", e.target.value as HolidayPolicy)
              }
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5"
            >
              <option value="normal">照常运行</option>
              <option value="skip">节假日跳过</option>
              <option value="run_before">提前到前一工作日 (P1 同 skip)</option>
              <option value="run_after">延后到后一工作日 (P1 同 skip)</option>
            </select>
          </Field>
          <Field label="最大执行时长 (秒)">
            <input
              type="number"
              value={form.max_duration_sec}
              onChange={(e) =>
                update(
                  "max_duration_sec",
                  parseInt(e.target.value || "300", 10),
                )
              }
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5"
            />
          </Field>
          <Field label="执行命令">
            <textarea
              value={form.command}
              onChange={(e) => update("command", e.target.value)}
              rows={6}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 font-mono text-xs"
              placeholder={`cd /opt/hiclaw/command_scheduler/workspace/nps\nsource /opt/hiclaw/command_scheduler/venv/bin/activate\npython send_nps.py --prod`}
            />
          </Field>
          {err && <div className="text-xs text-red-400">错误: {err}</div>}
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button
            type="button"
            onClick={onClose}
            className="text-sm px-3 py-1.5 rounded border border-[#30363d] text-gray-400 hover:text-white"
          >
            取消
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={save}
            className="text-sm px-4 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
