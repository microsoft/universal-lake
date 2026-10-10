# Step 7: Orchestrate

You already ran `Lake_Orchestrator` once in step 5. From now on it's the daily job: each run loads what's new, processes and promotes it, refreshes the models and runs a data check. Each step is logged separately, so you can see exactly what failed and re-run just that.

## Schedule the daily run

1. Open `Lake_Orchestrator` and set the first cell back to the defaults: `RUN_MODE = 'incremental'`, `DRY_RUN = False`, `STEPS`, `RUN_ID` blank, `RERUN_FAILED = False`. **Save** (schedules use the saved values).
2. **Run all** once by hand. This time the refresh steps run too (step 6 is done), so check they say `succeeded`.
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

These are the only ones you normally touch:

| Parameter | Default | When to change it |
|---|---|---|
| `RUN_MODE` | `incremental` | `first_load` once at the start; `backfill` for more history or to fill a gap |
| `RUN_ID` + `RERUN_FAILED` | blank / `False` | To retry a run: that run's ID and `True`. Only the steps that didn't succeed run. |
| `STEPS` | blank | To run one step alone, e.g. `'org_data'` |
| `DRY_RUN` | `False` | `True` to print the plan and date ranges without running anything |

<details>
<summary>Advanced parameters (leave as is)</summary>

| Parameter | Default | Meaning |
|---|---|---|
| `BACKFILL_DAYS` | `0` | `0` = `backfillDays` from `config.json`. Max 180. |
| `SCALE`, `MODULES` | blank | Blank = the values from `config.json` |
| `SKIP_STEPS` | blank | Leave out these steps |
| `START_FROM` | blank | Skip every step before this one |
| `CONTINUE_ON_ERROR` | `True` | Keep going after a non-critical failure |
| `AUTO_RESUME` | `8` | Extra automatic passes for an audit backfill that hits its time budget |

</details>

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
