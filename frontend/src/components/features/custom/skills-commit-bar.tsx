// >>> CUSTOM: HiClaw — skills change detection + commit bar <<<
import React from "react";
import CheckCircleIcon from "#/icons/u-check-circle.svg?react";
import LoadingIcon from "#/icons/loading.svg?react";
import { Typography } from "#/ui/typography";
import { cn } from "#/utils/utils";
import { useRemoteWorkerStore } from "#/stores/remote-worker-store";
import axios from "axios";

interface SkillFile {
  status: string;
  path: string;
}

interface DiffResult {
  has_changes: boolean;
  files: SkillFile[];
  diff: string;
}

export function SkillsCommitBar() {
  const { enabled, machineStatus } = useRemoteWorkerStore();
  const workerManagerUrl = useRemoteWorkerStore((s) => s.workerManagerUrl);
  const [diffResult, setDiffResult] = React.useState<DiffResult | null>(null);
  const [showDiff, setShowDiff] = React.useState(false);
  const [committing, setCommitting] = React.useState(false);
  const [committed, setCommitted] = React.useState(false);

  // Poll for skill changes every 10 seconds
  React.useEffect(() => {
    if (!enabled || machineStatus !== "ready") return;

    const checkDiff = async () => {
      try {
        // Get machine ID
        const machinesResp = await axios.get(`${workerManagerUrl}/api/machines`);
        const machine = machinesResp.data?.find?.(
          (m: { status: string }) => m.status === "ready",
        );
        if (!machine) return;

        const resp = await axios.get(
          `${workerManagerUrl}/api/machines/${machine.id}/skills/diff`,
        );
        setDiffResult(resp.data);
        if (!resp.data.has_changes) setCommitted(false);
      } catch {
        /* ignore polling errors */
      }
    };

    checkDiff();
    const interval = setInterval(checkDiff, 10000);
    return () => clearInterval(interval);
  }, [enabled, machineStatus]);

  const handleCommit = async () => {
    setCommitting(true);
    try {
      const machinesResp = await axios.get(`${workerManagerUrl}/api/machines`);
      const machine = machinesResp.data?.find?.(
        (m: { status: string }) => m.status === "ready",
      );
      if (!machine) return;

      await axios.post(
        `${workerManagerUrl}/api/machines/${machine.id}/skills/commit`,
        { message: `Update skills: ${diffResult?.files.map((f) => f.path).join(", ")}` },
      );
      setCommitted(true);
      setDiffResult(null);
      setShowDiff(false);
    } catch (e) {
      console.error("Commit failed:", e);
    } finally {
      setCommitting(false);
    }
  };

  // Don't render if no changes or not remote
  if (!enabled || machineStatus !== "ready") return null;
  if (!diffResult?.has_changes && !committed) return null;

  // Just committed — show success briefly
  if (committed && !diffResult?.has_changes) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 bg-[#1A2E1A] border border-[#2D5A2D] rounded-lg mx-4 mb-2">
        <CheckCircleIcon className="w-3.5 h-3.5 text-green-500" />
        <Typography.Text className="text-[11px] text-green-400">
          Skills synced to server
        </Typography.Text>
      </div>
    );
  }

  if (!diffResult?.has_changes) return null;

  const filesSummary = diffResult.files
    .map((f) => {
      const icon = f.status === "??" ? "+" : f.status === "D" ? "-" : "~";
      return `${icon}${f.path}`;
    })
    .join(", ");

  return (
    <div className="mx-4 mb-2">
      {/* Commit bar */}
      <div className="flex items-center justify-between px-3 py-2 bg-[#25272D] border border-[#474A54] rounded-lg">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[11px]">📝</span>
          <Typography.Text className="text-[11px] text-[#A3A3A3] truncate">
            Skills modified: {filesSummary}
          </Typography.Text>
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-2">
          <button
            type="button"
            onClick={() => setShowDiff(!showDiff)}
            className="px-2 py-0.5 text-[11px] text-[#A3A3A3] hover:text-white border border-[#474A54] rounded transition-colors"
          >
            {showDiff ? "Hide" : "Review"}
          </button>
          <button
            type="button"
            onClick={handleCommit}
            disabled={committing}
            className={cn(
              "px-3 py-0.5 text-[11px] font-medium rounded transition-colors",
              committing
                ? "bg-[#3F3F46] text-[#A3A3A3]"
                : "bg-white text-black hover:bg-[#E5E5E5]",
            )}
          >
            {committing ? (
              <span className="flex items-center gap-1">
                <LoadingIcon className="w-3 h-3 animate-spin" />
                Syncing
              </span>
            ) : (
              "Commit"
            )}
          </button>
        </div>
      </div>

      {/* Diff preview */}
      {showDiff && diffResult.diff && (
        <div className="mt-1 bg-[#0A0A0A] border border-[#27272A] rounded-lg p-2 max-h-[200px] overflow-auto">
          <pre className="font-mono text-[10px] text-[#A3A3A3] whitespace-pre-wrap">
            {diffResult.diff}
          </pre>
        </div>
      )}
    </div>
  );
}
// >>> END CUSTOM <<<
