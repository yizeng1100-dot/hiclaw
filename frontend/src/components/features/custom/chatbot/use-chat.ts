// HiClaw — Chat state + streaming driver.
//
// Owns the messages array, per-message tool-result map, and the
// streaming session lifecycle. Persists everything to localStorage
// under ``hiclaw_chat_history`` so a page refresh doesn't wipe the
// conversation.
//
// The hook consumes ChatbotService.stream() events:
//   - token:           append to current in-flight assistant content
//   - assistant_end:   the current assistant message (with tool_calls)
//                      is finalized — append to messages list
//   - tool_call:       mark the tool as running
//   - tool_result:     record the result under its call_id
//   - done:            replace the entire messages array with the
//                      authoritative history from the backend so any
//                      tool messages land correctly
//   - error:           surface to caller

import React from "react";
import {
  ChatbotService,
  ChatMessage,
  ChatStreamEvent,
} from "#/api/custom-skill-service/chatbot-service.api";

const STORAGE_KEY = "hiclaw_chat_history";

function loadFromStorage(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed as ChatMessage[];
  } catch {
    /* ignore */
  }
  return [];
}

function saveToStorage(messages: ChatMessage[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  } catch {
    /* quota exceeded — drop silently */
  }
}

export interface UseChatState {
  messages: ChatMessage[];
  /** Partial assistant text during a streaming turn. */
  streamingText: string;
  /** Tool results keyed by tool_call_id. */
  toolResults: Record<string, unknown>;
  runningToolIds: Set<string>;
  loading: boolean;
  error: string | null;
  sendMessage: (text: string) => Promise<void>;
  clear: () => void;
}

export function useChat(): UseChatState {
  const [messages, setMessages] = React.useState<ChatMessage[]>(() =>
    loadFromStorage(),
  );
  const [streamingText, setStreamingText] = React.useState("");
  const [toolResults, setToolResults] = React.useState<Record<string, unknown>>(
    {},
  );
  const [runningToolIds, setRunningToolIds] = React.useState<Set<string>>(
    new Set(),
  );
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    saveToStorage(messages);
  }, [messages]);

  const sendMessage = React.useCallback(
    async (text: string) => {
      if (!text.trim() || loading) return;
      setError(null);
      setStreamingText("");
      setRunningToolIds(new Set());

      const userMsg: ChatMessage = { role: "user", content: text };
      const withUser = [...messages, userMsg];
      setMessages(withUser);
      setLoading(true);

      try {
        for await (const evt of ChatbotService.stream(
          withUser,
        ) as AsyncGenerator<ChatStreamEvent>) {
          if (evt.type === "token") {
            setStreamingText((prev) => prev + evt.text);
          } else if (evt.type === "assistant_end") {
            // Clear streaming buffer; the backend will emit the final
            // authoritative messages array in the "done" event.
            setStreamingText("");
          } else if (evt.type === "tool_call") {
            setRunningToolIds((prev) => {
              const next = new Set(prev);
              next.add(evt.call.id);
              return next;
            });
          } else if (evt.type === "tool_result") {
            setToolResults((prev) => ({ ...prev, [evt.call_id]: evt.result }));
            setRunningToolIds((prev) => {
              const next = new Set(prev);
              next.delete(evt.call_id);
              return next;
            });
          } else if (evt.type === "done") {
            setMessages(evt.messages);
            setStreamingText("");
            setRunningToolIds(new Set());
          } else if (evt.type === "error") {
            setError(evt.message);
          }
        }
      } catch (e: unknown) {
        const err = e as { message?: string };
        setError(err?.message || "chat request failed");
      } finally {
        setLoading(false);
      }
    },
    [messages, loading],
  );

  const clear = React.useCallback(() => {
    setMessages([]);
    setToolResults({});
    setStreamingText("");
    setRunningToolIds(new Set());
    setError(null);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  return {
    messages,
    streamingText,
    toolResults,
    runningToolIds,
    loading,
    error,
    sendMessage,
    clear,
  };
}
