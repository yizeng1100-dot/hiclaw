// >>> CUSTOM: HiClaw — Agent report download <<<
// Platform-generic report download bar. Used to be hard-wired to the perf
// agent's two html files; now it discovers reports dynamically from the
// agent's workflow_phases so any new agent whose skill frontmatter declares
// an `output` path ending in `.html` automatically gets a download button.
//
// The component name is kept as PerfReportDownload for backwards
// compatibility with existing mount points, but it is no longer
// perf-specific.
import React from "react";
import V1ConversationService from "#/api/conversation-service/v1-conversation-service.api";
import { AgentService } from "#/api/custom-skill-service/agent-service.api";
import { TaskService } from "#/api/custom-skill-service/task-service.api";
import { downloadBlob } from "#/utils/utils";

interface ReportFile {
  label: string;
  path: string;
  filename: string;
}

interface WorkflowPhase {
  key?: string;
  label?: string;
  desc?: string;
  file?: string | null;
  output?: string | null;
  optional?: boolean;
}

interface AgentReportDecl {
  label?: string;
  file?: string;
}

// Keep absolute `/workspace/...` paths as-is — readConversationFile
// passes absolute paths straight through to the remote workspace, which
// matches how phase outputs actually live in the sandbox (e.g.
// /workspace/render_output/render_report.html). Relative paths get
// resolved against /workspace/project/<convHex>/ which is NOT where
// most skill outputs land, so stripping the prefix here would lead to
// false negatives (probe 404s the file and the download button never
// shows, even when the report exists).
function normalizeReportPath(raw: string): string {
  const p = raw.trim();
  if (p.startsWith("/")) return p;
  return p.replace(/^\.?\//, "");
}

function basename(p: string): string {
  const idx = p.lastIndexOf("/");
  return idx >= 0 ? p.slice(idx + 1) : p;
}

function collectReportFiles(
  reports: AgentReportDecl[] | undefined,
  phases: WorkflowPhase[],
): ReportFile[] {
  const seen = new Set<string>();
  const out: ReportFile[] = [];

  const pushIfNew = (path: string, label: string) => {
    if (seen.has(path)) return;
    seen.add(path);
    out.push({ label, path, filename: basename(path) });
  };

  // 1. Prefer the explicit `reports:` frontmatter list — one button
  //    per entry, order preserved. This is the skill's declared
  //    contract for downloadable deliverables.
  if (reports && reports.length > 0) {
    reports.forEach((r) => {
      const raw = r.file;
      if (!raw || typeof raw !== "string") return;
      const path = normalizeReportPath(raw);
      pushIfNew(path, r.label || basename(path));
    });
    if (out.length > 0) return out;
  }

  // 2. Fallback for skills that haven't declared `reports:` yet: scan
  //    workflow_phases for any phase whose `output`/`file` ends in
  //    `.html`. Gives every workflow-aware agent at least one button.
  phases.forEach((phase) => {
    const raw = phase.output ?? phase.file;
    if (!raw || typeof raw !== "string") return;
    if (!/\.html?$/i.test(raw)) return;
    const path = normalizeReportPath(raw);
    pushIfNew(path, phase.label ? `${phase.label}` : basename(path));
  });
  return out;
}

interface PerfReportDownloadProps {
  conversationId: string;
  /** Agent id whose workflow_phases declare the reports. */
  agentId?: string | null;
}

/**
 * Report download component — renders only when at least one `.html`
 * output declared by the agent's workflow_phases actually exists in the
 * conversation's working_dir.
 */
export function PerfReportDownload({
  conversationId,
  agentId,
}: PerfReportDownloadProps) {
  const [availableReports, setAvailableReports] = React.useState<ReportFile[]>(
    [],
  );
  const [downloading, setDownloading] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  // Resolve the effective agent id: (1) prop from parent (2) sessionStorage
  // (set by handleSelectAgent at launch) (3) reverse-lookup by convId via
  // the task-by-conversation endpoint. Without an id we cannot know which
  // reports to probe for, so the component renders nothing.
  const [resolvedAgentId, setResolvedAgentId] = React.useState<string | null>(
    () => agentId ?? sessionStorage.getItem("hiclaw_perf_agent_id"),
  );

  React.useEffect(() => {
    setResolvedAgentId(
      agentId ?? sessionStorage.getItem("hiclaw_perf_agent_id"),
    );
  }, [agentId, conversationId]);

  React.useEffect(() => {
    if (resolvedAgentId || !conversationId) return undefined;
    let cancelled = false;
    (async () => {
      const task = await TaskService.getByConversation(conversationId);
      if (cancelled || !task?.agent_id) return;
      setResolvedAgentId(task.agent_id);
    })();
    return () => {
      cancelled = true;
    };
  }, [resolvedAgentId, conversationId]);

  const effectiveAgentId = resolvedAgentId;

  React.useEffect(() => {
    if (!effectiveAgentId || !conversationId) {
      setAvailableReports([]);
      return undefined;
    }

    let cancelled = false;
    (async () => {
      // 1. Pull the agent's config_json. The backend overlays two
      //    relevant fields from the linked workflow skill frontmatter:
      //      - workflow_phases → phase progress
      //      - reports         → downloadable artifacts (this component)
      //    see agent_mgmt/router.get_agent + skill_mgmt/bridge.
      let phases: WorkflowPhase[] = [];
      let declaredReports: AgentReportDecl[] | undefined;
      try {
        const agent = await AgentService.getAgent(effectiveAgentId);
        const cfg =
          typeof agent.config_json === "string"
            ? JSON.parse(agent.config_json || "{}")
            : agent.config_json || {};
        phases = cfg?.workflow_phases ?? [];
        declaredReports = cfg?.reports;
      } catch {
        return;
      }

      const reports = collectReportFiles(declaredReports, phases);
      if (reports.length === 0) return;

      // 2. Probe the conversation's working_dir once per report. Reports
      //    that don't exist yet (agent still running, or phase skipped)
      //    just don't get a button.
      const checks = reports.map(async (report) => {
        try {
          const content = await V1ConversationService.readConversationFile(
            conversationId,
            report.path,
          );
          return content && content.length > 0 ? report : null;
        } catch {
          return null;
        }
      });
      const results = await Promise.all(checks);
      if (cancelled) return;
      setAvailableReports(results.filter((r): r is ReportFile => r !== null));
    })();

    return () => {
      cancelled = true;
    };
  }, [conversationId, effectiveAgentId]);

  const handleDownload = React.useCallback(
    async (report: ReportFile) => {
      setDownloading(report.filename);
      setError(null);
      try {
        const content = await V1ConversationService.readConversationFile(
          conversationId,
          report.path,
        );
        const blob = new Blob([content], { type: "text/html;charset=utf-8" });
        downloadBlob(blob, report.filename);
      } catch {
        setError(`下载失败: ${report.filename}`);
      } finally {
        setDownloading(null);
      }
    },
    [conversationId],
  );

  if (availableReports.length === 0) return null;

  return (
    <div className="mb-2 px-3 py-2 bg-[#161b22] border border-[#30363d] rounded-lg">
      <div className="flex items-center gap-2">
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#4ECDC4"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
        {/* eslint-disable-next-line i18next/no-literal-string */}
        <span className="text-xs text-[#4ECDC4] font-medium">
          分析报告已生成
        </span>
      </div>

      {error && <div className="mt-1.5 text-xs text-red-400">{error}</div>}

      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {availableReports.map((report) => (
          <button
            key={report.filename}
            type="button"
            onClick={() => handleDownload(report)}
            disabled={downloading === report.filename}
            className="text-xs px-2 py-1 rounded bg-[#4ECDC4]/15 text-[#4ECDC4] border border-[#4ECDC4]/30 hover:bg-[#4ECDC4]/25 disabled:opacity-50 transition-colors"
          >
            {downloading === report.filename
              ? "下载中..."
              : `⬇ ${report.label}`}
          </button>
        ))}
      </div>
    </div>
  );
}
// >>> END CUSTOM <<<
