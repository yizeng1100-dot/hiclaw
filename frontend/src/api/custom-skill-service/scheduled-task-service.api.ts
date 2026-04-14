// HiClaw — Scheduled tasks REST client.
// Wraps /api/v1/scheduled-tasks CRUD + fire-now + fires list.

import { openHands } from "#/api/open-hands-axios";

export type ScheduleKind =
  | "every_n_minutes"
  | "hourly"
  | "daily"
  | "weekly"
  | "custom_cron";

export interface SchedulePayload {
  kind: ScheduleKind;
  params: Record<string, unknown>;
}

export interface ScheduledTaskInfo {
  id: string;
  agent_id: string;
  agent_name: string | null;
  name: string;
  schedule: SchedulePayload;
  schedule_description: string;
  form_values: Record<string, unknown>;
  enabled: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  last_fire_at: string | null;
  next_fire_at: string | null;
  last_status: string | null;
}

export interface ScheduledTaskFireInfo {
  id: string;
  scheduled_task_id: string;
  started_at: string;
  completed_at: string | null;
  status: "running" | "success" | "failed" | "skipped_concurrent";
  task_id: string | null;
  conversation_id: string | null;
  error_message: string | null;
}

export interface ScheduledTaskCreate {
  agent_id: string;
  name: string;
  schedule: SchedulePayload;
  form_values?: Record<string, unknown>;
  enabled?: boolean;
}

export interface ScheduledTaskUpdate {
  name?: string;
  schedule?: SchedulePayload;
  form_values?: Record<string, unknown>;
  enabled?: boolean;
}

export class ScheduledTaskService {
  static async listSchedules(params?: {
    enabled?: boolean;
  }): Promise<ScheduledTaskInfo[]> {
    const resp = await openHands.get<{ schedules: ScheduledTaskInfo[] }>(
      "/api/v1/scheduled-tasks",
      { params },
    );
    return resp.data.schedules;
  }

  static async getSchedule(id: string): Promise<ScheduledTaskInfo> {
    const resp = await openHands.get<ScheduledTaskInfo>(
      `/api/v1/scheduled-tasks/${id}`,
    );
    return resp.data;
  }

  static async createSchedule(
    data: ScheduledTaskCreate,
  ): Promise<ScheduledTaskInfo> {
    const resp = await openHands.post<ScheduledTaskInfo>(
      "/api/v1/scheduled-tasks",
      data,
    );
    return resp.data;
  }

  static async updateSchedule(
    id: string,
    data: ScheduledTaskUpdate,
  ): Promise<ScheduledTaskInfo> {
    const resp = await openHands.patch<ScheduledTaskInfo>(
      `/api/v1/scheduled-tasks/${id}`,
      data,
    );
    return resp.data;
  }

  static async deleteSchedule(id: string): Promise<void> {
    await openHands.delete(`/api/v1/scheduled-tasks/${id}`);
  }

  static async fireNow(
    id: string,
  ): Promise<{ status: string; schedule_id: string }> {
    const resp = await openHands.post<{ status: string; schedule_id: string }>(
      `/api/v1/scheduled-tasks/${id}/fire-now`,
    );
    return resp.data;
  }

  static async listFires(
    id: string,
    limit = 50,
  ): Promise<ScheduledTaskFireInfo[]> {
    const resp = await openHands.get<{ fires: ScheduledTaskFireInfo[] }>(
      `/api/v1/scheduled-tasks/${id}/fires`,
      { params: { limit } },
    );
    return resp.data.fires;
  }
}
