# Reruns and recovery

All of these work on the same Lakehouse. None of them drops data, except where a step overwrites by design (snapshots, a backfill processor, promote).

## Which rerun?

| Situation | Set in `Lake_Orchestrator` |
|---|---|
| Some steps failed, and you want to retry only those | `RUN_ID='<that run>'`, `RERUN_FAILED=True`, **the same `RUN_MODE`** as the original run |
| The audit backfill came back `paused` (still not done after `AUTO_RESUME` automatic resumes) | The same as above, or raise `AUTO_RESUME`. Each pass resumes from `Files/_audit_staging`. |
| You fixed something, and want to go on from a given step | `START_FROM='processor'` (a new run) |
| You want just one or two steps | `STEPS='org_data,promote'` |
| Everything except a broken optional source | `SKIP_STEPS='product_feedback'` |
| Stop at the first failure of any kind | `CONTINUE_ON_ERROR=False` |
| See what would happen | Add `DRY_RUN=True` to any of the above |

**`RERUN_FAILED` in detail**: it reads the **latest** status of every step of `RUN_ID` from `ops.run_log` and leaves out the steps whose status is `succeeded`. It reruns `failed`, `paused` and `skipped` steps, and any step that never started. New rows are added under the **same `RUN_ID`**, so the run's history stays in one place. Dependencies count earlier successes in that run, so a processor that succeeded earlier in the run doesn't block promote.

Find the run ID:

```sql
SELECT run_id, run_mode, min(started_at) AS started FROM ops.run_log GROUP BY run_id, run_mode ORDER BY started DESC LIMIT 10;
```

## Rerunning by hand, outside the orchestrator

Opening a notebook and running it is always allowed. It isn't logged to `ops.*`. To keep the tables consistent, follow these rules:

* After any change in `dbo`, **run `Lake_Promote_Medallion`**, because the models read `gold`, not `dbo`. Use `TABLES='x'` for just that table.
* After promote, refresh the model: run the orchestrator with `STEPS='refresh_universal'`, or refresh it in the workspace.
* After an audit **backfill**, run the processor with **overwrite**, then promote, then refresh the models. `RUN_MODE='backfill'` does all of that for you.

## Is it safe to rerun this step?

| Step | Safe to rerun? | Why |
|---|---|---|
| `audit` | yes | Staged chunks are reused. The table write de-duplicates on the event ID. |
| `licensed_users`, `org_data`, `product_feedback`, `azure_ai`, `agent365` | yes | Snapshot or overwrite |
| `m365_activity` | yes | Merges the last 4 days again |
| `transcripts` | yes | Merges on natural keys |
| `m365_usage` | yes | Like `audit`: replaces whole days |
| `studio`, `viva` | yes | Reload every file in the landing folder |
| `upload_router` | yes | Files already moved are gone from the uploads folder. Re-upload a file to route it again. |
| `processor` | yes | `overwrite` rebuilds everything; `merge` upserts on `Id` |
| `promote` | yes | Overwrites each layer from `dbo` |
| `refresh_*` | yes | Refreshes the model again |
| `Lake_Deploy_Models` | yes | Updates the same models and connection |
| `Lake_Setup` | yes | Never drops anything. Blank values don't overwrite settings. `npm run deploy` runs it each time. |

## Failure → fix

| Step / message | Likely cause | Fix |
|---|---|---|
| any: `401` / `403` / `Authorization_RequestDenied` | Permission or consent missing | Run `Lake_Setup`, then fix what it lists ([step 2](../02-permissions/README.md)) |
| any: `Key Vault … Forbidden` | You (or the app) can't read the secret | Give the running identity **Key Vault Secrets User**, or use the `config.json` bypass ([step 2.2](../02-permissions/README.md#22-store-the-client-secret)) |
| `audit`: `Time budget of N min reached …` (`paused`) | A very long backfill that outlasted `AUTO_RESUME` | `RERUN_FAILED=True` on the same `RUN_ID`, or raise `AUTO_RESUME`. On a large tenant, use `SCALE='large'`. |
| `audit`: refuses, *unrecovered gap* | An older chunk failed for good | Run `RUN_MODE='backfill'` with `BACKFILL_DAYS` covering the gap |
| `audit`: chunks keep failing even at 1 h | Audit service trouble | Wait and rerun. Staged chunks are kept. |
| `licensed_users`: UPNs are 32-character hex strings, and nothing joins to org data | The reports setting conceals user names | Microsoft 365 admin center: **Settings > Org settings > Reports**, then clear *"Display concealed user, group, and site names"* |
| `processor`: skipped, *dependency audit did not succeed* | Audit failed earlier in the run | Fix audit, then use `RERUN_FAILED` |
| `promote`: *Required but not in gold* | The processor hasn't produced `copilot_interactions_curated` | Run `processor`, then `promote` |
| `promote`: *gold_tables.json not found* | Models folder not uploaded | Run `npm run deploy` ([step 4](../04-deploy/README.md)); it uploads `out/models` |
| `refresh_*`: SKIP, *no model_id* | The `models` step didn't run or failed | See the `models` step's error; rerun with `STEPS='models,refresh_universal'` |
| `refresh_*`: *credentials* or *data source* | Connection not bound, or the secret was rotated | Rerun with `STEPS='models,refresh_universal'`; if `models` warns about the tenant setting, see [step 6](../06-models/README.md#62-the-semantic-models) |
| `notebook.run`: *not found* | Notebook missing, or not under its exact name | Run `npm run deploy` again ([step 4](../04-deploy/README.md)) |
| `agent365` failed and `agent365_lander` succeeded | Registry API unavailable. The CSV fallback filled `agents_365`. | No action needed. `RERUN_FAILED` will try the registry again. |
| Timeout on any step | Large tenant | `SCALE='large'`, or rerun the step |

## Starting over

Only start over if you really need to. Reruns are almost always enough.

1. Drop the data tables: `dbo.*`, `bronze.*`, `silver.*`, `gold.*`. Keep `ops.config`.
2. Delete `Files/_audit_staging`.
3. Run `Lake_Orchestrator` with `RUN_MODE='first_load'`.
