import { useTranslation } from "react-i18next";
import { I18nKey } from "#/i18n/declaration";
import PlusIcon from "#/icons/u-plus.svg?react";
import { CardTitle } from "#/ui/card-title";
import { Typography } from "#/ui/typography";
import { CreateConversationButton } from "./create-conversation-button";
import { Card } from "#/ui/card";
// >>> CUSTOM: HiClaw <<<
import {
  useAgentEngineStore,
  type AgentEngine,
} from "#/stores/agent-engine-store";
// >>> END CUSTOM <<<

export function NewConversation() {
  const { t } = useTranslation();
  // >>> CUSTOM: HiClaw <<<
  const { engine, setEngine } = useAgentEngineStore();

  const engines: { value: AgentEngine; label: string }[] = [
    { value: "openhands_sdk", label: "OpenHands" },
    { value: "claude_sdk", label: "Claude" },
  ];
  // >>> END CUSTOM <<<

  return (
    <Card className="flex-col p-5 gap-2.5 min-h-[286px] md:min-h-auto w-full">
      <CardTitle icon={<PlusIcon width={17} height={14} />}>
        {t(I18nKey.COMMON$START_FROM_SCRATCH)}
      </CardTitle>
      <Typography.Text>
        {t(I18nKey.HOME$NEW_PROJECT_DESCRIPTION)}
      </Typography.Text>
      {/* >>> CUSTOM: HiClaw — Remote machine is mandatory <<< */}
      <label className="flex items-center gap-2 mt-1">
        <input
          type="checkbox"
          checked
          disabled
          className="accent-blue-500 w-3.5 h-3.5"
        />
        {/* eslint-disable-next-line i18next/no-literal-string */}
        <span className="text-xs text-neutral-400">Remote Machine</span>
      </label>
      {/* >>> END CUSTOM <<< */}
      {/* >>> CUSTOM: HiClaw — Agent engine selector <<< */}
      <div className="flex items-center gap-2 mt-1">
        {/* eslint-disable-next-line i18next/no-literal-string */}
        <span className="text-xs text-neutral-400 shrink-0">Agent Engine:</span>
        <div className="flex gap-1">
          {engines.map((opt) => {
            const isActive = engine === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => setEngine(opt.value)}
                className={`px-2 py-0.5 text-[11px] rounded border transition ${
                  isActive
                    ? "bg-blue-500/20 border-blue-500 text-blue-300"
                    : "border-neutral-700 text-neutral-400 hover:border-neutral-500 hover:text-neutral-200"
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>
      {/* >>> END CUSTOM <<< */}
      <CreateConversationButton />
    </Card>
  );
}
