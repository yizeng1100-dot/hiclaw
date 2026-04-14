/* eslint-disable i18next/no-literal-string */
// HiClaw — Scrolling list of chat bubbles + streaming draft bubble.

import React from "react";
import { ChatMessage } from "#/api/custom-skill-service/chatbot-service.api";
import { MessageBubble } from "./message-bubble";

interface MessageListProps {
  messages: ChatMessage[];
  streamingText: string;
  toolResults: Record<string, unknown>;
  runningToolIds: Set<string>;
  loading: boolean;
}

export function MessageList({
  messages,
  streamingText,
  toolResults,
  runningToolIds,
  loading,
}: MessageListProps) {
  const bottomRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streamingText]);

  const showEmpty = messages.length === 0 && !loading;

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 custom-scrollbar">
      {showEmpty && (
        <div className="h-full flex flex-col items-center justify-center text-gray-500 text-sm gap-2">
          <div className="text-2xl">💬</div>
          <div>HiClaw Chat 已就绪</div>
          <div className="text-xs text-gray-600 max-w-sm text-center">
            可以问平台的 agent、任务、定时任务、skill 相关的任何问题；
            需要的时候可以请我帮你启动一次 agent 分析。
          </div>
        </div>
      )}

      {messages.map((msg, i) => (
        <MessageBubble
          // eslint-disable-next-line react/no-array-index-key
          key={i}
          message={msg}
          toolResults={toolResults}
          runningToolIds={runningToolIds}
        />
      ))}

      {loading && streamingText && (
        <MessageBubble
          message={{ role: "assistant", content: streamingText }}
          toolResults={toolResults}
          runningToolIds={runningToolIds}
        />
      )}

      {loading && !streamingText && (
        <div className="flex justify-start mb-3">
          <div className="bg-[#161b22] border border-[#30363d] rounded-2xl px-4 py-3">
            <div className="flex gap-1.5">
              <div className="w-2 h-2 rounded-full bg-gray-500 animate-pulse" />
              <div
                className="w-2 h-2 rounded-full bg-gray-500 animate-pulse"
                style={{ animationDelay: "0.15s" }}
              />
              <div
                className="w-2 h-2 rounded-full bg-gray-500 animate-pulse"
                style={{ animationDelay: "0.3s" }}
              />
            </div>
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
