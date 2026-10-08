# Step 5: Ingest

One notebook, `Lake_Orchestrator`, runs every ingester for the sources you picked, in the right order, then processes and promotes the data (step 6). Every step is logged to `ops`.

## Run it

1. Open `Lake_Orchestrator`.
2. In the first cell, change one line: `RUN_MODE = 'first_load'`.
3. **Run all**. Note the `RUN_ID` it prints.

That's it. Leave the other settings as they are. The model refresh steps show `SKIP` for now; they start working after step 7.

Optional: set `DRY_RUN = True` first to only print the plan (which steps, which date ranges) without running anything.

## What it runs, in order

You don't need to pick these; they run automatically. The names show up in the plan and in `ops.run_log`.

| # | Step | What it loads | History | Module |
|---|---|---|---|---|
| 1 | `audit` | Every Copilot prompt and agent run | **First load / backfill**: last `backfillDays`. **Daily**: since the last load, re-reading a few days. | copilotInteractions |
| 2 | `licensed_users` | Who has a Copilot licence | Latest snapshot | copilotInteractions |
| 3 | `agent365` | Agent registry (CSV lander if the API fails) | Latest snapshot + history | agent365 |
| 4 | `processor` | Builds the curated fact table (step 6) | All loaded audit data | copilotInteractions |
| 5 | `upload_router` | Moves CSVs from `Files/analytics_hub_uploads` | Every file there | copilotInteractions |
| 6 | `org_data` | Department, title, country, manager | Latest snapshot | orgData |
| 7 | `m365_activity` | Daily Teams, Outlook, Word, Excel… use | Last 4 days, merged | m365Activity |
| 8 | `product_feedback` | Copilot feedback | Every uploaded export | productFeedback |
| 9 | `transcripts` | Copilot Studio transcripts | First load: `backfillDays`; daily: 14 days | agentEvaluator |
| 10–12 | `azure_ai`, `studio`, `viva` | Azure AI cost; Studio and Cowork credits | Azure: 90 days; others: every uploaded file | consumption |

After these come `promote` ([step 6](../06-process/README.md)) and the model refreshes. Steps for sources you didn't pick show `SKIP`.

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
3. **Retry only what failed** (also for a timeout or `paused`): in the first cell set `RUN_ID = '<run_id>'` and `RERUN_FAILED = True`, then **Run all**. Steps that already succeeded are skipped; audit and transcripts resume where they stopped.
4. **Run just one step** (e.g. after fixing a permission): `STEPS = 'org_data'`. This is the only time you need `STEPS`. More in [RERUNS.md](../08-orchestrate/RERUNS.md).

Next: [Step 6: Process and promote](../06-process/README.md)
