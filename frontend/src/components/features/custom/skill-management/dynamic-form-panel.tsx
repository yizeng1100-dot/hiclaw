/* eslint-disable i18next/no-literal-string */
import React from "react";
import { FileUploadService } from "#/api/custom-skill-service/file-upload-service.api";
import { cn } from "#/utils/utils";

// ---- Schema types matching backend input_form ----

interface FormFieldBase {
  key: string;
  type: "file" | "select" | "text" | "number" | "textarea";
  label: string;
  placeholder?: string;
  required?: boolean;
  default?: string | number;
}

interface FileField extends FormFieldBase {
  type: "file";
  accept?: string;
}

interface SelectOption {
  label: string;
  value: string;
  desc?: string;
}

interface SelectField extends FormFieldBase {
  type: "select";
  options: SelectOption[];
}

interface NumberField extends FormFieldBase {
  type: "number";
  min?: number;
  max?: number;
  step?: number;
}

interface TextField extends FormFieldBase {
  type: "text";
}

interface TextareaField extends FormFieldBase {
  type: "textarea";
  rows?: number;
}

type FormField =
  | FileField
  | SelectField
  | NumberField
  | TextField
  | TextareaField;

export interface InputFormConfig {
  fields: FormField[];
  submit_message: string;
}

interface DynamicFormPanelProps {
  config: InputFormConfig;
  onSubmit: (message: string) => void;
  onDismiss: () => void;
  disabled?: boolean;
  accentColor?: string;
}

export function DynamicFormPanel({
  config,
  onSubmit,
  onDismiss,
  disabled,
  accentColor = "#4ECDC4",
}: DynamicFormPanelProps) {
  const [values, setValues] = React.useState<Record<string, string | number>>(
    () => {
      const defaults: Record<string, string | number> = {};
      for (const field of config.fields) {
        if (field.default !== undefined) {
          defaults[field.key] = field.default;
        } else if (field.type === "number") {
          defaults[field.key] = "";
        } else {
          defaults[field.key] = "";
        }
      }
      return defaults;
    },
  );

  const [pendingFiles, setPendingFiles] = React.useState<Record<string, File>>(
    {},
  );
  const [uploading, setUploading] = React.useState(false);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);
  const fileInputRefs = React.useRef<Record<string, HTMLInputElement | null>>(
    {},
  );

  const setValue = (key: string, val: string | number) => {
    setValues((prev) => ({ ...prev, [key]: val }));
  };

  const clearPendingFile = (key: string) => {
    setPendingFiles((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const canSubmit = config.fields
    .filter((f) => f.required)
    .every((f) => {
      const v = values[f.key];
      return v !== undefined && v !== "";
    });

  const handleSubmit = async () => {
    if (!canSubmit || uploading) return;
    setErrorMsg(null);
    setUploading(true);
    try {
      // Upload any staged files first; replace the field value with the
      // real sandbox-visible path returned by the backend. Uploads run
      // in parallel — there's no dependency between files and the
      // component stays unresponsive until all uploads resolve.
      const resolved: Record<string, string | number> = { ...values };
      const uploads = await Promise.all(
        Object.entries(pendingFiles).map(async ([key, file]) => {
          const res = await FileUploadService.upload(file);
          return [key, res.sandbox_path] as const;
        }),
      );
      for (const [key, path] of uploads) resolved[key] = path;
      // Template interpolation: replace {{key}} with resolved values
      let message = config.submit_message;
      for (const [key, val] of Object.entries(resolved)) {
        message = message.replace(
          new RegExp(`\\{\\{${key}\\}\\}`, "g"),
          String(val),
        );
      }
      // Clean up empty template vars
      message = message.replace(/\{\{[^}]+\}\}/g, "");
      onSubmit(message.trim());
    } catch (e: unknown) {
      const err = e as { message?: string };
      setErrorMsg(err?.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      className="flex flex-col gap-3 px-4 py-3 mx-2 mb-2 rounded-xl border bg-[#161b22]"
      style={{ borderColor: `${accentColor}30` }}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke={accentColor}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
          </svg>
          <span
            className="text-sm font-semibold"
            style={{ color: accentColor }}
          >
            Analysis Configuration
          </span>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="text-gray-500 hover:text-white text-xs px-1.5 py-0.5 rounded hover:bg-[#333] transition"
        >
          &times;
        </button>
      </div>

      {/* Dynamic fields */}
      {config.fields.map((field) => (
        <div key={field.key}>
          {field.type === "file" &&
            (() => {
              const staged = pendingFiles[field.key];
              return (
                <div className="flex items-center gap-2">
                  <div
                    className={cn(
                      "flex-1 flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer border transition-colors",
                      staged
                        ? "border-opacity-50 bg-opacity-5"
                        : "border-[#30363d] bg-[#0d1117] hover:border-[#525568]",
                    )}
                    style={
                      staged
                        ? {
                            borderColor: `${accentColor}80`,
                            backgroundColor: `${accentColor}0d`,
                          }
                        : {}
                    }
                    onClick={() => fileInputRefs.current[field.key]?.click()}
                  >
                    <input
                      ref={(el) => {
                        fileInputRefs.current[field.key] = el;
                      }}
                      type="file"
                      className="hidden"
                      accept={(field as FileField).accept}
                      onChange={(e) => {
                        if (e.target.files?.[0]) {
                          const file = e.target.files[0];
                          setPendingFiles((prev) => ({
                            ...prev,
                            [field.key]: file,
                          }));
                          // Display-only hint; real sandbox path is resolved at submit.
                          setValue(field.key, file.name);
                        }
                      }}
                    />
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke={staged ? accentColor : "#525568"}
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                    {staged ? (
                      <span className="text-xs text-white truncate">
                        {staged.name}
                        <span className="text-[#727987] ml-1">
                          ({(staged.size / 1024 / 1024).toFixed(1)}MB)
                        </span>
                      </span>
                    ) : (
                      <span className="text-xs text-[#525568]">
                        {field.label}
                      </span>
                    )}
                  </div>
                  <span className="text-[10px] text-[#30363d]">or</span>
                  <input
                    type="text"
                    value={staged ? "" : String(values[field.key] || "")}
                    onChange={(e) => {
                      setValue(field.key, e.target.value);
                      clearPendingFile(field.key);
                    }}
                    placeholder={field.placeholder}
                    className="flex-1 px-2 py-2 bg-[#0d1117] border border-[#30363d] rounded-lg text-xs text-white placeholder-[#525568] focus:outline-none"
                    style={{ ["--tw-ring-color" as string]: accentColor }}
                  />
                </div>
              );
            })()}

          {field.type === "select" && (
            <div>
              <label className="text-[11px] text-gray-500 mb-1 block">
                {field.label}
              </label>
              <div className="flex flex-wrap gap-1.5">
                {(field as SelectField).options.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className={cn(
                      "px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors border",
                      values[field.key] === opt.value
                        ? "border-opacity-50"
                        : "bg-[#21262d] text-[#8b949e] border-[#30363d] hover:border-[#525568] hover:text-white",
                    )}
                    style={
                      values[field.key] === opt.value
                        ? {
                            backgroundColor: `${accentColor}33`,
                            color: accentColor,
                            borderColor: `${accentColor}80`,
                          }
                        : {}
                    }
                    onClick={() => setValue(field.key, opt.value)}
                    title={opt.desc}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {field.type === "text" && (
            <input
              type="text"
              value={String(values[field.key] || "")}
              onChange={(e) => setValue(field.key, e.target.value)}
              placeholder={field.placeholder || field.label}
              className="w-full px-2 py-1.5 bg-[#0d1117] border border-[#30363d] rounded-lg text-xs text-white placeholder-[#525568] focus:outline-none"
            />
          )}

          {field.type === "number" && (
            <div>
              <label className="text-[11px] text-gray-500 mb-1 block">
                {field.label}
              </label>
              <input
                type="number"
                value={
                  values[field.key] === "" ? "" : Number(values[field.key])
                }
                onChange={(e) =>
                  setValue(
                    field.key,
                    e.target.value === "" ? "" : Number(e.target.value),
                  )
                }
                placeholder={field.placeholder || field.label}
                min={(field as NumberField).min}
                max={(field as NumberField).max}
                step={(field as NumberField).step}
                className="w-32 px-2 py-1.5 bg-[#0d1117] border border-[#30363d] rounded-lg text-xs text-white placeholder-[#525568] focus:outline-none"
              />
            </div>
          )}

          {field.type === "textarea" && (
            <textarea
              value={String(values[field.key] || "")}
              onChange={(e) => setValue(field.key, e.target.value)}
              placeholder={field.placeholder || field.label}
              rows={(field as TextareaField).rows || 3}
              className="w-full px-2 py-1.5 bg-[#0d1117] border border-[#30363d] rounded-lg text-xs text-white placeholder-[#525568] focus:outline-none resize-none"
            />
          )}
        </div>
      ))}

      {errorMsg && (
        <div className="text-[11px] text-red-400 px-1">{errorMsg}</div>
      )}

      {/* Submit */}
      <div className="flex justify-end">
        <button
          type="button"
          disabled={!canSubmit || disabled || uploading}
          className={cn(
            "px-4 py-1.5 rounded-lg font-semibold text-xs whitespace-nowrap transition-all",
            canSubmit && !disabled && !uploading
              ? "text-black cursor-pointer"
              : "bg-[#21262d] text-[#525568] cursor-not-allowed",
          )}
          style={
            canSubmit && !disabled && !uploading
              ? { backgroundColor: accentColor }
              : {}
          }
          onClick={handleSubmit}
        >
          {uploading ? "Uploading..." : "Analyze"}
        </button>
      </div>
    </div>
  );
}
