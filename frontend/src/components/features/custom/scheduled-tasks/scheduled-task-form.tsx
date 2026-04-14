/* eslint-disable i18next/no-literal-string, no-nested-ternary, consistent-return */
// HiClaw — Create/edit form for a scheduled task.
//
// Layout:
//   Name input -> Agent dropdown -> Preset form editor (renders the
//   chosen agent's input_form fields) -> SchedulePicker -> Save/Cancel.
//
// The preset editor is a minimal reimplementation of DynamicFormPanel's
// field rendering. File fields upload via FileUploadService.upload and
// store the sandbox path in form_values — same path the live launch
// takes, so a scheduled fire hits the file via the same uploads mount.

import React from "react";
import {
  AgentService,
  type AgentInfo,
} from "#/api/custom-skill-service/agent-service.api";
import { FileUploadService } from "#/api/custom-skill-service/file-upload-service.api";
import {
  ScheduledTaskService,
  type ScheduledTaskInfo,
  type SchedulePayload,
} from "#/api/custom-skill-service/scheduled-task-service.api";
import { cn } from "#/utils/utils";
import { SchedulePicker } from "./schedule-picker";

interface InputFormField {
  key: string;
  type: "file" | "select" | "number" | "text" | "textarea";
  label: string;
  placeholder?: string;
  required?: boolean;
  default?: unknown;
  accept?: string;
  min?: number;
  max?: number;
  options?: Array<{ label: string; value: string; desc?: string }>;
}

interface InputFormConfig {
  fields: InputFormField[];
  submit_message: string;
}

interface Props {
  initialValue?: ScheduledTaskInfo;
  onSaved: (schedule: ScheduledTaskInfo) => void;
  onCancel: () => void;
}

export function ScheduledTaskForm({ initialValue, onSaved, onCancel }: Props) {
  const [agents, setAgents] = React.useState<AgentInfo[]>([]);
  const [agentId, setAgentId] = React.useState<string>(
    initialValue?.agent_id ?? "",
  );
  const [name, setName] = React.useState<string>(initialValue?.name ?? "");
  const [inputForm, setInputForm] = React.useState<InputFormConfig | null>(
    null,
  );
  const [values, setValues] = React.useState<Record<string, unknown>>(
    initialValue?.form_values ?? {},
  );
  const [pendingFiles, setPendingFiles] = React.useState<Record<string, File>>(
    {},
  );
  const [schedule, setSchedule] = React.useState<SchedulePayload>(
    initialValue?.schedule ?? {
      kind: "daily",
      params: { hour: 9, minute: 0 },
    },
  );
  const [enabled, setEnabled] = React.useState<boolean>(
    initialValue?.enabled ?? true,
  );
  const [saving, setSaving] = React.useState(false);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);
  const fileInputRefs = React.useRef<Record<string, HTMLInputElement | null>>(
    {},
  );

  React.useEffect(() => {
    AgentService.listAgents({ is_enabled: true, limit: 200 })
      .then((resp) => setAgents(resp.agents))
      .catch(() => setAgents([]));
  }, []);

  // Load agent config when agent selected (and prefill defaults)
  React.useEffect(() => {
    if (!agentId) {
      setInputForm(null);
      return;
    }
    AgentService.getAgent(agentId)
      .then((agent) => {
        const cfg = JSON.parse(agent.config_json ?? "{}");
        const form = cfg?.input_form as InputFormConfig | null;
        setInputForm(form);
        if (form && !initialValue) {
          // First-time agent pick: seed defaults
          const defaults: Record<string, unknown> = {};
          for (const f of form.fields) {
            if (f.default !== undefined) defaults[f.key] = f.default;
          }
          setValues(defaults);
          setPendingFiles({});
        }
      })
      .catch(() => setInputForm(null));
  }, [agentId, initialValue]);

  const setFieldValue = (key: string, v: unknown) =>
    setValues((prev) => ({ ...prev, [key]: v }));

  const canSubmit =
    agentId.length > 0 &&
    name.trim().length > 0 &&
    !!inputForm &&
    inputForm.fields
      .filter((f) => f.required)
      .every(
        (f) =>
          values[f.key] !== undefined ||
          pendingFiles[f.key] !== undefined ||
          (initialValue && initialValue.form_values[f.key] !== undefined),
      );

  const handleSave = async () => {
    if (!canSubmit || saving) return;
    setSaving(true);
    setErrorMsg(null);
    try {
      // Upload staged files first; parallel.
      const resolved: Record<string, unknown> = { ...values };
      const uploads = await Promise.all(
        Object.entries(pendingFiles).map(async ([key, file]) => {
          const res = await FileUploadService.upload(file);
          return [key, res.sandbox_path] as const;
        }),
      );
      for (const [k, p] of uploads) resolved[k] = p;

      const payload = {
        agent_id: agentId,
        name: name.trim(),
        schedule,
        form_values: resolved,
        enabled,
      };

      const saved = initialValue
        ? await ScheduledTaskService.updateSchedule(initialValue.id, payload)
        : await ScheduledTaskService.createSchedule(payload);
      onSaved(saved);
    } catch (e: unknown) {
      const err = e as {
        message?: string;
        response?: { data?: { detail?: string } };
      };
      setErrorMsg(err?.response?.data?.detail || err?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4 p-5 bg-[#161b22] border border-[#30363d] rounded-xl max-w-2xl">
      {/* Title */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-white">
          {initialValue ? "编辑定时任务" : "新建定时任务"}
        </h2>
        <button
          type="button"
          onClick={onCancel}
          className="text-gray-500 hover:text-white text-sm px-2 py-1 rounded hover:bg-[#333]"
        >
          &times;
        </button>
      </div>

      {errorMsg && (
        <div className="p-2 bg-red-900/30 border border-red-900/50 rounded text-xs text-red-400">
          {errorMsg}
        </div>
      )}

      {/* Name */}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-gray-400">任务名称</span>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="例如：每日 09:00 抖音 trace 分析"
          className="px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded-lg text-sm text-white focus:outline-none focus:border-[#58a6ff]"
        />
      </label>

      {/* Agent */}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-gray-400">Agent</span>
        <select
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          disabled={!!initialValue}
          className="px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded-lg text-sm text-white focus:outline-none focus:border-[#58a6ff] disabled:opacity-60"
        >
          <option value="">-- 选择 Agent --</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </label>

      {/* Preset form editor — renders agent.config.input_form fields */}
      {inputForm && (
        <div className="flex flex-col gap-3 p-3 bg-[#0d1117] border border-[#30363d] rounded-lg">
          <div className="text-xs text-gray-500 -mb-1">
            预设参数（每次定时触发使用这些值）
          </div>
          {inputForm.fields.map((field) => (
            <div key={field.key} className="flex flex-col gap-1">
              <span className="text-[11px] text-gray-500">
                {field.label}
                {field.required && <span className="text-red-400 ml-1">*</span>}
              </span>

              {field.type === "file" && (
                <div
                  className={cn(
                    "flex items-center gap-2 px-3 py-2 rounded border border-[#30363d] bg-[#161b22] cursor-pointer",
                    (pendingFiles[field.key] || values[field.key]) &&
                      "border-[#58a6ff]/50",
                  )}
                  onClick={() => fileInputRefs.current[field.key]?.click()}
                >
                  <input
                    ref={(el) => {
                      fileInputRefs.current[field.key] = el;
                    }}
                    type="file"
                    className="hidden"
                    accept={field.accept}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) {
                        setPendingFiles((prev) => ({
                          ...prev,
                          [field.key]: f,
                        }));
                      }
                    }}
                  />
                  <span className="text-xs text-gray-300 truncate">
                    {pendingFiles[field.key]?.name ??
                      (values[field.key]
                        ? String(values[field.key])
                        : "点击选择文件")}
                  </span>
                </div>
              )}

              {field.type === "select" && (
                <div className="flex flex-wrap gap-1.5">
                  {field.options?.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      title={opt.desc}
                      onClick={() => setFieldValue(field.key, opt.value)}
                      className={cn(
                        "px-3 py-1 rounded-full text-xs border",
                        values[field.key] === opt.value
                          ? "bg-[#58a6ff]/20 text-[#58a6ff] border-[#58a6ff]/60"
                          : "bg-[#0d1117] text-gray-400 border-[#30363d]",
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}

              {field.type === "number" && (
                <input
                  type="number"
                  value={Number(values[field.key] ?? field.default ?? 0)}
                  min={field.min}
                  max={field.max}
                  onChange={(e) =>
                    setFieldValue(field.key, Number(e.target.value))
                  }
                  className="w-32 px-2 py-1 bg-[#161b22] border border-[#30363d] rounded text-white text-xs"
                />
              )}

              {field.type === "text" && (
                <input
                  type="text"
                  value={String(values[field.key] ?? "")}
                  placeholder={field.placeholder}
                  onChange={(e) => setFieldValue(field.key, e.target.value)}
                  className="px-2 py-1 bg-[#161b22] border border-[#30363d] rounded text-white text-xs"
                />
              )}

              {field.type === "textarea" && (
                <textarea
                  value={String(values[field.key] ?? "")}
                  placeholder={field.placeholder}
                  rows={3}
                  onChange={(e) => setFieldValue(field.key, e.target.value)}
                  className="px-2 py-1 bg-[#161b22] border border-[#30363d] rounded text-white text-xs font-mono"
                />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Schedule */}
      <div className="flex flex-col gap-2">
        <span className="text-xs text-gray-400">触发时间</span>
        <SchedulePicker value={schedule} onChange={setSchedule} />
      </div>

      {/* Enabled */}
      <label className="flex items-center gap-2 text-xs text-gray-300">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          className="w-4 h-4"
        />
        启用
      </label>

      {/* Actions */}
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="px-4 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white border border-[#30363d]"
        >
          取消
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={!canSubmit || saving}
          className={cn(
            "px-4 py-1.5 rounded-lg text-xs font-semibold",
            canSubmit && !saving
              ? "bg-[#58a6ff] text-white hover:bg-[#4493f8]"
              : "bg-[#30363d] text-gray-500 cursor-not-allowed",
          )}
        >
          {saving ? "保存中..." : initialValue ? "保存" : "创建"}
        </button>
      </div>
    </div>
  );
}
