# Step 5: Ingest

One notebook, `Lake_Orchestrator`, runs every ingester for the sources you picked, in the right order, then processes and promotes the data. Every step is logged to `ops`.

## Run it

**From your PC:** `npm run deploy -- --run first_load` starts it, then keeps watching and says in the terminal when it ends: succeeded, or which steps failed, each with its error, and how to re-run just those. It ends with a link to each semantic model. When everything succeeded it says what to do next (check the data, then schedule the daily `incremental` run). (In Fabric's Monitor hub a failed run only says *System cancelled the Spark session due to statement execution failures*; that is Fabric's generic message whenever the orchestrator reports a failed step.) Closing the window doesn't stop the run; `npm run deploy -- --watch` picks it up again (it deploys nothing). It also prints a link to the notebook. The link opens the notebook, not the run: to watch the run, open the **Run** tab at the top of the notebook (not the **Run all** menu), choose **Recent runs** and open the newest one. Each cell shows whether it has run and its output so far. The **Monitor** hub lists the run too. Or in Fabric:

1. Open `Lake_Orchestrator` (deploy printed a link).
2. In the first cell, change one line: `RUN_MODE = 'first_load'`.
3. **Run all**. Note the `RUN_ID` it prints.

That's it. Leave the other settings as they are. The run ends by creating the semantic models and refreshing them; nobody needs to sign in.

Optional: set `DRY_RUN = True` first to only print the plan (which steps, which date ranges) without running anything.

## What it runs, in order

You don't need to pick these; they run automatically. The names show up in the plan and in `ops.run_log`.

| # | Step | What it loads | History | Module |
|---|---|---|---|---|
| 1 | `audit` | Every Copilot prompt and agent run | **First load / backfill**: last `backfillDays`. **Daily**: since the last load, re-reading a few days. | copilotInteractions |
| 2 | `licensed_users` | Who has a Copilot licence | Latest snapshot | copilotInteractions |
| 3 | `agent365` | Agent registry (CSV lander if the API fails) | Latest snapshot + history | agent365 |
| 4 | `processor` | Builds the curated fact table ([step 6](../06-models/README.md#61-check-the-data)) | All loaded audit data | copilotInteractions |
| 5 | `upload_router` | Sorts the CSVs deploy uploaded into their source folders | Every file there | copilotInteractions |
| 6 | `org_data` | Department, title, country, manager | Latest snapshot | orgData |
| 7 | `m365_activity` | Daily Teams, Outlook, Word, Excel… use | Last 4 days, merged | m365Activity |
| 8 | `product_feedback` | Copilot feedback | Every uploaded export | productFeedback |
| 9 | `transcripts` | Copilot Studio transcripts | First load: `backfillDays`; daily: 14 days | agentEvaluator |
| 10–12 | `azure_ai`, `studio`, `viva` | Azure AI cost; Studio and Cowork credits | Azure: 90 days; others: every uploaded file | consumption |
| 13 | `m365_usage` | Teams, Outlook, Word, Excel, PowerPoint audit events, including mail items accessed. Writes `m365_usage_rollup` (daily, no AI interactions), `connected_ai_app_interactions`, `ai_app_interactions` and `m365_teams_call_participation` (Teams call and meeting join/leave times, time in call and screen-share sessions from `CallParticipantDetail` / `MeetingParticipantDetail`). Copilot interactions come from the `audit` step, which must also run | Like `audit` | m365Usage |

After these come `promote` ([step 6](../06-models/README.md#61-check-the-data)), `models` (creates and connects the semantic models) and the model refreshes. Steps for sources you didn't pick show `SKIP`.

**Workday only**: run `Copilot_Org_Data_Workday_Lander` by hand after deploying the extract, then `org_data`.

## The audit backfill: what to expect

**What a query is.** The audit step asks Purview for Copilot events through the Graph audit search API. Each request is one *query*: an audit search job, like a search in the Purview portal, over one time window. Purview runs it in the background, and the notebook waits for it, then downloads the results.

**Limits.**

* Purview runs about **10 audit queries at once** per tenant. The notebook runs **5 in parallel**, leaving room for other admins. If Purview throttles it (HTTP 429), it lowers that number for the rest of the run.
* A window is **1 day** on `standard`, **2 hours** on `large` (busy tenants have too many events for a 1-day window). A 30-day backfill on `standard` is 30 queries, about 5 running at a time.
* A window that keeps failing is retried, then **split in half** (down to 1 hour) and the halves are queried.
* Purview keeps **180 days** of audit data, so `backfillDays` is at most 180.

**You don't need to re-run it by hand.**

* Each finished window is saved to `Files/_audit_staging`. A run that stops resumes from there instead of starting over.
* Each pass of the audit step stops cleanly after 90 minutes (`standard`) or 5 hours (`large`), so Fabric doesn't kill it mid-write. The orchestrator then **resumes it automatically**, up to `AUTO_RESUME` (default 8) more times, before moving on. That covers about 12 hours on `standard` and 45 on `large`.
* Only if it's still not done after that does the step end `paused`. Then retry with `RUN_ID` and `RERUN_FAILED = True` (see below), or raise `AUTO_RESUME`.
* A window that fails even at 1 hour is a **gap**. The run reports it, and the next daily run refuses to start until you run once with `RUN_MODE = 'backfill'` over that period. This stops a gap from being silently skipped.

See what was fetched (in the Lakehouse's SQL analytics endpoint):

```sql
SELECT TOP 20 run_id, source, mode, window_start, window_end, days, status, note
FROM ops.backfill_ledger ORDER BY recorded_at DESC;
```

## When a step fails

1. Read the error:
   ```sql
   SELECT step, status, error FROM ops.run_log
   WHERE run_id = '<run_id>' AND event = 'end' ORDER BY step_no;
   ```
2. **401 / 403**: run `Lake_Setup` (or `npm run deploy` again); it names what's missing. See [TROUBLESHOOTING.md](../TROUBLESHOOTING.md#lake_setup-checks).
3. **Retry only what failed** (also for a timeout or `paused`): in the first cell set `RUN_ID = '<run_id>'` and `RERUN_FAILED = True`, then **Run all**. Steps that already succeeded are skipped; audit and transcripts resume where they stopped. From your PC: `npm run deploy -- --rerun-failed` deploys (so any fix you pulled is included), then does the same for the last run and watches it; add `--run-id <run_id>` for an older run. It doesn't change the notebook's saved settings.
4. **Run just one step** (e.g. after fixing a permission): `STEPS = 'org_data'`. This is the only time you need `STEPS`. More in [RERUNS.md](../07-orchestrate/RERUNS.md).

Next: [Step 6: Check the data and the models](../06-models/README.md)
