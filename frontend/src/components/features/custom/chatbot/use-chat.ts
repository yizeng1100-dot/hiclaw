// HiClaw — Chat state + streaming driver (multi-session).
//
// Owns a list of chat sessions plus the live streaming state for the
// currently-selected one. Each session has its own messages array
// persisted separately so switching between sessions doesn't pay a
// full-blown JSON roundtrip for history that isn't being viewed.
//
// Storage layout in localStorage:
//   hiclaw_chat.sessions      → ChatSession[] (metadata only)
//   hiclaw_chat.session.{id}  → ChatMessage[] for that session
//   hiclaw_chat.current_id    → currently-active session id (string)
//
// Migration: on first load we look for the legacy
// ``hiclaw_chat_history`` key (used before multi-session existed) and
// convert whatever is there into a new session so users don't lose
// their ongoing conversation.

import React from "react";
import {
  ChatbotService,
  ChatMessage,
  ChatStreamEvent,
} from "#/api/custom-skill-service/chatbot-service.api";

const LS = {
  sessions: "hiclaw_chat.sessions",
  current: "hiclaw_chat.current_id",
  msgs: (id: string) => `hiclaw_chat.session.${id}`,
  legacy: "hiclaw_chat_history",
};

export interface ChatSession {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}

function generateId(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

function deriveTitle(firstUserMsg: string): string {
  const s = (firstUserMsg || "").trim().replace(/\s+/g, " ");
  if (!s) return "新对话";
  return s.length > 30 ? `${s.slice(0, 30)}…` : s;
}

function safeParse<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function loadSessions(): ChatSession[] {
  try {
    return safeParse<ChatSession[]>(localStorage.getItem(LS.sessions), []);
  } catch {
    return [];
  }
}

function saveSessions(sessions: ChatSession[]): void {
  try {
    localStorage.setItem(LS.sessions, JSON.stringify(sessions));
  } catch {
    /* quota exceeded — drop silently */
  }
}

function loadMessages(id: string): ChatMessage[] {
  try {
    return safeParse<ChatMessage[]>(localStorage.getItem(LS.msgs(id)), []);
  } catch {
    return [];
  }
}

function saveMessages(id: string, msgs: ChatMessage[]): void {
  try {
    localStorage.setItem(LS.msgs(id), JSON.stringify(msgs));
  } catch {
    /* quota exceeded — drop silently */
  }
}

function deleteMessagesStorage(id: string): void {
  try {
    localStorage.removeItem(LS.msgs(id));
  } catch {
    /* ignore */
  }
}

/**
 * Turn any pre-multi-session history into a single migrated session.
 * Runs at most once — after migration the legacy key is removed.
 */
function migrateLegacy(): {
  sessions: ChatSession[];
  currentId: string | null;
} {
  try {
    const legacyRaw = localStorage.getItem(LS.legacy);
    if (!legacyRaw) return { sessions: [], currentId: null };
    const legacyMsgs = safeParse<ChatMessage[]>(legacyRaw, []);
    if (!Array.isArray(legacyMsgs) || legacyMsgs.length === 0) {
      localStorage.removeItem(LS.legacy);
      return { sessions: [], currentId: null };
    }
    const id = generateId();
    const firstUser = legacyMsgs.find((m) => m.role === "user");
    const title = deriveTitle((firstUser?.content as string) || "");
    const now = new Date().toISOString();
    const session: ChatSession = {
      id,
      title,
      createdAt: now,
      updatedAt: now,
    };
    saveSessions([session]);
    saveMessages(id, legacyMsgs);
    localStorage.setItem(LS.current, id);
    localStorage.removeItem(LS.legacy);
    return { sessions: [session], currentId: id };
  } catch {
    return { sessions: [], currentId: null };
  }
}

export interface UseChatState {
  // Sessions
  sessions: ChatSession[];
  currentId: string | null;
  newSession: () => void;
  switchSession: (id: string) => void;
  deleteSession: (id: string) => void;
  // Current session state
  messages: ChatMessage[];
  streamingText: string;
  toolResults: Record<string, unknown>;
  runningToolIds: Set<string>;
  loading: boolean;
  error: string | null;
  sendMessage: (text: string) => Promise<void>;
}

export function useChat(): UseChatState {
  // Bootstrap: load existing sessions or migrate legacy history.
  const [sessions, setSessions] = React.useState<ChatSession[]>(() => {
    const existing = loadSessions();
    if (existing.length > 0) return existing;
    return migrateLegacy().sessions;
  });
  const [currentId, setCurrentId] = React.useState<string | null>(() => {
    const explicit = localStorage.getItem(LS.current);
    if (explicit) return explicit;
    const first = loadSessions()[0];
    return first?.id ?? null;
  });
  const [messages, setMessages] = React.useState<ChatMessage[]>(() =>
    currentId ? loadMessages(currentId) : [],
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

  // Persist sessions list whenever it changes.
  React.useEffect(() => {
    saveSessions(sessions);
  }, [sessions]);

  // Persist messages for the current session whenever they change.
  React.useEffect(() => {
    if (currentId) {
      saveMessages(currentId, messages);
    }
  }, [currentId, messages]);

  // Persist the active session id.
  React.useEffect(() => {
    try {
      if (currentId) {
        localStorage.setItem(LS.current, currentId);
      } else {
        localStorage.removeItem(LS.current);
      }
    } catch {
      /* ignore */
    }
  }, [currentId]);

  const resetTransientState = React.useCallback(() => {
    setStreamingText("");
    setRunningToolIds(new Set());
    setToolResults({});
    setError(null);
  }, []);

  const newSession = React.useCallback(() => {
    const id = generateId();
    const now = new Date().toISOString();
    const session: ChatSession = {
      id,
      title: "新对话",
      createdAt: now,
      updatedAt: now,
    };
    setSessions((prev) => [session, ...prev]);
    setCurrentId(id);
    setMessages([]);
    resetTransientState();
  }, [resetTransientState]);

  const switchSession = React.useCallback(
    (id: string) => {
      if (id === currentId) return;
      setCurrentId(id);
      setMessages(loadMessages(id));
      resetTransientState();
    },
    [currentId, resetTransientState],
  );

  const deleteSession = React.useCallback(
    (id: string) => {
      deleteMessagesStorage(id);
      setSessions((prev) => {
        const next = prev.filter((s) => s.id !== id);
        if (currentId === id) {
          if (next.length > 0) {
            setCurrentId(next[0].id);
            setMessages(loadMessages(next[0].id));
          } else {
            setCurrentId(null);
            setMessages([]);
          }
          resetTransientState();
        }
        return next;
      });
    },
    [currentId, resetTransientState],
  );

  const sendMessage = React.useCallback(
    async (text: string) => {
      if (!text.trim() || loading) return;

      // Ensure a session exists. If not, create one on the fly so the
      // very first message from a brand-new install lands in a fresh
      // session without the user having to click "新对话" first.
      let sessionId = currentId;
      if (!sessionId) {
        sessionId = generateId();
        const now = new Date().toISOString();
        setSessions((prev) => [
          {
            id: sessionId as string,
            title: deriveTitle(text),
            createdAt: now,
            updatedAt: now,
          },
          ...prev,
        ]);
        setCurrentId(sessionId);
      }

      setError(null);
      setStreamingText("");
      setRunningToolIds(new Set());

      const userMsg: ChatMessage = { role: "user", content: text };
      const withUser = [...messages, userMsg];
      setMessages(withUser);
      setLoading(true);

      // Update session title from the first user message, or just bump
      // updatedAt for subsequent messages.
      const isFirstUserMsg =
        messages.filter((m) => m.role === "user").length === 0;
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== sessionId) return s;
          const nowIso = new Date().toISOString();
          if (isFirstUserMsg || s.title === "新对话") {
            return { ...s, title: deriveTitle(text), updatedAt: nowIso };
          }
          return { ...s, updatedAt: nowIso };
        }),
      );

      try {
        for await (const evt of ChatbotService.stream(
          withUser,
        ) as AsyncGenerator<ChatStreamEvent>) {
          if (evt.type === "token") {
            setStreamingText((prev) => prev + evt.text);
          } else if (evt.type === "assistant_end") {
            setStreamingText("");
          } else if (evt.type === "tool_call") {
            setRunningToolIds((prev) => {
              const next = new Set(prev);
              next.add(evt.call.id);
              return next;
            });
          } else if (evt.type === "tool_result") {
            setToolResults((prev) => ({
              ...prev,
              [evt.call_id]: evt.result,
            }));
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
    [messages, loading, currentId],
  );

  return {
    sessions,
    currentId,
    newSession,
    switchSession,
    deleteSession,
    messages,
    streamingText,
    toolResults,
    runningToolIds,
    loading,
    error,
    sendMessage,
  };
}
