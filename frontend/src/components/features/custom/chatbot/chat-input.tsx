/* eslint-disable i18next/no-literal-string */
// HiClaw — Chat input: multi-line textarea with model picker and send
// button. Supports two layout variants:
//   - "bottom":   full-width card at the bottom of the page (after first
//                 message has been sent)
//   - "centered": centered card used in the empty-state hero (Qwen-style)

import React from "react";
import { cn } from "#/utils/utils";

interface ModelOption {
  id: string;
  label: string;
  description?: string;
}

// P1: one hardcoded option backed by the platform LLM settings. A future
// /api/v1/chat/models endpoint will replace this list.
const MODELS: ModelOption[] = [
  {
    id: "default",
    label: "HiClaw 默认",
    description: "使用平台 LLM 设置中的模型",
  },
];

interface ChatInputProps {
  onSend: (text: string) => void;
  disabled?: boolean;
  variant?: "bottom" | "centered";
}

export function ChatInput({
  onSend,
  disabled = false,
  variant = "bottom",
}: ChatInputProps) {
  const [value, setValue] = React.useState("");
  const [modelId, setModelId] = React.useState(MODELS[0].id);
  const [menuOpen, setMenuOpen] = React.useState(false);
  const taRef = React.useRef<HTMLTextAreaElement | null>(null);
  const menuRef = React.useRef<HTMLDivElement | null>(null);

  // Auto-grow the textarea up to 6 lines.
  React.useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "0px";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [value]);

  // Close menu on outside click.
  React.useEffect(() => {
    if (!menuOpen) return undefined;
    const onDocClick = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  const handleSend = () => {
    const text = value.trim();
    if (!text || disabled) return;
    setValue("");
    onSend(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  };

  const currentModel = MODELS.find((m) => m.id === modelId) ?? MODELS[0];

  return (
    <div
      className={cn(
        "mx-auto w-full",
        variant === "bottom" ? "max-w-[860px] px-4 pb-4" : "max-w-[640px]",
      )}
    >
      <div
        className={cn(
          "rounded-2xl border bg-[#161b22] border-[#30363d]",
          "focus-within:border-[#58a6ff] transition-colors p-3",
        )}
      >
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息,Enter 发送, Shift+Enter 换行"
          rows={1}
          disabled={disabled}
          className={cn(
            "w-full resize-none bg-transparent outline-none",
            "text-sm text-white placeholder:text-gray-500",
            "disabled:opacity-60",
          )}
        />
        <div className="flex items-center justify-end gap-2 mt-2">
          {/* Model picker */}
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-[#222]"
            >
              <span>{currentModel.label}</span>
              <span className="text-[9px]">▾</span>
            </button>
            {menuOpen && (
              <div className="absolute bottom-full right-0 mb-1 bg-[#161b22] border border-[#30363d] rounded-lg shadow-lg min-w-[240px] py-1 z-10">
                <div className="px-3 py-1 text-[10px] text-gray-500">模型</div>
                {MODELS.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => {
                      setModelId(m.id);
                      setMenuOpen(false);
                    }}
                    className={cn(
                      "w-full text-left px-3 py-2 hover:bg-[#222]",
                      m.id === modelId && "bg-[#1f6feb]/10",
                    )}
                  >
                    <div className="text-xs text-white flex items-center gap-2">
                      {m.label}
                      {m.id === modelId && (
                        <span className="text-[#58a6ff]">✓</span>
                      )}
                    </div>
                    {m.description && (
                      <div className="text-[10px] text-gray-500 mt-0.5">
                        {m.description}
                      </div>
                    )}
                  </button>
                ))}
                <div className="border-t border-[#30363d] mt-1 pt-1 px-3 py-1 text-[10px] text-gray-600">
                  更多模型即将上线
                </div>
              </div>
            )}
          </div>
          {/* Send button */}
          <button
            type="button"
            onClick={handleSend}
            disabled={disabled || !value.trim()}
            aria-label="发送"
            className={cn(
              "w-8 h-8 rounded-full flex items-center justify-center transition text-base",
              value.trim() && !disabled
                ? "bg-[#58a6ff] text-white hover:bg-[#4493f8]"
                : "bg-[#30363d] text-gray-500 cursor-not-allowed",
            )}
          >
            ↑
          </button>
        </div>
      </div>
    </div>
  );
}
