/* eslint-disable i18next/no-literal-string, no-nested-ternary */
import React from "react";
import { useParams, useNavigate } from "react-router";
import {
  AgentService,
  type AgentDetail,
} from "#/api/custom-skill-service/agent-service.api";
import { TaskService } from "#/api/custom-skill-service/task-service.api";
import { useCreateConversation } from "#/hooks/mutation/use-create-conversation";
import { cn } from "#/utils/utils";
import { PerfAnalysisInlinePanel } from "../skill-management/perf-analysis-inline-panel";
// KernelDiffInlinePanel only available on merge branch
// import { KernelDiffInlinePanel } from "../skill-management/kernel-diff-inline-panel";

function getAgentType(agent: AgentDetail | null): string | null {
  if (!agent?.config_json) return null;
  try {
    return JSON.parse(agent.config_json).agent_type || null;
  } catch {
    return null;
  }
}

export function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const { mutateAsync: createConversation } = useCreateConversation();
  const [agent, setAgent] = React.useState<AgentDetail | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [starting, setStarting] = React.useState(false);
  const [showPerfPanel, setShowPerfPanel] = React.useState(false);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!agentId) return;
    setLoading(true);
    AgentService.getAgent(agentId)
      .then(setAgent)
      .catch((e) => console.error("Failed to load agent:", e))
      .finally(() => setLoading(false));
  }, [agentId]);

  const agentType = getAgentType(agent);
  const hasPanel = agentType === "perf-analysis" || agentType === "kernel-diff";

  // Helper: create HiClaw task + conversation, then navigate
  const startAgentConversation = React.useCallback(
    async (message: string) => {
      if (!agentId || starting) return;
      setStarting(true);
      setErrorMsg(null);
      try {
        // 1. Create HiClaw task record
        const taskResult = await TaskService.createTask({ agent_id: agentId });

        // 2. Create conversation via the standard hook (respects v1_enabled)
        const convData = await createConversation({ query: message });

        // 3. Link HiClaw task to conversation
        await TaskService.startTask(
          taskResult.task_id,
          convData.conversation_id,
        ).catch(() => {});

        // 4. Navigate to conversation (useTaskPolling handles the rest)
        navigate(`/conversations/${convData.conversation_id}`);
      } catch (e: unknown) {
        const err = e as { message?: string };
        setErrorMsg(err.message || "Failed to start conversation");
      } finally {
        setStarting(false);
      }
    },
    [agentId, starting, navigate, createConversation],
  );

  // Perf agent flow: panel submit → create conversation with analysis message
  const handlePerfSubmit = React.useCallback(
    async (_tracePath: string, message: string) => {
      await startAgentConversation(message);
    },
    [startAgentConversation],
  );

  // Generic agent flow: create conversation with system prompt
  const handleStartAgent = async () => {
    if (!agent) return;
    const prompt = agent.system_prompt
      ? `[Agent: ${agent.name}]\n\n${agent.system_prompt}`
      : `Execute Agent: ${agent.name}`;
    await startAgentConversation(prompt);
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500">
        加载中...
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-500">
        <p>Agent 未找到</p>
        <button
          type="button"
          onClick={() => navigate("/agents")}
          className="mt-4 text-blue-400 hover:underline"
        >
          返回 Agent 列表
        </button>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col p-6 text-white overflow-auto custom-scrollbar">
      {/* Back */}
      <button
        type="button"
        onClick={() => navigate("/agents")}
        className="text-sm text-gray-400 hover:text-white mb-4 self-start"
      >
        ← 返回列表
      </button>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">{agent.name}</h1>
          <p className="text-gray-400 mt-1">
            {agent.description || "暂无描述"}
          </p>
          <div className="flex gap-2 mt-2">
            {agent.category && (
              <span className="text-xs px-2 py-0.5 rounded bg-[#21262d] text-gray-300">
                {agent.category}
              </span>
            )}
            {agent.tags.map((t) => (
              <span
                key={t}
                className="text-xs px-2 py-0.5 rounded bg-blue-900/30 text-blue-400"
              >
                {t}
              </span>
            ))}
          </div>
        </div>

        {/* Action button */}
        {hasPanel ? (
          <button
            type="button"
            onClick={() => setShowPerfPanel((v) => !v)}
            disabled={starting || !agent.is_enabled}
            className={cn(
              "px-6 py-2.5 disabled:opacity-50 rounded-lg text-sm font-medium text-black transition shrink-0",
              agentType === "kernel-diff"
                ? "bg-[#F97316] hover:bg-[#EA690E]"
                : "bg-[#4ECDC4] hover:bg-[#3dbdb5]",
            )}
          >
            {starting ? "分析中..." : showPerfPanel ? "收起面板" : "开始分析"}
          </button>
        ) : (
          <button
            type="button"
            onClick={handleStartAgent}
            disabled={starting || !agent.is_enabled}
            className="px-6 py-2.5 bg-green-600 hover:bg-green-700 disabled:opacity-50 rounded-lg text-sm font-medium transition shrink-0"
          >
            {starting ? "启动中..." : "启动 Agent"}
          </button>
        )}
      </div>

      {/* Error message */}
      {errorMsg && (
        <div className="mb-4 p-3 bg-red-900/30 border border-red-800/50 rounded-lg text-sm text-red-400">
          {errorMsg}
        </div>
      )}

      {/* Analysis panel */}
      {hasPanel && showPerfPanel && (
        <div className="mb-6">
          {agentType === "perf-analysis" ? (
            <PerfAnalysisInlinePanel
              onSubmit={handlePerfSubmit}
              onDismiss={() => setShowPerfPanel(false)}
              disabled={starting}
            />
          ) : null}
        </div>
      )}

      {/* Content grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* System Prompt - hide for agents with panels (too long) */}
        {!hasPanel && (
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-300 mb-2">
              系统提示词
            </h3>
            {agent.system_prompt ? (
              <pre className="text-sm text-gray-400 whitespace-pre-wrap font-mono bg-[#0d1117] p-3 rounded max-h-60 overflow-auto custom-scrollbar">
                {agent.system_prompt}
              </pre>
            ) : (
              <p className="text-sm text-gray-500">未配置系统提示词</p>
            )}
          </div>
        )}

        {/* Meta Info */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">基本信息</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">状态</span>
              <span
                className={agent.is_enabled ? "text-green-400" : "text-red-400"}
              >
                {agent.is_enabled ? "已启用" : "已停用"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">使用次数</span>
              <span className="text-gray-300">{agent.usage_count}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">创建者</span>
              <span className="text-gray-300">
                {agent.created_by || "unknown"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">默认模型</span>
              <span className="text-gray-300">
                {agent.default_llm_model || "默认"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">创建时间</span>
              <span className="text-gray-300">
                {new Date(agent.created_at).toLocaleString("zh-CN")}
              </span>
            </div>
          </div>
        </div>

        {/* Workflow Rule & Skills */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4">
          {/* Workflow Rule */}
          {agent.skills.filter((s) => s.name.includes("workflow")).length >
            0 && (
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-gray-300 mb-3">
                工作流 Rule
              </h3>
              <div className="space-y-2">
                {agent.skills
                  .filter((s) => s.name.includes("workflow"))
                  .map((skill) => (
                    <div
                      key={skill.id}
                      className="flex items-start gap-3 p-2 rounded bg-[#4ECDC4]/5 border border-[#4ECDC4]/20"
                    >
                      <div className="w-8 h-8 rounded bg-[#4ECDC4]/15 flex items-center justify-center shrink-0 mt-0.5">
                        <svg
                          width="14"
                          height="14"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="#4ECDC4"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                        </svg>
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-[#4ECDC4] font-medium truncate">
                          {skill.name}
                        </p>
                        <p className="text-xs text-gray-500 truncate">
                          {skill.description ||
                            "始终加载的工作流规则，指导 Agent 按步骤执行分析"}
                        </p>
                      </div>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#4ECDC4]/15 text-[#4ECDC4] shrink-0">
                        Rule
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Associated Skills */}
          <h3 className="text-sm font-semibold text-gray-300 mb-3">
            关联 Skills (
            {agent.skills.filter((s) => !s.name.includes("workflow")).length})
          </h3>
          {agent.skills.filter((s) => !s.name.includes("workflow")).length ===
          0 ? (
            <p className="text-sm text-gray-500">暂未关联任何 Skill</p>
          ) : (
            <div className="space-y-2 max-h-60 overflow-auto custom-scrollbar">
              {agent.skills
                .filter((s) => !s.name.includes("workflow"))
                .map((skill) => (
                  <div
                    key={skill.id}
                    className="flex items-start gap-3 p-2 rounded bg-[#0d1117] hover:bg-[#21262d] transition cursor-pointer"
                    onClick={() => navigate("/skill-management")}
                  >
                    <div className="w-8 h-8 rounded bg-blue-900/30 flex items-center justify-center shrink-0 mt-0.5">
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        className="text-blue-400"
                      >
                        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
                      </svg>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white font-medium truncate">
                        {skill.name}
                      </p>
                      <p className="text-xs text-gray-500 truncate">
                        {skill.description || "暂无描述"}
                      </p>
                    </div>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/30 text-blue-400 shrink-0">
                      Skill
                    </span>
                  </div>
                ))}
            </div>
          )}
        </div>

        {/* Usage Instructions */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-2">使用说明</h3>
          {agent.usage_instructions ? (
            <div className="text-sm text-gray-400 whitespace-pre-wrap bg-[#0d1117] p-3 rounded max-h-60 overflow-auto custom-scrollbar">
              {agent.usage_instructions}
            </div>
          ) : (
            <p className="text-sm text-gray-500">暂无使用说明</p>
          )}
        </div>
      </div>
    </div>
  );
}
