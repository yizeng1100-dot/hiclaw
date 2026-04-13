/* eslint-disable no-nested-ternary, no-plusplus, consistent-return, i18next/no-literal-string */
// >>> CUSTOM: HiClaw — Conversation phase progress indicator <<<
// Compact horizontal progress bar showing real-time workflow phase status.
// Designed as a standalone component — can be mounted in the chat box (position A)
// or in a dedicated panel alongside the planner (position B) by just changing
// the mount point. Only renders when at least one phase file exists (i.e. the
// conversation is running a workflow with known phases).
import React from "react";
import { cn } from "#/utils/utils";
import { AgentService } from "#/api/custom-skill-service/agent-service.api";

interface WorkflowPhase {
  key: string;
  label: string;
  desc: string;
  file: string | null;
  optional?: boolean;
}

interface ConvPhaseProgressProps {
  conversationId: string;
  agentState?: string; // "running" | "finished" | "stopped" | "error" etc
  agentId?: string; // If known, fetch phases directly from this agent
}

export function ConvPhaseProgress({
  conversationId,
  agentState,
  agentId,
}: ConvPhaseProgressProps) {
  const [phases, setPhases] = React.useState<WorkflowPhase[]>([]);
  const [phasesDone, setPhasesDone] = React.useState<boolean[]>([]);
  const [expanded, setExpanded] = React.useState(false);

  // Fetch workflow_phases for this conversation's agent.
  // Priority: (1) use agentId prop directly, (2) fallback: find agent with most phases.
  React.useEffect(() => {
    let cancelled = false;
    const extractPhases = (configJson: string | null): WorkflowPhase[] => {
      if (!configJson) return [];
      try {
        const config = JSON.parse(configJson);
        return config?.workflow_phases ?? [];
      } catch {
        return [];
      }
    };

    (async () => {
      if (!agentId) return; // No agent — no phases to show
      try {
        const detail = await AgentService.getAgent(agentId);
        const p = extractPhases(detail.config_json);
        if (!cancelled && p.length > 0) {
          setPhases(p);
          setPhasesDone(p.map(() => false));
        }
      } catch {
        // Agent fetch failed — don't render
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  // Subscribe to phase progress via SSE (server pushes only on change, no frontend polling)
  React.useEffect(() => {
    if (!conversationId || phases.length === 0) return;

    const fileList = phases
      .map((p) => p.file)
      .filter(Boolean)
      .join(",");
    if (!fileList) return;

    const url = `/api/v1/app-conversations/${conversationId}/phase-stream?files=${encodeURIComponent(fileList)}`;
    const source = new EventSource(url);

    source.onmessage = (event) => {
      try {
        const data: Record<string, boolean> = JSON.parse(event.data);
        if (data._done) {
          source.close();
          return;
        }
        const results = phases.map((p) => (p.file ? !!data[p.file] : false));
        // Phases without file (like cleanup): done if next phase is done
        for (let i = 0; i < results.length - 1; i++) {
          if (!phases[i].file && results[i + 1]) results[i] = true;
        }
        setPhasesDone(results);
      } catch {
        // ignore malformed events
      }
    };

    source.onerror = () => {
      // SSE connection lost (sandbox stopped, conv ended, etc.)
      // Don't retry — the component will stay at last known state
      source.close();
    };

    return () => source.close();
  }, [conversationId, phases]);

  // Don't render if no phases or nothing has started
  const anyDone = phasesDone.some(Boolean);
  const isRunning =
    agentState === "running" ||
    agentState === "init" ||
    agentState === "loading";
  if (phases.length === 0 || (!anyDone && !isRunning)) return null;

  const doneCount = phasesDone.filter(Boolean).length;
  const total = phases.length;
  const isFinished =
    agentState === "finished" ||
    agentState === "stopped" ||
    agentState === "error";

  const getStatus = (i: number) => {
    if (phasesDone[i]) return "done";
    if (phases[i]?.optional && isFinished) return "skipped";
    const lastDoneIdx = phasesDone.lastIndexOf(true);
    if (isRunning && i === lastDoneIdx + 1 && !phases[i]?.optional)
      return "active";
    return "pending";
  };

  return (
    <div className="mb-2 px-3 py-2 bg-[#161b22] border border-[#30363d] rounded-lg">
      {/* Header row — always visible */}
      <button
        type="button"
        className="w-full flex items-center justify-between text-xs"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span className="text-[#58a6ff] font-medium">
            {isFinished ? "执行完成" : "执行进度"}
          </span>
          <span className="text-gray-400">
            {doneCount}/{total}
          </span>
        </div>

        {/* Compact dot row */}
        <div className="flex items-center gap-1">
          {phases.map((phase, i) => {
            const s = getStatus(i);
            return (
              <div
                key={phase.key}
                title={`${phase.label}: ${s === "done" ? "完成" : s === "active" ? "执行中" : s === "skipped" ? "跳过" : "等待"}`}
                className={cn(
                  "w-2 h-2 rounded-full",
                  s === "done"
                    ? "bg-green-500"
                    : s === "active"
                      ? "bg-blue-500 animate-pulse"
                      : s === "skipped"
                        ? "bg-amber-500"
                        : "bg-gray-600",
                )}
              />
            );
          })}
          <span className="ml-1 text-gray-500">{expanded ? "▴" : "▾"}</span>
        </div>
      </button>

      {/* Expanded detail — vertical list */}
      {expanded && (
        <div className="mt-2 flex flex-col gap-0.5">
          {phases.map((phase, i) => {
            const s = getStatus(i);
            return (
              <div
                key={phase.key}
                className="flex items-center gap-2 text-xs py-0.5"
              >
                <span
                  className={cn(
                    "w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold border shrink-0",
                    s === "done"
                      ? "bg-green-900/50 border-green-500 text-green-400"
                      : s === "active"
                        ? "bg-blue-900/50 border-blue-500 text-blue-400 animate-pulse"
                        : s === "skipped"
                          ? "bg-amber-900/30 border-amber-700 text-amber-500"
                          : "bg-gray-800 border-gray-600 text-gray-500",
                  )}
                >
                  {s === "done"
                    ? "✓"
                    : s === "active"
                      ? "●"
                      : s === "skipped"
                        ? "⊘"
                        : i + 1}
                </span>
                <span
                  className={cn(
                    s === "done"
                      ? "text-green-400"
                      : s === "active"
                        ? "text-blue-400"
                        : s === "skipped"
                          ? "text-amber-500"
                          : "text-gray-500",
                  )}
                >
                  {phase.label}
                </span>
                <span className="text-gray-600 truncate">{phase.desc}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
// >>> END CUSTOM <<<
