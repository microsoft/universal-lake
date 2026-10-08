# Step 8: Orchestrate

`Lake_Orchestrator` runs the same steps, in the same order and with the same arguments and timeouts, as the installer's `CopilotAdoptionPipeline`. The difference: each step is a separate `notebook.run`, so you get:

* **a plan first.** It prints every step, its arguments and the history window it will fetch. `DRY_RUN = True` stops there.
* **a log per step.** It writes a start and an end row to `ops.run_log`, with status, duration, exit value and the full error.
* **a backfill ledger.** Every source that reads history writes its window to `ops.backfill_ledger` before (`planned`) and after (`done`, `failed` or `paused`).
* **partial reruns.** You can rerun only what failed, or start from any step. See [RERUNS.md](RERUNS.md).

## Import

You imported `Lake_Orchestrator` from `out/notebooks` in step 4, with the Lakehouse attached. Make sure `lake_ops`, `Lake_Promote_Medallion` and every installer notebook are in the **same workspace** under their exact names. `notebook.run` finds them by name. See [step 4](../04-import/README.md).

## Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `RUN_MODE` | `incremental` | `first_load`, `backfill` or `incremental` (see below) |
| `BACKFILL_DAYS` | `0` | `0` uses `backfill_days` from `ops.config`. Range 1–180. |
| `SCALE` | blank | blank uses `ops.config`. `standard` or `large` changes the audit chunking, time budget and timeouts. |
| `MODULES` | blank | blank uses `ops.config`. `core` is always included. |
| `STEPS` | blank | Run only these steps, e.g. `'audit,processor,promote'` |
| `SKIP_STEPS` | blank | Leave these steps out |
| `START_FROM` | blank | Skip every step before this one |
| `RUN_ID` | blank | Blank starts a new run. Set it with `RERUN_FAILED` to resume that run. |
| `RERUN_FAILED` | `False` | With `RUN_ID`: run only the steps that didn't succeed in that run |
| `CONTINUE_ON_ERROR` | `True` | When a non-critical step fails, log it and go on |
| `DRY_RUN` | `False` | Print the plan and stop |

## Run modes: what gets fetched

| `RUN_MODE` | Audit log | Processor | Transcripts | Model refresh | Use it for |
|---|---|---|---|---|---|
| `first_load` | backfills `BACKFILL_DAYS` | overwrite | last `BACKFILL_DAYS` | overwrite | the very first run |
| `backfill` | backfills `BACKFILL_DAYS` | overwrite | last `BACKFILL_DAYS` | overwrite | widening history, or repairing an audit gap |
| `incremental` | since the last load, re-reading `LOOKBACK_DAYS` | merge | last 14 days | merge | the daily run |

Snapshot sources (licensed users, org data, product feedback, Azure AI's 90 days, Studio and Viva uploads) reload the same way in every mode. M365 activity always manages its own incremental window. The full per-step detail is in [step 5](../05-ingest/README.md).

## The steps

| # | Step | Critical | Needs | Module |
|---|---|---|---|---|
| 1 | `audit` | yes | | core |
| 2 | `licensed_users` | yes | | core |
| 3 | `agent365` (if it fails, `agent365_lander` runs instead) | | | agent365 |
| 4 | `processor` | yes | audit, licensed_users | core |
| 5 | `upload_router` | | | core |
| 6 | `org_data` | | | orgData |
| 7 | `m365_activity` | | | m365Activity |
| 8 | `product_feedback` | | | productFeedback |
| 9 | `transcripts` | | | agentEvaluator |
| 10–12 | `azure_ai`, `studio`, `viva` | | | consumption |
| 13 | `promote` | yes | processor | core |
| 14–16 | `refresh_universal`, `refresh_consumption`, `refresh_agent_evaluator` | | promote, plus `model_id.<key>` in `ops.config` | core / consumption / agentEvaluator |
| 17 | `data_check` | | | core |

* **Critical** means that if it fails, every later step is logged as `skipped` and not run.
* **Needs** applies to the current run only. A dependency blocks only if it **ran** in this run (or earlier in the same `RUN_ID`) and didn't succeed. If you leave it out with `STEPS` or `START_FROM`, you get a note, and the step uses whatever is already in `dbo`.
* Steps of modules you didn't select are shown as `SKIP (module … not selected)`.

## Recommended sequence

1. **Plan it.** Set `RUN_MODE='first_load'` and `DRY_RUN=True`, then read the plan and the backfill summary.
2. **First load.** Set `RUN_MODE='first_load'` and `DRY_RUN=False`.
   * If the audit step comes back **`paused`** (the time budget ran out), rerun with the printed `RUN_ID` and `RERUN_FAILED=True` until it succeeds. Each pass resumes from the staged windows.
   * The refresh steps are skipped until you've deployed the models.
3. **Deploy the models.** Run `Lake_Deploy_Models` ([step 7](../07-semantic-model/README.md)).
4. **Daily.** Schedule `Lake_Orchestrator` with `RUN_MODE='incremental'`: open the notebook, then **Run > Schedule**, once a day. Schedules run the notebook with its saved default parameters, and `incremental` is the default.
5. **Widening history later.** Run `RUN_MODE='backfill'` with a larger `BACKFILL_DAYS`. Chunks that were already fetched are reused.

> Don't run the orchestrator while a scheduled run is in progress. Two runs of the audit ingester share `Files/_audit_staging`.

## Watching a run

The last cell shows the run and the ledger. Afterwards:

```sql
-- Every run, newest first
SELECT run_id, run_mode, min(started_at) AS started, max(ended_at) AS ended,
       sum(CASE WHEN event = 'end' AND status = 'succeeded' THEN 1 ELSE 0 END) AS ok,
       sum(CASE WHEN event = 'end' AND status <> 'succeeded' THEN 1 ELSE 0 END) AS not_ok
FROM ops.run_log GROUP BY run_id, run_mode ORDER BY started DESC LIMIT 20;

-- One run, step by step
SELECT step_no, step, notebook, status, round(duration_s / 60, 1) AS minutes, exit_value, error
FROM ops.run_log WHERE run_id = '<run_id>' AND event = 'end' ORDER BY step_no, ended_at;

-- What history each run asked for
SELECT run_id, source, mode, window_start, window_end, days, status, note, recorded_at
FROM ops.backfill_ledger ORDER BY recorded_at DESC LIMIT 50;
```

`ops.run_log.params_json` holds the exact arguments each step got.

If any step didn't succeed, the run ends with an error that names the failed steps and prints the rerun settings. A scheduled run then shows as failed in the Monitor hub, which is where to look.

Next: [RERUNS.md](RERUNS.md), how to rerun safely.
