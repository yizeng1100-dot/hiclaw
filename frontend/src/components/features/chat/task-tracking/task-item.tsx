import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import CircleIcon from "#/icons/u-circle.svg?react";
import CheckCircleIcon from "#/icons/u-check-circle.svg?react";
import CheckCircleHalfIcon from "#/icons/u-check-circle-half.svg?react";
import { I18nKey } from "#/i18n/declaration";
import { cn } from "#/utils/utils";
import { Typography } from "#/ui/typography";

interface TaskItemProps {
  task: {
    id: string;
    title: string;
    status: "todo" | "in_progress" | "done";
    notes?: string;
  };
}

export function TaskItem({ task }: TaskItemProps) {
  const { t } = useTranslation();

  // >>> CUSTOM: HiClaw — "light up" phase progress colors <<<
  const icon = useMemo(() => {
    switch (task.status) {
      case "todo":
        return <CircleIcon className="w-4 h-4 text-gray-600" />;
      case "in_progress":
        return (
          <CheckCircleHalfIcon className="w-4 h-4 text-blue-400 animate-pulse" />
        );
      case "done":
        return <CheckCircleIcon className="w-4 h-4 text-green-400" />;
      default:
        return <CircleIcon className="w-4 h-4 text-gray-600" />;
    }
  }, [task.status]);

  const textColor =
    task.status === "done"
      ? "text-green-400"
      : task.status === "in_progress"
        ? "text-blue-400"
        : "text-gray-500";
  // >>> END CUSTOM <<<

  return (
    <div className="flex gap-2 items-center w-full" data-name="item">
      <div className="shrink-0">{icon}</div>
      <div className="flex flex-col items-start justify-center leading-[16px] text-nowrap whitespace-pre font-normal">
        <Typography.Text className={cn("text-[12px]", textColor)}>
          {task.title}
        </Typography.Text>
        {task.notes && (
          <Typography.Text
            className={cn(
              "text-[10px]",
              task.status === "done" ? "text-green-700" : "text-[#A3A3A3]",
            )}
          >
            {t(I18nKey.TASK_TRACKING_OBSERVATION$TASK_NOTES)}: {task.notes}
          </Typography.Text>
        )}
      </div>
    </div>
  );
}
