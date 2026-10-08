# Step 8: Orchestrate

You already ran `Lake_Orchestrator` once in step 5. From now on it's the daily job: each run loads what's new, processes and promotes it, refreshes the models and runs a data check. Each step is logged separately, so you can see exactly what failed and re-run just that.

## Schedule the daily run

1. Open `Lake_Orchestrator` and set the first cell back to the defaults: `RUN_MODE = 'incremental'`, `DRY_RUN = False`, `STEPS`, `RUN_ID` blank, `RERUN_FAILED = False`. **Save** (schedules use the saved values).
2. **Run all** once by hand. This time the refresh steps run too (step 7 is done), so check they say `succeeded`.
3. **Run > Schedule** > once a day.

Don't start a manual run while the scheduled one is running: they share `Files/_audit_staging`.

## Run modes

| `RUN_MODE` | Audit log | Processor | Transcripts | Use it for |
|---|---|---|---|---|
| `first_load` | last `BACKFILL_DAYS` | rebuild | last `BACKFILL_DAYS` | the very first run |
| `backfill` | last `BACKFILL_DAYS` | rebuild | last `BACKFILL_DAYS` | more history, or repairing an audit gap |
| `incremental` | since the last load (re-reads a few days) | merge | last 14 days | the daily run |

Snapshot sources (licences, org data, feedback, uploads, Azure AI's 90 days) reload the same way in every mode.

## Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `RUN_MODE` | `incremental` | See above |
| `BACKFILL_DAYS` | `0` | `0` = the value from `config.json`. Max 180. |
| `SCALE`, `MODULES` | blank | Blank = the values from `config.json` |
| `STEPS` / `SKIP_STEPS` | blank | Run only / leave out these steps, e.g. `'audit,processor,promote'` |
| `START_FROM` | blank | Skip every step before this one |
| `RUN_ID` + `RERUN_FAILED` | blank / `False` | Re-run only the steps of that run that didn't succeed |
| `CONTINUE_ON_ERROR` | `True` | Keep going after a non-critical failure |
| `AUTO_RESUME` | `8` | Times a paused audit step is resumed automatically before the run moves on |
| `DRY_RUN` | `False` | Print the plan and stop |

`audit`, `licensed_users`, `processor` and `promote` are **critical**: if one fails, the rest of the run is skipped. After them come `refresh_universal`, `refresh_consumption`, `refresh_agent_evaluator` and `data_check`. Steps for sources you didn't pick show as `SKIP`.

## Check a run

```sql
-- Runs, newest first
SELECT run_id, run_mode, min(started_at) AS started,
       sum(CASE WHEN event = 'end' AND status <> 'succeeded' THEN 1 ELSE 0 END) AS not_ok
FROM ops.run_log GROUP BY run_id, run_mode ORDER BY started DESC LIMIT 20;

-- One run, step by step
SELECT step_no, step, status, round(duration_s / 60, 1) AS minutes, error
FROM ops.run_log WHERE run_id = '<run_id>' AND event = 'end' ORDER BY step_no, ended_at;
```

If any step fails, the run ends with an error naming the failed steps and the settings to re-run them, so a scheduled run shows as failed in the **Monitor** hub.

Next: [RERUNS.md](RERUNS.md), how to re-run and fix failures.
