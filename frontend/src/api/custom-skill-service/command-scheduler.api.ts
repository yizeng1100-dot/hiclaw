// HiClaw — API client for the command scheduler.

export type ScheduleKind =
  | "one_time"
  | "daily"
  | "weekly"
  | "monthly"
  | "yearly";
export type ShellKind = "linux" | "windows";
export type EnvTag = "formal" | "test";
export type HolidayPolicy = "normal" | "skip" | "run_before" | "run_after";
export type FireStatus =
  | "running"
  | "success"
  | "failed"
  | "timeout"
  | "skipped";
export type TriggerSource = "scheduled" | "manual";

export interface CommandSchedule {
  id: string;
  name: string;
  env_tag: EnvTag;
  shell_kind: ShellKind;
  kind: ScheduleKind;
  cron_expr: string | null;
  run_at: string | null;
  command: string;
  working_dir: string | null;
  max_duration_sec: number;
  holiday_policy: HolidayPolicy;
  log_path: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  last_fire_at: string | null;
  next_fire_at: string | null;
  schedule_description: string;
}

export interface CommandScheduleInput {
  name: string;
  env_tag?: EnvTag;
  shell_kind?: ShellKind;
  kind: ScheduleKind;
  cron_expr?: string | null;
  run_at?: string | null;
  command: string;
  working_dir?: string | null;
  max_duration_sec?: number;
  holiday_policy?: HolidayPolicy;
  log_path?: string | null;
  enabled?: boolean;
}

export interface CommandFire {
  id: string;
  schedule_id: string;
  started_at: string;
  completed_at: string | null;
  status: FireStatus;
  skip_reason: string | null;
  exit_code: number | null;
  stdout_tail: string | null;
  stderr_tail: string | null;
  log_file_path: string | null;
  trigger_source: TriggerSource;
}

export interface Holiday {
  date: string;
  name: string;
  kind: "holiday" | "makeup_workday";
  source: "preset" | "user";
  created_at: string;
}

export interface HolidayCheck {
  date: string;
  is_holiday: boolean;
  is_makeup_workday: boolean;
  is_workday: boolean;
  name: string | null;
}

export interface Stats {
  total: number;
  running: number;
  enabled: number;
  disabled: number;
}

const BASE = "/api/v1/command-schedules";
const HOL = "/api/v1/command-scheduler/holidays";

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!resp.ok) {
    throw new Error(`${init?.method || "GET"} ${url} -> ${resp.status}`);
  }
  if (resp.status === 204) return undefined as unknown as T;
  return (await resp.json()) as T;
}

// eslint-disable-next-line import/prefer-default-export
export class CommandSchedulerService {
  static list(params?: {
    enabled?: boolean;
    env_tag?: string;
    q?: string;
  }): Promise<CommandSchedule[]> {
    const qs = new URLSearchParams();
    if (params?.enabled !== undefined)
      qs.set("enabled", String(params.enabled));
    if (params?.env_tag) qs.set("env_tag", params.env_tag);
    if (params?.q) qs.set("q", params.q);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return req<CommandSchedule[]>(`${BASE}${suffix}`);
  }

  static get(id: string): Promise<CommandSchedule> {
    return req<CommandSchedule>(`${BASE}/${id}`);
  }

  static stats(): Promise<Stats> {
    return req<Stats>(`${BASE}/stats`);
  }

  static create(payload: CommandScheduleInput): Promise<CommandSchedule> {
    return req<CommandSchedule>(BASE, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  static update(
    id: string,
    payload: Partial<CommandScheduleInput>,
  ): Promise<CommandSchedule> {
    return req<CommandSchedule>(`${BASE}/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  static delete(id: string): Promise<{ deleted: boolean }> {
    return req<{ deleted: boolean }>(`${BASE}/${id}`, { method: "DELETE" });
  }

  static run(id: string): Promise<{ fire_id: string }> {
    return req<{ fire_id: string }>(`${BASE}/${id}/run`, { method: "POST" });
  }

  static pauseAll(): Promise<{ paused: number }> {
    return req<{ paused: number }>(`${BASE}/pause-all`, { method: "POST" });
  }

  static resumeAll(): Promise<{ resumed: number }> {
    return req<{ resumed: number }>(`${BASE}/resume-all`, { method: "POST" });
  }

  static listFires(id: string, limit = 20, offset = 0): Promise<CommandFire[]> {
    return req<CommandFire[]>(
      `${BASE}/${id}/fires?limit=${limit}&offset=${offset}`,
    );
  }

  static getFire(fireId: string): Promise<CommandFire> {
    return req<CommandFire>(`${BASE}/fires/${fireId}`);
  }

  static logUrl(fireId: string): string {
    return `${BASE}/fires/${fireId}/log`;
  }

  // Holidays
  static listHolidays(year: number): Promise<Holiday[]> {
    return req<Holiday[]>(`${HOL}?year=${year}`);
  }

  static addHoliday(payload: {
    date: string;
    name: string;
    kind?: string;
  }): Promise<Holiday> {
    return req<Holiday>(HOL, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  static deleteHoliday(date: string): Promise<{ deleted: boolean }> {
    return req<{ deleted: boolean }>(`${HOL}/${date}`, { method: "DELETE" });
  }

  static checkDate(date: string): Promise<HolidayCheck> {
    return req<HolidayCheck>(`${HOL}/check/${date}`);
  }
}
