/* eslint-disable no-nested-ternary, no-plusplus, consistent-return, i18next/no-literal-string */
// >>> CUSTOM: HiClaw — Phase progress right-side tab <<<
// Platform-driven phase progress panel (no LLM involvement).
// Reads workflow_phases from agent config, monitors phase files via SSE,
// and renders real-time progress with the same visual style as TaskListTab.
// Always visible in the right panel — shows empty state when no workflow is active.

import React from "react";
import { cn } from "#/utils/utils";
import { AgentService } from "#/api/custom-skill-service/agent-service.api";
import { useConversationId } from "#/hooks/use-conversation-id";
import { useAgentState } from "#/hooks/use-agent-state";

interface WorkflowPhase {
  key: string;
  label: string;
  desc: string;
  file: string | null;
  optional?: boolean;
}

function PhaseProgressTab() {
  const { conversationId } = useConversationId();
  const { curAgentState } = useAgentState();

  const [phases, setPhases] = React.useState<WorkflowPhase[]>([]);
  const [phasesDone, setPhasesDone] = React.useState<boolean[]>([]);

  // Read agentId from sessionStorage (set when user clicks "analyze" on an agent)
  const agentId = React.useMemo(
    () => sessionStorage.getItem("hiclaw_perf_agent_id"),
    [],
  );

  // Fetch workflow_phases from agent config
  React.useEffect(() => {
    if (!agentId) return;
    let cancelled = false;
    (async () => {
      try {
        const detail = await AgentService.getAgent(agentId);
        const config =
          typeof detail.config_json === "string"
            ? JSON.parse(detail.config_json)
            : detail.config_json;
        const p: WorkflowPhase[] = config?.workflow_phases ?? [];
        if (!cancelled && p.length > 0) {
          setPhases(p);
          setPhasesDone(p.map(() => false));
        }
      } catch {
        // Agent not found or no phases
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  // Subscribe to SSE phase-stream for real-time updates
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
        // ignore
      }
    };

    source.onerror = () => {
      source.close();
    };

    return () => source.close();
  }, [conversationId, phases]);

  // Determine phase status
  const isRunning =
    curAgentState === "running" ||
    curAgentState === "init" ||
    curAgentState === "loading";
  const isFinished =
    curAgentState === "finished" ||
    curAgentState === "stopped" ||
    curAgentState === "error";

  const getStatus = (i: number) => {
    if (phasesDone[i]) return "done";
    if (phases[i]?.optional && isFinished) return "skipped";
    const lastDoneIdx = phasesDone.lastIndexOf(true);
    if (isRunning && i === lastDoneIdx + 1 && !phases[i]?.optional)
      return "active";
    return "pending";
  };

  // Empty state
  if (phases.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center w-full h-full p-10 gap-4">
        <svg
          width="48"
          height="48"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#A1A1A1"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
        </svg>
        <span className="text-[#8D95A9] text-sm">暂无执行进度</span>
        <span className="text-[#555] text-xs">
          启动带工作流的 Agent 后，执行进度将在此实时展示
        </span>
      </div>
    );
  }

  const doneCount = phasesDone.filter(Boolean).length;

  return (
    <main className="h-full overflow-y-auto flex flex-col custom-scrollbar-always p-2">
      {/* Summary */}
      <div className="flex items-center justify-between px-2 py-1.5 mb-1">
        <span className="text-xs text-[#58a6ff] font-medium">
          {isFinished ? "执行完成" : isRunning ? "执行中" : "执行进度"}
        </span>
        <span className="text-xs text-gray-400">
          {doneCount}/{phases.length}
        </span>
      </div>

      {/* Phase list */}
      {phases.map((phase, i) => {
        const s = getStatus(i);
        return (
          <div key={phase.key} className="flex px-2">
            {/* Connector line */}
            <div className="flex flex-col items-center mr-2 w-5 shrink-0">
              {i > 0 && (
                <div
                  className={cn(
                    "w-0.5 h-2",
                    s === "done"
                      ? "bg-green-500"
                      : s === "active"
                        ? "bg-blue-500"
                        : s === "skipped"
                          ? "bg-amber-700/60"
                          : "bg-gray-700",
                  )}
                />
              )}
              {/* Node */}
              <div
                className={cn(
                  "w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold border-2 shrink-0",
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
              </div>
              {i < phases.length - 1 && (
                <div
                  className={cn(
                    "w-0.5 h-2",
                    s === "done"
                      ? "bg-green-500"
                      : s === "skipped"
                        ? "bg-amber-700/60"
                        : "bg-gray-700",
                  )}
                />
              )}
            </div>

            {/* Label */}
            <div
              className={cn(
                "flex-1 py-1",
                s === "active" && "bg-blue-900/20 rounded px-2 -mx-1",
              )}
            >
              <p
                className={cn(
                  "text-xs font-medium leading-tight",
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
              </p>
              <p className="text-[10px] text-gray-600 leading-tight">
                {phase.desc}
              </p>
            </div>
          </div>
        );
      })}
    </main>
  );
}

export default PhaseProgressTab;
// >>> END CUSTOM <<<
