import React from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";
import { X } from "lucide-react";
import { I18nKey } from "#/i18n/declaration";
import { cn } from "#/utils/utils";
// >>> CUSTOM: HiClaw <<<
import { openHands } from "#/api/open-hands-axios";
import { useConversationId } from "#/hooks/use-conversation-id";
// >>> END CUSTOM <<<

interface ErrorMessageBannerProps {
  message: string;
  onDismiss?: () => void;
}

const DEFAULT_MAX_COLLAPSED_CHARS = 220;

// >>> CUSTOM: HiClaw — detect LLM API errors <<<
const LLM_ERROR_KEYWORDS = [
  "free tier", "exhausted", "quota", "rate limit", "rate_limit",
  "insufficient_quota", "billing", "exceeded", "APIError", "api_key",
  "invalid_api_key", "authentication", "Unauthorized",
  "model not found", "model_not_found", "does not exist",
];
function isLLMConfigError(msg: string): boolean {
  const lower = msg.toLowerCase();
  return LLM_ERROR_KEYWORDS.some((kw) => lower.includes(kw.toLowerCase()));
}
// >>> END CUSTOM <<<

export function ErrorMessageBanner({ message, onDismiss }: ErrorMessageBannerProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { conversationId } = useConversationId();
  const [isExpanded, setIsExpanded] = React.useState(false);
  // >>> CUSTOM: HiClaw <<<
  const [showModelForm, setShowModelForm] = React.useState(false);
  const [model, setModel] = React.useState("");
  const [apiKey, setApiKey] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [saveMsg, setSaveMsg] = React.useState("");
  const showLLMSwitch = isLLMConfigError(message);

  const handleOpenModelForm = React.useCallback(async () => {
    try {
      const { data } = await openHands.get("/api/settings");
      setModel(data.llm_model || "");
      setApiKey("");
      setBaseUrl(data.llm_base_url || "");
    } catch { /* ignore */ }
    setShowModelForm(true);
    setSaveMsg("");
  }, []);

  const handleSaveModel = async () => {
    if (!model.trim()) { setSaveMsg("请填写模型名称"); return; }
    setSaving(true); setSaveMsg("");
    try {
      const payload: Record<string, string> = { llm_model: model.trim() };
      if (apiKey.trim()) payload.llm_api_key = apiKey.trim();
      if (baseUrl.trim()) payload.llm_base_url = baseUrl.trim();
      const { data } = await openHands.post(
        `/api/v1/conversations/${conversationId || "unknown"}/switch-model`, payload);
      setSaveMsg(data.message || "模型已切换");
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setSaveMsg("切换失败: " + (err.response?.data?.detail || err.message));
    } finally { setSaving(false); }
  };
  // >>> END CUSTOM <<<

  const isI18nKey = i18n.exists(message);
  const displayTextForLength = isI18nKey ? String(t(message)) : message;
  const shouldShowToggle = displayTextForLength.length > DEFAULT_MAX_COLLAPSED_CHARS;
  const isCollapsed = shouldShowToggle && !isExpanded;

  return (
    <div
      className="w-full rounded-lg p-2 border border-[#FF0006] bg-[#4A0709] flex flex-col gap-2 text-white"
      data-testid="error-message-banner"
    >
      <div className="flex gap-2 items-start">
        <div className="min-w-0 flex-1">
          <div
            className={cn(
              "whitespace-pre-wrap break-words",
              isCollapsed && "line-clamp-3",
            )}
            data-testid="error-message-banner-content"
          >
            {isI18nKey ? (
              <Trans
                i18nKey={message}
                components={{
                  a: (
                    <Link
                      className="underline font-bold cursor-pointer"
                      to="/settings/billing"
                    >
                      link
                    </Link>
                  ),
                }}
              />
            ) : (
              message
            )}
          </div>
          <div className="flex items-center gap-2 mt-1.5">
            {shouldShowToggle && (
              <button type="button" className="text-xs underline font-semibold cursor-pointer" onClick={() => setIsExpanded((prev) => !prev)} data-testid="error-message-banner-toggle">
                {isExpanded ? t(I18nKey.COMMON$VIEW_LESS) : t(I18nKey.COMMON$VIEW_MORE)}
              </button>
            )}
            {/* >>> CUSTOM: HiClaw <<< */}
            {showLLMSwitch && !showModelForm && (
              <button type="button" onClick={handleOpenModelForm} className="text-xs px-2 py-1 bg-blue-600 hover:bg-blue-700 rounded font-medium transition">
                {"更换模型"}
              </button>
            )}
            {/* >>> END CUSTOM <<< */}
          </div>
        </div>
        {onDismiss && (
          <button type="button" onClick={onDismiss} className="shrink-0 rounded-md p-1 hover:bg-black/10 cursor-pointer" aria-label={t(I18nKey.BUTTON$CLOSE)} data-testid="error-message-banner-dismiss">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      {/* >>> CUSTOM: HiClaw — inline model switch form <<< */}
      {showModelForm && (
        <div className="border-t border-red-800/50 pt-2 space-y-2">
          <div className="grid grid-cols-1 gap-2">
            <input type="text" value={model} onChange={(e) => setModel(e.target.value)} placeholder="模型名称 (e.g. openai/qwen-max)" className="px-2 py-1.5 bg-[#1a1d24] border border-[#444] rounded text-xs text-white focus:outline-none focus:border-blue-500" />
            <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="API Key (留空则不更改)" className="px-2 py-1.5 bg-[#1a1d24] border border-[#444] rounded text-xs text-white focus:outline-none focus:border-blue-500" />
            <input type="text" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="Base URL (留空则不更改)" className="px-2 py-1.5 bg-[#1a1d24] border border-[#444] rounded text-xs text-white focus:outline-none focus:border-blue-500" />
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {saveMsg && !saveMsg.includes("失败") ? (
              <>
                <span className="text-xs text-green-400">{"✓ "}{saveMsg}</span>
                <button type="button" onClick={() => window.location.reload()} className="text-xs px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded font-medium transition">{"刷新继续"}</button>
              </>
            ) : (
              <>
                <button type="button" onClick={handleSaveModel} disabled={saving} className="text-xs px-3 py-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded font-medium transition">{saving ? "切换中..." : "切换模型"}</button>
                <button type="button" onClick={() => setShowModelForm(false)} className="text-xs px-3 py-1 bg-[#333] hover:bg-[#444] rounded transition">{"取消"}</button>
                {saveMsg && <span className="text-xs text-red-400">{saveMsg}</span>}
              </>
            )}
          </div>
        </div>
      )}
      {/* >>> END CUSTOM <<< */}
    </div>
  );
}
