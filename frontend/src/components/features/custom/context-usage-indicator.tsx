// >>> CUSTOM: HiClaw <<<
import React from "react";
import useMetricsStore from "#/stores/metrics-store";

function formatNumber(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function ContextUsageIndicator() {
  const usage = useMetricsStore((s) => s.usage);

  if (!usage || !usage.context_window) return null;

  const used = usage.prompt_tokens + usage.completion_tokens;
  const total = usage.context_window;
  const percent = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const perTurn = usage.per_turn_token || 0;

  // Color based on usage
  let barColor = "bg-green-500";
  let textColor = "text-green-400";
  if (percent >= 80) {
    barColor = "bg-red-500";
    textColor = "text-red-400";
  } else if (percent >= 60) {
    barColor = "bg-yellow-500";
    textColor = "text-yellow-400";
  }

  return (
    <div className="flex items-center gap-2 px-2 py-1 rounded bg-neutral-800/50 border border-neutral-700 text-xs">
      <span className="text-neutral-400">Context</span>
      <div className="w-20 h-1.5 bg-neutral-700 rounded overflow-hidden">
        <div
          className={`h-full ${barColor} transition-all`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className={`font-mono ${textColor}`}>
        {percent}%
      </span>
      <span className="text-neutral-500 font-mono">
        {formatNumber(used)} / {formatNumber(total)}
      </span>
      {perTurn > 0 && (
        <span className="text-neutral-500 font-mono" title="Tokens this turn">
          (+{formatNumber(perTurn)})
        </span>
      )}
    </div>
  );
}
// >>> END CUSTOM <<<
