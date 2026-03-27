// >>> CUSTOM: HiClaw — machine provisioning progress panel <<<
// Uses the same icon/style pattern as OpenHands TaskItem component
import React from "react";
import CircleIcon from "#/icons/u-circle.svg?react";
import CheckCircleIcon from "#/icons/u-check-circle.svg?react";
import LoadingIcon from "#/icons/loading.svg?react";
import ErrorIcon from "#/icons/circle-error.svg?react";
import { Typography } from "#/ui/typography";
import { cn } from "#/utils/utils";
import { useRemoteWorkerStore, type ProvisionEvent } from "#/stores/remote-worker-store";

const STEP_LABELS: Record<string, string> = {
  ssh_connect: "SSH Connection",
  check_python: "Checking Python",
  install_python: "Installing Python",
  check_agent_sdk: "Checking Agent SDK",
  install_agent_sdk: "Installing Agent SDK",
  check_code_server: "Checking VS Code Server",
  install_code_server: "Installing VS Code Server",
  scp_dependencies: "Uploading Dependencies",
  clone_skills: "Syncing Skills",
  start_agent_server: "Starting Agent Server",
  health_check: "Health Check",
  setup_tunnel: "Setting Up Tunnel",
};

const BASE_STEPS = [
  "ssh_connect",
  "check_python",
  "scp_dependencies",
  "install_agent_sdk",
  "install_code_server",
  "clone_skills",
  "start_agent_server",
  "health_check",
  "setup_tunnel",
];

type StepStatus = "todo" | "in_progress" | "done" | "skipped" | "failed";

function mapStatus(event?: ProvisionEvent): StepStatus {
  if (!event) return "todo";
  if (event.status === "completed" || event.status === "skipped") return "done";
  if (event.status === "started") return "in_progress";
  if (event.status === "failed") return "failed";
  return "todo";
}

function StepIcon({ status }: { status: StepStatus }) {
  switch (status) {
    case "done":
      return <CheckCircleIcon className="w-4 h-4 text-[#A3A3A3]" />;
    case "in_progress":
      return <LoadingIcon className="w-4 h-4 text-white animate-spin" />;
    case "failed":
      return <ErrorIcon className="w-4 h-4 text-red-400" />;
    default:
      return <CircleIcon className="w-4 h-4 text-[#525252]" />;
  }
}

function ProvisionStepItem({
  label,
  status,
  detail,
}: {
  label: string;
  status: StepStatus;
  detail?: string;
}) {
  return (
    <div className="flex gap-2 items-center w-full py-0.5" data-name="provision-step">
      <div className="shrink-0">
        <StepIcon status={status} />
      </div>
      <div className="flex flex-col items-start justify-center leading-[16px]">
        <Typography.Text
          className={cn(
            "text-[12px]",
            status === "done" ? "text-[#A3A3A3]" :
            status === "failed" ? "text-red-400" :
            status === "in_progress" ? "text-white" :
            "text-[#525252]",
          )}
        >
          {label}
        </Typography.Text>
        {detail && (
          <Typography.Text className="text-[10px] text-[#A3A3A3]">
            {detail}
          </Typography.Text>
        )}
      </div>
    </div>
  );
}

export function MachineProvisioningPanel() {
  const { machineStatus, provisionEvents, error } = useRemoteWorkerStore();
  const logRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [provisionEvents]);

  if (!machineStatus) return null;

  // Build step status map — last event per step wins
  const stepStatus: Record<string, ProvisionEvent> = {};
  for (const evt of provisionEvents) {
    stepStatus[evt.step] = evt;
  }

  // Determine visible steps and their status
  const steps = BASE_STEPS.map((step) => {
    // Check if install variant exists (e.g., install_python for check_python)
    const installKey = step.replace("check_", "install_");
    const evt = stepStatus[step] || stepStatus[installKey];
    const displayStep = stepStatus[installKey] ? installKey : step;
    return {
      key: step,
      label: STEP_LABELS[displayStep] || displayStep,
      status: mapStatus(evt),
      detail: evt?.detail || "",
    };
  });

  const doneCount = steps.filter((s) => s.status === "done").length;
  const progressPct = steps.length > 0 ? Math.round((doneCount / steps.length) * 100) : 0;

  return (
    <div className="flex flex-col gap-3">
      {/* Progress bar — same style as OpenHands conversation loading */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <Typography.Text className={cn(
            "text-[12px] font-medium",
            machineStatus === "ready" ? "text-[#A3A3A3]" :
            machineStatus === "error" ? "text-red-400" :
            "text-white",
          )}>
            {machineStatus === "ready" ? "Connected" :
             machineStatus === "error" ? "Failed" :
             `Deploying... ${progressPct}%`}
          </Typography.Text>
          <Typography.Text className="text-[10px] text-[#A3A3A3]">
            {doneCount}/{steps.length}
          </Typography.Text>
        </div>
        <div className="h-[3px] bg-[#27272A] rounded-full overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              machineStatus === "ready" ? "bg-[#A3A3A3]" :
              machineStatus === "error" ? "bg-red-500" :
              "bg-white",
            )}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Step list — same pattern as TaskItem */}
      <div className="flex flex-col">
        {steps.map((step) => (
          <ProvisionStepItem
            key={step.key}
            label={step.label}
            status={step.status}
            detail={step.detail}
          />
        ))}
      </div>

      {/* Log output */}
      {provisionEvents.length > 0 && (
        <div>
          <Typography.Text className="text-[10px] text-[#A3A3A3] mb-1 block">
            Logs
          </Typography.Text>
          <div
            ref={logRef}
            className="bg-[#0A0A0A] border border-[#27272A] rounded-lg p-2 max-h-[100px] overflow-y-auto font-mono text-[10px] text-[#A3A3A3] custom-scrollbar"
          >
            {provisionEvents.map((evt, i) => (
              <div key={i} className={cn(
                evt.status === "failed" ? "text-red-400" :
                evt.status === "completed" ? "text-[#525252]" :
                "text-[#A3A3A3]",
              )}>
                <span className="text-[#3F3F46]">
                  [{new Date(evt.timestamp).toLocaleTimeString()}]
                </span>
                {" "}{STEP_LABELS[evt.step] || evt.step}: {evt.status}
                {evt.detail ? ` — ${evt.detail}` : ""}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="p-2 bg-[#1C1917] border border-[#7F1D1D] rounded-lg">
          <Typography.Text className="text-[12px] text-red-400">
            {error}
          </Typography.Text>
        </div>
      )}
    </div>
  );
}
// >>> END CUSTOM <<<
