/* eslint-disable i18next/no-literal-string */
// HiClaw — Main chat page at /chat.

import React from "react";
import { ChatInput } from "./chat-input";
import { MessageList } from "./message-list";
import { useChat } from "./use-chat";

export function ChatPage() {
  const {
    messages,
    streamingText,
    toolResults,
    runningToolIds,
    loading,
    error,
    sendMessage,
    clear,
  } = useChat();

  return (
    <div className="h-full flex flex-col text-white bg-[#0d1117]">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-[#30363d]">
        <div>
          <h1 className="text-base font-semibold">HiClaw Chat</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            平台对话助手 · 可查询 agent / 任务 / 定时任务 / skill， 也能帮你触发
            agent 分析
          </p>
        </div>
        <button
          type="button"
          onClick={clear}
          disabled={loading || messages.length === 0}
          className="text-xs px-3 py-1.5 rounded border border-[#30363d] text-gray-400 hover:text-white hover:border-[#525568] disabled:opacity-40 disabled:cursor-not-allowed"
        >
          新对话
        </button>
      </div>

      {error && (
        <div className="mx-4 mt-3 px-3 py-2 rounded bg-red-900/30 border border-red-900/50 text-xs text-red-400">
          错误: {error}
        </div>
      )}

      <MessageList
        messages={messages}
        streamingText={streamingText}
        toolResults={toolResults}
        runningToolIds={runningToolIds}
        loading={loading}
      />

      <ChatInput onSend={sendMessage} disabled={loading} />
    </div>
  );
}
