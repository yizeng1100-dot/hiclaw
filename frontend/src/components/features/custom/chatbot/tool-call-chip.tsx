/* eslint-disable i18next/no-literal-string, no-nested-ternary */
// HiClaw — Tool call / tool result chip for the chatbot.
//
// Rendered inline within an assistant bubble or as a standalone row in
// the message list. Collapsed by default — click to expand and see the
// full JSON arguments + result.

import React from "react";
import { cn } from "#/utils/utils";

interface ToolCallChipProps {
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  running?: boolean;
}

export function ToolCallChip({
  name,
  args,
  result,
  running = false,
}: ToolCallChipProps) {
  const [expanded, setExpanded] = React.useState(false);

  const argsStr = JSON.stringify(args);
  const argsShort = argsStr.length > 80 ? `${argsStr.slice(0, 80)}…` : argsStr;

  const status = running ? "running" : result !== undefined ? "done" : "idle";

  return (
    <div
      className={cn(
        "my-1 text-[11px] rounded border transition-colors",
        status === "running"
          ? "bg-blue-900/20 border-blue-800/50 text-blue-300"
          : status === "done"
            ? "bg-[#0d1117] border-[#30363d] text-gray-400"
            : "bg-[#0d1117] border-[#30363d] text-gray-500",
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2 py-1.5 text-left"
      >
        <span className="font-semibold">
          {status === "running" ? "⏳" : status === "done" ? "✓" : "·"}
        </span>
        <span className="font-mono text-[#79c0ff]">{name}</span>
        <span className="font-mono text-gray-500 truncate flex-1">
          ({argsShort})
        </span>
        <span className="text-gray-600">{expanded ? "▴" : "▾"}</span>
      </button>

      {expanded && (
        <div className="px-2 pb-2 flex flex-col gap-2 border-t border-[#30363d]/50 pt-2 mt-1">
          <div>
            <div className="text-[10px] text-gray-600 mb-1">ARGS</div>
            <pre className="text-[11px] bg-black/30 rounded p-1.5 overflow-x-auto font-mono">
              {JSON.stringify(args, null, 2)}
            </pre>
          </div>
          {result !== undefined && (
            <div>
              <div className="text-[10px] text-gray-600 mb-1">RESULT</div>
              <pre className="text-[11px] bg-black/30 rounded p-1.5 overflow-x-auto max-h-64 font-mono">
                {typeof result === "string"
                  ? result
                  : JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
