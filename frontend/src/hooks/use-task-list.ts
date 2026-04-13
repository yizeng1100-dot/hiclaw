import { useMemo } from "react";
import { useEventStore } from "#/stores/use-event-store";
import {
  parseTaskListFromEvents,
  type TaskListItem,
} from "#/utils/parse-task-list";

export type { TaskListItem };

export function useTaskList() {
  const events = useEventStore((state) => state.events);

  return useMemo(() => {
    const taskList = parseTaskListFromEvents(events);
    return { taskList, hasTaskList: taskList.length > 0 };
  }, [events]);
}
