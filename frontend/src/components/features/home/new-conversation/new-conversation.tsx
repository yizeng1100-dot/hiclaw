import { useTranslation } from "react-i18next";
import { I18nKey } from "#/i18n/declaration";
import PlusIcon from "#/icons/u-plus.svg?react";
import { CardTitle } from "#/ui/card-title";
import { Typography } from "#/ui/typography";
import { CreateConversationButton } from "./create-conversation-button";
import { Card } from "#/ui/card";
// >>> CUSTOM: HiClaw <<<
import { useRemoteWorkerStore } from "#/stores/remote-worker-store";
// >>> END CUSTOM <<<

export function NewConversation() {
  const { t } = useTranslation();
  // >>> CUSTOM: HiClaw <<<
  const { enabled, setEnabled } = useRemoteWorkerStore();
  // >>> END CUSTOM <<<

  return (
    <Card className="flex-col p-5 gap-2.5 min-h-[286px] md:min-h-auto w-full">
      <CardTitle icon={<PlusIcon width={17} height={14} />}>
        {t(I18nKey.COMMON$START_FROM_SCRATCH)}
      </CardTitle>
      <Typography.Text>
        {t(I18nKey.HOME$NEW_PROJECT_DESCRIPTION)}
      </Typography.Text>
      {/* >>> CUSTOM: HiClaw <<< */}
      <label className="flex items-center gap-2 cursor-pointer mt-1">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          className="accent-blue-500 w-3.5 h-3.5"
        />
        <span className="text-xs text-neutral-400">Remote Machine</span>
      </label>
      {/* >>> END CUSTOM <<< */}
      <CreateConversationButton />
    </Card>
  );
}
