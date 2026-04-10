import axios, { AxiosError, AxiosResponse } from "axios";
// >>> CUSTOM: HiClaw <<<
import { dispatchSandboxError } from "#/utils/sandbox-error-event";
// >>> END CUSTOM <<<

export const openHands = axios.create({
  baseURL: `${window.location.protocol}//${import.meta.env.VITE_BACKEND_BASE_URL || window?.location.host}`,
});

// Helper function to check if a response contains an email verification error
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const checkForEmailVerificationError = (data: any): boolean => {
  const EMAIL_NOT_VERIFIED = "EmailNotVerifiedError";

  if (typeof data === "string") {
    return data.includes(EMAIL_NOT_VERIFIED);
  }

  if (typeof data === "object" && data !== null) {
    if ("message" in data) {
      const { message } = data;
      if (typeof message === "string") {
        return message.includes(EMAIL_NOT_VERIFIED);
      }
      if (Array.isArray(message)) {
        return message.some(
          (msg) => typeof msg === "string" && msg.includes(EMAIL_NOT_VERIFIED),
        );
      }
    }

    // Search any values in object in case message key is different
    return Object.values(data).some(
      (value) =>
        (typeof value === "string" && value.includes(EMAIL_NOT_VERIFIED)) ||
        (Array.isArray(value) &&
          value.some(
            (v) => typeof v === "string" && v.includes(EMAIL_NOT_VERIFIED),
          )),
    );
  }

  return false;
};

// >>> CUSTOM: HiClaw — re-export for backward compat <<<
export {
  SANDBOX_ERROR_EVENT,
  type SandboxErrorKind,
} from "#/utils/sandbox-error-event";
// >>> END CUSTOM <<<

// Set up the global interceptor
openHands.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError) => {
    // Check if it's a 403 error with the email verification message
    if (
      error.response?.status === 403 &&
      checkForEmailVerificationError(error.response?.data)
    ) {
      if (window.location.pathname !== "/settings/user") {
        window.location.reload();
      }
    }

    // >>> CUSTOM: HiClaw — surface sandbox disconnect errors as a global event <<<
    const status = error.response?.status;
    const data = error.response?.data as { error?: string } | undefined;
    if (status === 410 && data?.error === "sandbox_disconnected") {
      dispatchSandboxError("sandbox_disconnected");
    } else if (status === 503 && data?.error === "sandbox_stale") {
      dispatchSandboxError("sandbox_stale");
    }
    // >>> END CUSTOM <<<

    // Continue with the error for other error handlers
    return Promise.reject(error);
  },
);
