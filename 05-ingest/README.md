# Step 5: Ingest

The ingesters pull from Graph, Azure, Dataverse and uploaded CSVs into **`dbo`** tables. These are the installer's notebooks, unchanged. This stage shows how to run them **one at a time**, see exactly what history each one fetches, and fix them one at a time.

## Two ways to run a step

| Way | How | Logged to `ops.*` | Use it when |
|---|---|---|---|
| **One orchestrator step** (recommended) | Open `Lake_Orchestrator`, set `STEPS = 'audit'` (or any step name below) and `RUN_MODE`, then **Run all** | yes: `run_log` and `backfill_ledger` | Normal manual runs. The arguments are the same ones the full run would pass. |
| **Open the notebook itself** | Open it, change its parameters cell, then **Run all** | no | Debugging: you see every cell's output and can stop half-way |

Run the steps in the order below on a first load. The processor needs `audit` and `licensed_users`, and the orchestrator enforces that.

Use `DRY_RUN = True` in the orchestrator to print the plan, the arguments and the history window of each step without running anything.

## The steps, in order

| # | Step (`STEPS` name) | Notebook | Module | Writes (`dbo`) | History it reads | Timeout std / large |
|---|---|---|---|---|---|---|
| 1 | `audit` | `Copilot_Audit_Log_Direct_Ingester` | core | `copilot_interactions_parsed` | **Backfill**: `BACKFILL_DAYS` (≤180). **Incremental**: since its last load plus a `LOOKBACK_DAYS` requery. | 2 h / 6 h |
| 2 | `licensed_users` | `Copilot_Licensed_Users_Direct_Ingester` | core | `copilot_licensed_users` | Snapshot: Graph report period D7, overwrite | 15 / 30 min |
| 3 | `agent365` | `Copilot_Agent365_Registry_Ingester` (falls back to `Copilot_Agent365_Lander` if it fails) | agent365 | `agents_365`, `agents_365_history`, `agents_365_detail_cache` | Snapshot plus history. Details are incremental, with a full refresh every 7 days. | 15 min |
| 4 | `processor` | `Copilot_Audit_Log_Processor` | core | `copilot_interactions_curated` | All of `copilot_interactions_parsed` (see [step 6](../06-process/README.md)) | 2 h / 3 h |
| 5 | `upload_router` | `AnalyticsHub_Upload_Router` | core | `analytics_hub_upload_log`, and moves files | Every CSV in `Files/analytics_hub_uploads` | 30 min |
| 6 | `org_data` | `Copilot_Org_Data_Direct_Ingester` | orgData | `copilot_org_data` (+ hierarchy) | Snapshot of every user, overwrite | 30 min / 1 h |
| 7 | `m365_activity` | `Copilot_M365_Activity_Ingester` | m365Activity | `m365_activity_daily` | Incremental and self-managed: re-reads the last 4 days | 1 h / 2 h |
| 8 | `product_feedback` | `Copilot_ProductFeedback_Ingester` | productFeedback | `user_feedback` | Every uploaded export, overwrite | 30 min |
| 9 | `transcripts` | `AgentEval_Transcript_Parser` | agentEvaluator | `agent_*` | **Backfill**: last `BACKFILL_DAYS`. **Incremental**: last 14 days. Merge. | 2 h |
| 10 | `azure_ai` | `Consumption_Ingest_Azure_AI` | consumption | `azure_*` | The last 90 days, overwrite | 1 h |
| 11 | `studio` | `Consumption_Ingest_Studio` | consumption | `studio_*` | Every file in `Files/landing/studio` | 30 min |
| 12 | `viva` | `Consumption_Ingest_Viva` | consumption | `viva_*` | Every file in `Files/landing/viva` | 30 min |

Steps 13 and later (promote, refresh, data check) are covered in [step 6](../06-process/README.md), [step 7](../07-semantic-model/README.md) and [step 8](../08-orchestrate/README.md).

**Workday CSV source only**: the orchestrator doesn't run `Copilot_Org_Data_Workday_Lander`. Run it by hand after you drop the extract in `Files/org_workday`, then run `org_data`.

**Which notebooks accept arguments.** Only the audit ingester, processor, transcript parser and refresh notebook have a tagged parameters cell. The others always use the values `npm run sync` baked in. To change those values (for example the licensed-users report period), edit the notebook in Fabric, or change `config.json`, rebuild and re-import.

## Backfill: what is fetched and when

The orchestrator **prints the window before each step** and writes it to `ops.backfill_ledger` as `planned`, then marks it `done`, `failed` or `paused`. So you can always answer *"which run fetched which days?"*

| `RUN_MODE` | Audit ingester gets | Processor | Transcripts |
|---|---|---|---|
| `first_load` | `MODE='backfill'`, `BACKFILL_DAYS` | `WRITE_MODE='overwrite'` | `LOOKBACK_DAYS = BACKFILL_DAYS` |
| `backfill` | the same as `first_load` | overwrite | `BACKFILL_DAYS` |
| `incremental` | `MODE='incremental'`: from the newest record already loaded, minus `LOOKBACK_DAYS` | `merge` | 14 days |

The `SCALE` profile changes how the audit window is fetched, not how much is fetched:

| | `standard` | `large` |
|---|---|---|
| `CHUNK_HOURS` (one audit query per chunk) | 24 | 2 |
| `TIME_BUDGET_MIN` (fetch time before it pauses) | 90 | 300 |
| `WINDOW_RETRIES`, `LOOKBACK_DAYS` | notebook defaults (3, 7) | 1, 3 |
| Notebook timeout | 2 h | 6 h |

### How the audit backfill behaves (important)

* The audit service answers one query per chunk. A 90-day backfill on `standard` is 90 queries, run 5 at a time.
* Every finished chunk is saved to `Files/_audit_staging` before anything is written to the table. **A rerun resumes**: chunks already fetched are reused, not queried again.
* When `TIME_BUDGET_MIN` runs out, the notebook stops with *"Time budget …"*. The orchestrator records this as **`paused`**, not failed. **Run the same step again** (same `RUN_MODE`, or `RERUN_FAILED` on the same `RUN_ID`) until it reports done. Large tenants often need several runs for 180 days.
* A failing chunk is retried and then split into smaller chunks, down to 1 hour. A chunk that still fails is a **gap**. `incremental` refuses to run while an unrecovered gap exists. Run a `backfill` that covers that period to repair it.
* The audit log keeps 180 days, so `BACKFILL_DAYS` can't be more than 180.

Watch it:

```sql
SELECT run_id, source, mode, window_start, window_end, days, status, note, recorded_at
FROM ops.backfill_ledger ORDER BY recorded_at DESC LIMIT 20;
```

## When a step fails

1. Find the error. Every `end` row in `ops.run_log` has the full error text:
   ```sql
   SELECT step, status, duration_s, error FROM ops.run_log
   WHERE run_id = '<run_id>' AND event = 'end' ORDER BY step_no;
   ```
2. **401 or 403**: run `Lake_Validate_Credentials`. It names the missing permission.
3. **Timeout**: re-run the step. Audit and transcripts resume. Snapshots simply reload.
4. Re-run only that step: `Lake_Orchestrator` with `RUN_ID = '<run_id>'` and `RERUN_FAILED = True`. See [RERUNS.md](../08-orchestrate/RERUNS.md).

Next: [Step 6: Process and promote](../06-process/README.md)
