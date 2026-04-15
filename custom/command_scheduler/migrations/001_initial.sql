-- Reference schema for command_scheduler tables.
-- Actual table creation happens via SQLAlchemy Base.metadata at app startup
-- (inherited from the shared Base used by agent_mgmt and scheduled_tasks).
-- This file exists so ops can diff against the live DB schema.

CREATE TABLE IF NOT EXISTS command_schedules (
    id VARCHAR NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    env_tag VARCHAR NOT NULL DEFAULT 'formal',
    shell_kind VARCHAR NOT NULL DEFAULT 'linux',
    kind VARCHAR NOT NULL,
    cron_expr VARCHAR,
    run_at DATETIME,
    command TEXT NOT NULL,
    working_dir VARCHAR,
    max_duration_sec INTEGER NOT NULL DEFAULT 300,
    holiday_policy VARCHAR NOT NULL DEFAULT 'normal',
    log_path VARCHAR,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_fire_at DATETIME,
    next_fire_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_cs_enabled ON command_schedules(enabled);

CREATE TABLE IF NOT EXISTS command_fires (
    id VARCHAR NOT NULL PRIMARY KEY,
    schedule_id VARCHAR NOT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    status VARCHAR NOT NULL DEFAULT 'running',
    skip_reason VARCHAR,
    exit_code INTEGER,
    stdout_tail TEXT,
    stderr_tail TEXT,
    log_file_path VARCHAR,
    trigger_source VARCHAR NOT NULL DEFAULT 'scheduled',
    FOREIGN KEY (schedule_id) REFERENCES command_schedules(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cf_schedule_id ON command_fires(schedule_id);
CREATE INDEX IF NOT EXISTS idx_cf_started_at ON command_fires(started_at);

CREATE TABLE IF NOT EXISTS holidays (
    date VARCHAR NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
