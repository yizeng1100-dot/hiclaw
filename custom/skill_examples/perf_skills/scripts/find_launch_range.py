#!/usr/bin/env python3
"""Find app launch time range."""

import argparse
import json
import sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
from tp_query import query_tp, parse_columns, save_result, add_common_args


def main():
    parser = argparse.ArgumentParser(description="Find launch time range")
    add_common_args(parser)
    parser.add_argument("--process", required=True, help="Process name")
    args = parser.parse_args()

    # Try launching/bindApplication slices
    sql = f"""
    SELECT
      s.ts AS start_ts,
      s.ts + s.dur AS end_ts,
      s.dur AS duration_ns,
      CAST(s.dur AS REAL) / 1e6 AS duration_ms,
      s.name
    FROM slice s
    JOIN track t ON s.track_id = t.id
    WHERE (s.name LIKE '%launching%' OR s.name LIKE '%Launch%' OR s.name LIKE '%bindApplication%')
      AND (s.name LIKE '%{args.process}%' OR t.name LIKE '%{args.process}%')
      AND s.dur > 0
    ORDER BY s.dur DESC
    LIMIT 5
    """
    result = query_tp(args.port, sql)
    rows = parse_columns(result)

    if rows and rows[0].get("start_ts") and rows[0].get("duration_ms", 0) > 0:
        r = rows[0]
        dur_ms = r.get("duration_ms", 0)
        severity = "excellent" if dur_ms < 1000 else "good" if dur_ms < 1500 else "fair" if dur_ms < 2000 else "poor" if dur_ms < 3000 else "critical"
        output = {
            "start_time": r["start_ts"],
            "end_time": r["end_ts"],
            "duration_ns": r["duration_ns"],
            "duration_ms": dur_ms,
            "slice_name": r.get("name", ""),
            "method": "launch_slice",
            "severity": severity,
            "has_issue": severity in ("poor", "critical"),
            "all_launches": rows,
        }
        save_result(output, "launch_range.json", args.output_dir)
        print(json.dumps(output, indent=2))
        return

    # Fallback: use process first/last event
    sql_fallback = f"""
    SELECT
      MIN(ts.ts) AS start_ts,
      MAX(ts.ts + ts.dur) AS end_ts,
      MAX(ts.ts + ts.dur) - MIN(ts.ts) AS duration_ns,
      CAST(MAX(ts.ts + ts.dur) - MIN(ts.ts) AS REAL) / 1e6 AS duration_ms
    FROM thread_state ts
    JOIN thread t ON ts.utid = t.utid
    JOIN process p ON t.upid = p.upid
    WHERE p.name = '{args.process}'
    """
    result = query_tp(args.port, sql_fallback)
    rows = parse_columns(result)

    if rows:
        r = rows[0]
        dur_ms = r.get("duration_ms", 0)
        dur_severity = "excellent" if dur_ms < 1000 else "good" if dur_ms < 1500 else "fair" if dur_ms < 2000 else "poor" if dur_ms < 3000 else "critical"
        output = {
            "start_time": r["start_ts"],
            "end_time": r["end_ts"],
            "duration_ns": r["duration_ns"],
            "duration_ms": dur_ms,
            "method": "fallback_first_last_event",
            "severity": dur_severity,
            "has_issue": dur_severity in ("poor", "critical"),
            "note": "Used fallback method (process lifetime), may not reflect actual launch time",
        }
    else:
        output = {"error": f"No events found for process {args.process}"}

    save_result(output, "launch_range.json", args.output_dir)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
