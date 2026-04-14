// HiClaw — Chatbot streaming client.
// Uses fetch() with a ReadableStream reader to consume SSE frames from
// POST /api/v1/chat/stream. EventSource is not usable because we need
// to POST a JSON body and EventSource only supports GET.

export type ChatRole = "user" | "assistant" | "system" | "tool";

export interface ChatToolCall {
  id: string;
  type?: string;
  function: {
    name: string;
    arguments: string; // JSON string
  };
}

export interface ChatMessage {
  role: ChatRole;
  content?: string | null;
  tool_calls?: ChatToolCall[];
  tool_call_id?: string;
  name?: string;
}

// ─── Stream event shapes (match custom/chatbot/executor.py) ─────────

export type ChatStreamEvent =
  | { type: "token"; text: string }
  | { type: "assistant_end"; message: ChatMessage }
  | {
      type: "tool_call";
      call: {
        id: string;
        name: string;
        arguments: Record<string, unknown>;
      };
    }
  | {
      type: "tool_result";
      call_id: string;
      name: string;
      result: unknown;
    }
  | { type: "done"; messages: ChatMessage[] }
  | { type: "error"; message: string };

/**
 * Stream a chat request to the backend and yield events as they arrive.
 *
 * Usage:
 *   for await (const event of ChatbotService.stream(messages)) {
 *     // handle event
 *   }
 */
// eslint-disable-next-line import/prefer-default-export
export class ChatbotService {
  /* eslint-disable no-await-in-loop, no-cond-assign, no-continue */
  static async *stream(
    messages: ChatMessage[],
    signal?: AbortSignal,
  ): AsyncGenerator<ChatStreamEvent, void, undefined> {
    const resp = await fetch("/api/v1/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ messages }),
      signal,
    });

    if (!resp.ok) {
      throw new Error(`chatbot stream failed: ${resp.status}`);
    }
    if (!resp.body) {
      throw new Error("chatbot stream returned no body");
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    // Parse SSE: records are separated by blank lines; each record has
    // one or more "data: <json>" lines. Collect until we see the blank
    // line, then dispatch.
    while (true) {
      const { done, value } = await reader.read();
      if (done) return;
      // sse_starlette emits CRLF line endings, so normalize to LF before
      // splitting on the blank-line record separator.
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      let sepIdx;
      while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
        const record = buffer.slice(0, sepIdx);
        buffer = buffer.slice(sepIdx + 2);

        // Extract all "data:" lines in this record and join.
        const dataLines: string[] = [];
        for (const line of record.split("\n")) {
          if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).trim());
          }
        }
        if (dataLines.length === 0) continue;
        const dataStr = dataLines.join("\n");
        if (!dataStr) continue;
        try {
          const event = JSON.parse(dataStr) as ChatStreamEvent;
          yield event;
          if (event.type === "done") return;
        } catch {
          // Malformed frame — ignore and keep going
        }
      }
    }
  }
}
