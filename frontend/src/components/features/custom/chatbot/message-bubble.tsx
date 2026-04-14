/* eslint-disable i18next/no-literal-string, no-nested-ternary */
// HiClaw — One message bubble in the chatbot message list.
//
// Renders one of three states based on role:
//   - user:      right-aligned blue bubble, plain text
//   - assistant: left-aligned gray bubble with markdown rendering +
//                inline tool_call chips (if any)
//   - tool:      hidden (tool results render inside the preceding
//                assistant bubble via ToolCallChip)

import React from "react";
import { MarkdownRenderer } from "#/components/features/markdown/markdown-renderer";
import {
  ChatMessage,
  ChatToolCall,
} from "#/api/custom-skill-service/chatbot-service.api";
import { cn } from "#/utils/utils";
import { ToolCallChip } from "./tool-call-chip";

function parseArgs(raw: string): Record<string, unknown> {
  try {
    return JSON.parse(raw || "{}");
  } catch {
    return {};
  }
}

interface MessageBubbleProps {
  message: ChatMessage;
  /** Tool results keyed by tool_call_id, collected from sibling tool messages. */
  toolResults?: Record<string, unknown>;
  /** Tool calls whose result hasn't arrived yet (still running). */
  runningToolIds?: Set<string>;
}

export function MessageBubble({
  message,
  toolResults = {},
  runningToolIds = new Set(),
}: MessageBubbleProps) {
  if (message.role === "tool") return null;

  const isUser = message.role === "user";
  const content = typeof message.content === "string" ? message.content : "";

  return (
    <div
      className={cn(
        "flex w-full mb-3",
        isUser ? "justify-end" : "justify-start",
      )}
    >
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-3 text-sm",
          isUser
            ? "bg-[#1f6feb] text-white"
            : "bg-[#161b22] border border-[#30363d] text-gray-200",
        )}
      >
        {content && (
          <div className={cn(isUser ? "whitespace-pre-wrap" : "chat-markdown")}>
            {isUser ? (
              content
            ) : (
              <MarkdownRenderer
                content={content}
                includeStandard
                includeHeadings
              />
            )}
          </div>
        )}

        {!isUser && message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mt-2">
            {message.tool_calls.map((call: ChatToolCall) => (
              <ToolCallChip
                key={call.id}
                name={call.function.name}
                args={parseArgs(call.function.arguments)}
                result={toolResults[call.id]}
                running={runningToolIds.has(call.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
