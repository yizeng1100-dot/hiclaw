// >>> CUSTOM: HiClaw <<<
import React from "react";
import { CondensationEvent } from "#/types/v1/core/events/condensation-event";

interface Props {
  event: CondensationEvent;
}

function formatTime(iso: string | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
  } catch {
    return "";
  }
}

export function CondensationEventMessage({ event }: Props) {
  const forgottenCount = event.forgotten_event_ids?.length || 0;
  const summary = event.summary;
  const [expanded, setExpanded] = React.useState(false);

  return (
    <div className="my-2 px-3 py-2 rounded-lg border border-amber-700/40 bg-amber-900/10 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-amber-400">🗜️</span>
        <span className="text-amber-300 font-medium">上下文压缩</span>
        <span className="text-xs text-neutral-500 font-mono ml-auto">
          {formatTime(event.timestamp)}
        </span>
      </div>
      <div className="text-xs text-neutral-400 mt-1 ml-6">
        合并/移除了 <span className="text-amber-300 font-mono">{forgottenCount}</span> 个历史事件
        {summary && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="ml-2 text-blue-400 hover:underline"
          >
            {expanded ? "隐藏摘要" : "查看摘要"}
          </button>
        )}
      </div>
      {expanded && summary && (
        <div className="mt-2 ml-6 px-3 py-2 rounded border border-neutral-700 bg-neutral-900/50 text-xs text-neutral-300 whitespace-pre-wrap">
          {summary}
        </div>
      )}
    </div>
  );
}
// >>> END CUSTOM <<<
