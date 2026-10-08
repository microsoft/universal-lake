# Step 8: Orchestrate

`Lake_Orchestrator` runs every step from steps 5 and 6, in order, then refreshes the models and runs a data check. It's the same sequence as the installer's pipeline, but each step is logged separately, so you can see exactly what failed and re-run just that.

## Your first full run

1. Open `Lake_Orchestrator`. In the first cell set `RUN_MODE = 'first_load'` and `DRY_RUN = True`. **Run all**.
   It prints the plan: each step, and how many days of history it will fetch. Check it.
2. Set `DRY_RUN = False`. **Run all**. Note the `RUN_ID` it prints.
3. If `audit` ends `paused` (big backfill), set `RUN_ID = '<that id>'`, `RERUN_FAILED = True` and run again. Repeat until it succeeds.
4. If you haven't yet, run `Lake_Deploy_Models` ([step 7](../07-semantic-model/README.md)). Until then the refresh steps are skipped.

## Schedule the daily run

Open `Lake_Orchestrator` > **Run > Schedule** > once a day. Make sure the saved first cell has `RUN_MODE = 'incremental'` and `DRY_RUN = False` (the defaults), because schedules use the saved values.

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
