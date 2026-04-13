// >>> CUSTOM: HiClaw — Shared task-list parser <<<
// Pulls the latest TaskTrackingObservation (command="plan") out of a list of
// conversation events and normalizes it to TaskListItem[]. Used by both the
// live-stream `useTaskList` hook and the task center detail page, so both
// surfaces render exactly the same data shape.

import { isTaskTrackingObservation } from "#/types/core/guards";
import type { OpenHandsParsedEvent } from "#/types/core";
import { isObservationEvent } from "#/types/v1/type-guards";
import type { OpenHandsEvent } from "#/types/v1/core";
import type { TaskTrackerObservation } from "#/types/v1/core/base/observation";
import type { ObservationEvent } from "#/types/v1/core/events/observation-event";

export interface TaskListItem {
  id: string;
  title: string;
  status: "todo" | "in_progress" | "done";
  notes?: string;
}

export function getTaskListFromEvent(event: unknown): TaskListItem[] | null {
  // v0 event format: observation is a string "task_tracking"
  const v0 = event as OpenHandsParsedEvent;
  if (isTaskTrackingObservation(v0) && v0.extras.command === "plan") {
    return v0.extras.task_list.map((t) => ({
      id: t.id,
      title: t.title,
      status: t.status,
      notes: t.notes,
    }));
  }

  // v1 event format: observation is an object with kind "TaskTrackerObservation"
  const v1 = event as OpenHandsEvent;
  if (
    isObservationEvent(v1) &&
    v1.observation.kind === "TaskTrackerObservation"
  ) {
    const obs = (v1 as ObservationEvent<TaskTrackerObservation>).observation;
    if (obs.command === "plan") {
      return obs.task_list.map((t, i) => ({
        id: String(i + 1),
        title: t.title,
        status: t.status,
        notes: t.notes || undefined,
      }));
    }
  }

  return null;
}

/**
 * Walk `events` newest-first and return the latest task_tracking plan as
 * TaskListItem[]. Returns an empty array if no plan event is present.
 */
export function parseTaskListFromEvents(events: unknown[]): TaskListItem[] {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const list = getTaskListFromEvent(events[i]);
    if (list) return list;
  }
  return [];
}
// >>> END CUSTOM <<<
