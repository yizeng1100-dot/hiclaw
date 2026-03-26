// >>> CUSTOM: HiClaw — Performance report download <<<
import React from "react";
import V1ConversationService from "#/api/conversation-service/v1-conversation-service.api";
import { downloadBlob } from "#/utils/utils";

interface ReportFile {
  label: string;
  path: string;
  filename: string;
}

const REPORT_FILES: ReportFile[] = [
  {
    label: "完整报告 (Full Report)",
    path: "/workspace/perf_analysis_output/full_report.html",
    filename: "full_report.html",
  },
  {
    label: "问题报告 (Issue Report)",
    path: "/workspace/perf_analysis_output/issue_report.html",
    filename: "issue_report.html",
  },
];

interface PerfReportDownloadProps {
  conversationId: string;
}

/**
 * Report download component — renders only when reports exist.
 * Used in chat box (after agent finishes) and task center/detail pages.
 */
export function PerfReportDownload({
  conversationId,
}: PerfReportDownloadProps) {
  const [availableReports, setAvailableReports] = React.useState<ReportFile[]>(
    [],
  );
  const [downloading, setDownloading] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  // Check once on mount which reports exist
  React.useEffect(() => {
    let cancelled = false;

    (async () => {
      const checks = REPORT_FILES.map(async (report) => {
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
      const found = results.filter((r): r is ReportFile => r !== null);
      if (!cancelled) setAvailableReports(found);
    })();

    return () => {
      cancelled = true;
    };
  }, [conversationId]);

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
          性能分析报告已生成
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
