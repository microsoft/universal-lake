# Step 5: Ingest

The ingesters pull from Graph, Azure, Dataverse and your uploaded CSVs into `dbo` tables. Run them through `Lake_Orchestrator` so every step is logged.

## How to run one step

1. Open `Lake_Orchestrator`.
2. In its first cell set `STEPS = 'audit'` (any step name below) and `RUN_MODE = 'first_load'`.
3. **Run all**.

Set `DRY_RUN = True` first if you want to see the plan and date ranges without running anything. To run everything in one go, leave `STEPS` blank; that's [step 8](../08-orchestrate/README.md).

(You can also open an ingester notebook and **Run all** to watch each cell, but then nothing is logged to `ops`.)

## The steps, in order

| # | `STEPS` name | What it loads | History | Module |
|---|---|---|---|---|
| 1 | `audit` | Every Copilot prompt and agent run | **First load / backfill**: last `backfillDays`. **Daily**: since the last load, re-reading a few days. | core |
| 2 | `licensed_users` | Who has a Copilot licence | Latest snapshot | core |
| 3 | `agent365` | Agent registry (CSV lander if the API fails) | Latest snapshot + history | agent365 |
| 4 | `processor` | Builds the curated fact table (step 6) | All loaded audit data | core |
| 5 | `upload_router` | Moves CSVs from `Files/analytics_hub_uploads` | Every file there | core |
| 6 | `org_data` | Department, title, country, manager | Latest snapshot | orgData |
| 7 | `m365_activity` | Daily Teams, Outlook, Word, Excel… use | Last 4 days, merged | m365Activity |
| 8 | `product_feedback` | Copilot feedback | Every uploaded export | productFeedback |
| 9 | `transcripts` | Copilot Studio transcripts | First load: `backfillDays`; daily: 14 days | agentEvaluator |
| 10–12 | `azure_ai`, `studio`, `viva` | Azure AI cost; Studio and Cowork credits | Azure: 90 days; others: every uploaded file | consumption |

On a first load run 1, 2 and 4 first (`STEPS = 'audit,licensed_users,processor'`), then the rest. Steps for sources you didn't pick are skipped.

**Workday only**: run `Copilot_Org_Data_Workday_Lander` by hand after uploading the extract, then `org_data`.

## The audit backfill: what to expect

* It fetches one query per day (`standard`) or per 2 hours (`large`). A 30-day backfill on `standard` is 30 queries.
* Each finished chunk is saved to `Files/_audit_staging`, so **a re-run resumes** instead of starting over.
* After 90 minutes (`standard`) or 5 hours (`large`) it stops and the step shows **`paused`**. That's normal for big backfills: run it again with the same `RUN_ID` and `RERUN_FAILED = True` until it says `succeeded`.
* A chunk that keeps failing becomes a **gap**. Daily runs refuse to start until you run `RUN_MODE = 'backfill'` over that period.
* The audit log keeps 180 days, so `backfillDays` can't be more than 180.

See what was fetched:

```sql
SELECT run_id, source, mode, window_start, window_end, days, status, note
FROM ops.backfill_ledger ORDER BY recorded_at DESC LIMIT 20;
```

## When a step fails

1. Read the error:
   ```sql
   SELECT step, status, error FROM ops.run_log
   WHERE run_id = '<run_id>' AND event = 'end' ORDER BY step_no;
   ```
2. **401 / 403**: run `Lake_Validate_Credentials`; it names what's missing.
3. **Timeout or `paused`**: run it again. Audit and transcripts resume.
4. To retry only what failed: `RUN_ID = '<run_id>'`, `RERUN_FAILED = True`. More in [RERUNS.md](../08-orchestrate/RERUNS.md).

Next: [Step 6: Process and promote](../06-process/README.md)
