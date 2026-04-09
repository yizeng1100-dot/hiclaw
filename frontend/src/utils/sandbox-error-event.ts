// >>> CUSTOM: HiClaw — sandbox error event constants <<<
// In a separate module so it can be imported by both axios setup
// and React components without pulling in the full axios instance.
export type SandboxErrorKind =
  | "sandbox_disconnected"
  | "sandbox_stale"
  | "sandbox_stopped";

export const SANDBOX_ERROR_EVENT = "hiclaw:sandbox-error";

export function dispatchSandboxError(kind: SandboxErrorKind) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(SANDBOX_ERROR_EVENT, { detail: { kind } }),
  );
}
// >>> END CUSTOM <<<
