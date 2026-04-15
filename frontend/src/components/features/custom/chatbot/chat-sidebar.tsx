/* eslint-disable i18next/no-literal-string, no-alert */
// HiClaw — Left panel inside the chat page: session list + "新对话".

import React from "react";
import { cn } from "#/utils/utils";
import { ChatSession } from "./use-chat";

interface Props {
  sessions: ChatSession[];
  currentId: string | null;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

interface RowProps {
  session: ChatSession;
  active: boolean;
  onClick: () => void;
  onDelete: () => void;
}

function SessionRow({ session, active, onClick, onDelete }: RowProps) {
  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (window.confirm(`删除 "${session.title}"?`)) {
      onDelete();
    }
  };

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group w-full flex items-center gap-2 px-2.5 py-2 rounded-md text-xs text-left transition",
        active
          ? "bg-[#1f6feb]/20 text-white"
          : "text-gray-400 hover:bg-[#222] hover:text-white",
      )}
    >
      <span className="flex-1 truncate">{session.title}</span>
      <span
        role="button"
        tabIndex={-1}
        aria-label="删除对话"
        onClick={handleDelete}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            handleDelete(e as unknown as React.MouseEvent);
          }
        }}
        className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 text-[14px] leading-none px-1"
      >
        ✕
      </span>
    </button>
  );
}

export function ChatSidebar({
  sessions,
  currentId,
  onNew,
  onSelect,
  onDelete,
}: Props) {
  return (
    <aside className="w-[260px] shrink-0 border-r border-[#30363d] flex flex-col bg-[#0d1117]">
      <div className="p-3">
        <button
          type="button"
          onClick={onNew}
          className="w-full px-3 py-2 rounded-lg border border-[#30363d] text-sm text-gray-300 hover:text-white hover:border-[#525568] flex items-center justify-center gap-2 transition"
        >
          <span className="text-base leading-none">＋</span>
          <span>新对话</span>
        </button>
      </div>
      <div className="px-4 pt-2 pb-1 text-[10px] text-gray-500 uppercase tracking-wider">
        历史对话
      </div>
      <div className="flex-1 overflow-y-auto custom-scrollbar px-2 pb-3">
        {sessions.length === 0 ? (
          <div className="px-3 py-6 text-xs text-gray-600 text-center">
            暂无对话, 点上方 &quot;+新对话&quot;开始
          </div>
        ) : (
          sessions.map((s) => (
            <SessionRow
              key={s.id}
              session={s}
              active={s.id === currentId}
              onClick={() => onSelect(s.id)}
              onDelete={() => onDelete(s.id)}
            />
          ))
        )}
      </div>
    </aside>
  );
}
