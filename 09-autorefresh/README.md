# Step 9: Auto-refresh (set it and forget it)

After the first load (step 5), the lake needs only one thing: `Lake_Orchestrator` running once a day. Each run loads the new days from every source, processes and promotes them, refreshes the semantic models and runs a data check. This step makes that happen by itself, and shows how to start a run yourself when you need one.

## What runs by itself

| What | When | Set up in |
|---|---|---|
| `Lake_Orchestrator`: API sources, processing, model refresh | Every day at the time you pick | This step, 1 to 3 |
| Your published Power BI reports | After the lake's daily run | This step, 4 |
| CSV sources (product feedback, Studio and Viva credits) | **Not automatic**: someone exports them | [New CSV exports](#new-csv-exports) |

## Set it up once

### 1. Check the model connection works unattended

Scheduled runs refresh the models with nobody signed in, so the models' connection to the Lakehouse must not depend on you.

* **Best:** the workspace identity. `npm run deploy` sets it up when you are workspace **Admin** on a paid **F** capacity. Nothing expires.
* **Otherwise:** sign the connection in once in the portal: **Settings (gear) > Manage connections and gateways** > the "Universal Lake" connection > **Edit credentials > OAuth 2.0 > Sign in > Save**. It stays signed in until that account loses access or its password changes.

The sign-in `npm run deploy` does from your terminal lasts only about an hour, so it is **not** enough for a schedule. Details: [step 6](../06-models/README.md).

### 2. Check the notebook's saved values

Schedules use what is **saved** in the first cell of `Lake_Orchestrator`. `npm run deploy` saves the right ones: `RUN_MODE = 'incremental'`, `RUN_ID` and `STEPS` blank, `RERUN_FAILED = False`, `DRY_RUN = False`. If you changed them by hand, set them back and **Save**, or run `npm run deploy` again.

### 3. Turn on the daily schedule

From your PC (uses this PC's time zone):

```powershell
npm run deploy -- --schedule 06:00
```

Pick a quiet time; a daily run usually takes well under an hour. For another time zone add `--time-zone "GMT Standard Time"` (a Windows time zone name). Running it again changes the time; it never adds a second schedule. It deploys nothing.

Or in Fabric: open `Lake_Orchestrator` > **Run > Schedule** > **On**, **Daily**, a time, an end date far ahead > **Apply**.

The next day, check the **Monitor** hub (left bar in Fabric) lists the run, or run `npm run deploy -- --watch`.

### 4. Schedule your reports (if you published any)

Published reports (step 8) keep their own copy of the data. In Fabric open each published semantic model > **Settings > Scheduled refresh** > on, once a day, **1 to 2 hours after** the lake's run. Its data source credentials must be set (**Edit credentials > OAuth2**).

The lake's own semantic models need nothing: `Lake_Orchestrator` refreshes them at the end of each run.

### 5. Get told when a run fails

A run with a failed step ends as **Failed**, so it shows in red in the **Monitor** hub. To get an email instead of checking:

* In `Lake_Orchestrator` > **Run > Schedule**, turn on failure notifications if your Fabric offers them; or
* Run it from a Data pipeline (a **Notebook** activity) with an **Office 365 Outlook** or **Teams** activity on failure, and schedule the pipeline instead of the notebook.

### 6. Put the expiry dates in your calendar

These are what quietly stop a "set and forget" lake. Add a reminder a few weeks before each:

| What | When it bites | Fix |
|---|---|---|
| The app's client secret | On its expiry date (step 2.2). Every API source fails. | New secret in Entra; update Key Vault (or `config.json`, then `npm run deploy`) |
| The schedule's end date | `--schedule` sets 5 years ahead (1 if Fabric refuses 5) | Run `--schedule` again |
| The account that owns the schedule or signed the connection | Leaves, loses workspace access, or changes password | Another admin runs `--schedule` and signs the connection in |
| The capacity | Paused, or the free trial ends | Resume it or assign another (step 1) |

## Run it yourself

| You want to | Do this |
|---|---|
| Load the new days now | `npm run deploy -- --run incremental`, or in Fabric open `Lake_Orchestrator` > **Run all** |
| Follow a run that is going | `npm run deploy -- --watch` (says when it ends; Ctrl+C any time, the run keeps going) |
| Retry only what failed | `npm run deploy -- --rerun-failed` ([RERUNS.md](../07-orchestrate/RERUNS.md)) |
| Load more history or fill a gap | `npm run deploy -- --run backfill` (`backfillDays` in `config.json`, max 180) |
| Run one source alone | In Fabric: `STEPS = 'org_data'` in the first cell, **Run all**. Don't Save, or the schedule uses it too. |

`--run` and `--rerun-failed` deploy first (only what changed), so they also pick up a new version of this repo. They don't change the notebook's saved values or its schedule.

Don't start a run while the scheduled one is running: they share `Files/_audit_staging`. Check the Monitor hub first.

## New CSV exports

CSV sources are only as new as the last file you gave the lake. When you have new exports:

1. Save them in your `exportsFolder` (the same folder as before; old files can stay).
2. Run `npm run deploy`. It uploads the new ones.
3. The next run (scheduled, or `--run incremental`) loads them.

A monthly reminder to export them is usually enough.

## Take a new version of this repo

```powershell
git pull
npm run deploy
```

This sends only what changed, keeps the schedule, and saves the defaults in `Lake_Orchestrator` again. The next scheduled run uses the new code.

## Change or stop the schedule

| You want to | Do this |
|---|---|
| Change the time | `npm run deploy -- --schedule 07:30` |
| Stop it | `npm run deploy -- --schedule off`. The data stays; you can still run it by hand. |
| See it | `Lake_Orchestrator` > **Run > Schedule** |

Pausing the capacity also stops it: runs fail while it is paused, and the first one after you resume carries on from the last date loaded.

## If a scheduled run fails

1. `npm run deploy -- --watch` shows how the latest run ended and which steps failed.
2. Fix the cause, then `npm run deploy -- --rerun-failed`. Only those steps run.
3. Missed a few days? Usually nothing to do: the next run picks up from the last date loaded. For a gap of more than a week or so, run `--run backfill`.

More: [RERUNS.md](../07-orchestrate/RERUNS.md) and [TROUBLESHOOTING.md](../TROUBLESHOOTING.md).
