/* eslint-disable i18next/no-literal-string */
import React from "react";
import { cn } from "#/utils/utils";

interface Props {
  envTag: string | undefined;
  q: string;
  onChange: (f: { env_tag?: string; q?: string }) => void;
  onNew: () => void;
  onHolidays: () => void;
  onPauseAll: () => void;
}

export function FilterBar({
  envTag,
  q,
  onChange,
  onNew,
  onHolidays,
  onPauseAll,
}: Props) {
  const tabs: { key: string | undefined; label: string }[] = [
    { key: undefined, label: "全部" },
    { key: "formal", label: "正式" },
    { key: "test", label: "测试" },
  ];
  return (
    <div className="flex items-center gap-3 px-5 py-3 border-b border-[#30363d]">
      <div className="flex gap-1 bg-[#161b22] rounded-lg p-1">
        {tabs.map((t) => (
          <button
            key={t.label}
            type="button"
            onClick={() => onChange({ env_tag: t.key, q })}
            className={cn(
              "px-3 py-1 rounded text-xs transition",
              envTag === t.key
                ? "bg-blue-600 text-white"
                : "text-gray-400 hover:text-white",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <input
        type="text"
        value={q}
        onChange={(e) => onChange({ env_tag: envTag, q: e.target.value })}
        placeholder="搜索任务名称"
        className="flex-1 bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5 text-sm text-white placeholder:text-gray-600"
      />
      <button
        type="button"
        onClick={onPauseAll}
        className="text-xs px-3 py-1.5 rounded border border-[#30363d] text-gray-400 hover:text-white"
      >
        暂停全部
      </button>
      <button
        type="button"
        onClick={onHolidays}
        className="text-xs px-3 py-1.5 rounded border border-[#30363d] text-gray-400 hover:text-white"
      >
        节假日管理
      </button>
      <button
        type="button"
        onClick={onNew}
        className="text-xs px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-500"
      >
        + 新建任务
      </button>
    </div>
  );
}
