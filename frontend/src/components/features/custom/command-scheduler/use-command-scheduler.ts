import React from "react";
import {
  CommandSchedulerService,
  CommandSchedule,
  Stats,
} from "#/api/custom-skill-service/command-scheduler.api";

export function useCommandScheduler() {
  const [schedules, setSchedules] = React.useState<CommandSchedule[]>([]);
  const [stats, setStats] = React.useState<Stats>({
    total: 0,
    running: 0,
    enabled: 0,
    disabled: 0,
  });
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [filter, setFilter] = React.useState<{
    env_tag?: string;
    q?: string;
  }>({});

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, st] = await Promise.all([
        CommandSchedulerService.list(filter),
        CommandSchedulerService.stats(),
      ]);
      setSchedules(list);
      setStats(st);
    } catch (e) {
      const err = e as Error;
      setError(err.message || "failed to load");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const toggleEnabled = React.useCallback(
    async (id: string, enabled: boolean) => {
      await CommandSchedulerService.update(id, { enabled });
      await refresh();
    },
    [refresh],
  );

  const runNow = React.useCallback(
    async (id: string) => {
      await CommandSchedulerService.run(id);
      await refresh();
    },
    [refresh],
  );

  const remove = React.useCallback(
    async (id: string) => {
      await CommandSchedulerService.delete(id);
      await refresh();
    },
    [refresh],
  );

  return {
    schedules,
    stats,
    loading,
    error,
    filter,
    setFilter,
    refresh,
    toggleEnabled,
    runNow,
    remove,
  };
}
