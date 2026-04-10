import { useTranslation } from "react-i18next";
import { I18nKey } from "#/i18n/declaration";
import CheckCircleIcon from "#/icons/u-check-circle.svg?react";
import { TaskItem } from "#/components/features/chat/task-tracking/task-item";
import { useTaskList } from "#/hooks/use-task-list";
import { Text } from "#/ui/typography";
import { cn } from "#/utils/utils";

function TaskListTab() {
  const { t } = useTranslation();
  const { taskList } = useTaskList();

  if (taskList.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center w-full h-full p-10 gap-4">
        <CheckCircleIcon width={109} height={109} color="#A1A1A1" />
        <Text className="text-[#8D95A9] text-[19px] font-normal leading-5">
          {t(I18nKey.COMMON$NO_TASKS)}
        </Text>
      </div>
    );
  }

  return (
    <main className="h-full overflow-y-auto flex flex-col custom-scrollbar-always">
      {taskList.map((task, i) => (
        <div key={task.id} className="flex px-4">
          {/* >>> CUSTOM: HiClaw — vertical connector line between phases <<< */}
          <div className="flex flex-col items-center mr-1 w-4 shrink-0">
            {i > 0 && (
              <div
                className={cn(
                  "w-0.5 h-2",
                  task.status === "done"
                    ? "bg-green-500"
                    : task.status === "in_progress"
                      ? "bg-blue-500"
                      : "bg-gray-700",
                )}
              />
            )}
            <div className="flex-1" />
            {i < taskList.length - 1 && (
              <div
                className={cn(
                  "w-0.5 h-2",
                  task.status === "done" ? "bg-green-500" : "bg-gray-700",
                )}
              />
            )}
          </div>
          {/* >>> END CUSTOM <<< */}
          <div
            className={cn(
              "flex-1 py-1.5",
              task.status === "in_progress" &&
                "bg-blue-900/20 rounded px-2 -mx-1",
            )}
          >
            <TaskItem task={task} />
          </div>
        </div>
      ))}
    </main>
  );
}

export default TaskListTab;
