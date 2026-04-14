/* eslint-disable i18next/no-literal-string */
// HiClaw — Chat input: multi-line textarea + send button, Enter sends,
// Shift+Enter inserts newline.

import React from "react";
import { cn } from "#/utils/utils";

interface ChatInputProps {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled = false }: ChatInputProps) {
  const [value, setValue] = React.useState("");
  const taRef = React.useRef<HTMLTextAreaElement | null>(null);

  // Auto-grow the textarea up to 6 lines.
  React.useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "0px";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [value]);

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

  return (
    <div className="flex items-end gap-2 border-t border-[#30363d] bg-[#161b22] px-4 py-3">
      <textarea
        ref={taRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入消息，Enter 发送，Shift+Enter 换行"
        rows={1}
        disabled={disabled}
        className={cn(
          "flex-1 resize-none rounded-lg bg-[#0d1117] border border-[#30363d] px-3 py-2",
          "text-sm text-white placeholder:text-gray-500",
          "focus:outline-none focus:border-[#58a6ff] disabled:opacity-60",
        )}
      />
      <button
        type="button"
        onClick={handleSend}
        disabled={disabled || !value.trim()}
        className={cn(
          "px-4 py-2 rounded-lg text-sm font-semibold",
          value.trim() && !disabled
            ? "bg-[#58a6ff] text-white hover:bg-[#4493f8]"
            : "bg-[#30363d] text-gray-500 cursor-not-allowed",
        )}
      >
        发送
      </button>
    </div>
  );
}
