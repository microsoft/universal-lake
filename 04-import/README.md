# Step 4: Import into Fabric and initialise

You take what `npm run all` built in `out/` and put it into the workspace from step 1: notebooks, model definitions and, if you use them, CSV exports. Then two notebooks set up the Lakehouse and check every credential. Nothing is ingested yet.

## 4.1 Import the notebooks

1. Open the workspace and choose **Import > Notebook > From this computer**.
2. Select **every `.ipynb` file in `out/notebooks/`** (you can select them all at once) and choose **Open**. Don't import the copies in the numbered folders of this repo: those have no Lakehouse attached and no parameters filled in.
3. Wait until they all appear in the workspace list.

| Group | Notebooks |
|---|---|
| This repo | `lake_ops`, `Lake_Init`, `Lake_Validate_Credentials`, `Lake_Promote_Medallion`, `Lake_Deploy_Models`, `Lake_Orchestrator` |
| Core | `Copilot_Audit_Log_Direct_Ingester`, `Copilot_Licensed_Users_Direct_Ingester`, `Copilot_Audit_Log_Processor`, `AnalyticsHub_Upload_Router`, `AnalyticsHub_Refresh_Model`, `AnalyticsHub_Data_Check`, `AnalyticsHub_Load_Status` (not used here; `ops.run_log` replaces it) |
| `orgData` | `Copilot_Org_Data_Direct_Ingester` (and `Copilot_Org_Data_Workday_Lander` with Workday) |
| `m365Activity` | `Copilot_M365_Activity_Ingester` |
| `agent365` | `Copilot_Agent365_Registry_Ingester`, `Copilot_Agent365_Lander` |
| `productFeedback` | `Copilot_ProductFeedback_Ingester` |
| `consumption` | `Consumption_Ingest_Azure_AI`, `Consumption_Ingest_Studio`, `Consumption_Ingest_Viva` |
| `agentEvaluator` | `AgentEval_Transcript_Parser` |

`out/notebooks/MANIFEST.json` is the exact list for your configuration.

**Names must not change.** The orchestrator runs notebooks by name, and every repo notebook starts with `%run lake_ops`. If a notebook with the same name already exists, Fabric doesn't overwrite it: it imports the new one as `lake_ops 1` (or similar), and the old one keeps running. When you re-import, **delete the old notebook first**, then import again.

## 4.2 Check the Lakehouse is attached

Open any two of the imported notebooks, for example `Lake_Init` and `Copilot_Audit_Log_Direct_Ingester`. In the **Explorer** pane on the left, `UniversalLake_LH` should be listed under *Lakehouses* with a pin (**default**).

If it isn't there (because `config.json` had no Lakehouse ID when you built), in **each** notebook choose **Add data items > Existing data source**, pick `UniversalLake_LH`, then open its **...** menu and choose **Set as default lakehouse**. Or fix `config.json`, run `npm run all`, delete the notebooks and import them again; that's quicker for 20 notebooks.

## 4.3 Upload the model definitions

1. Open `UniversalLake_LH`.
2. In the explorer, right-click **Files** and choose **New subfolder**, named `universal_lake`. (`Lake_Init` also creates it, so if you run 4.5 first it is already there.)
3. Right-click `universal_lake`, choose **Upload > Upload folder** and pick the **`out/models`** folder itself (not its contents).

You should end up with:

```
Files/universal_lake/models/gold_tables.json
Files/universal_lake/models/universal/definition.json
Files/universal_lake/models/consumption/definition.json
Files/universal_lake/models/agentEvaluator/definition.json
```

If you see `Files/universal_lake/universal/...` (no `models` level) or `Files/models/...`, you uploaded the wrong level: delete it and upload again. The other files in those folders (`model.bim`, `relationships.txt` and so on) are for you to read; the notebooks ignore them.

## 4.4 Upload your CSV exports (only for `csv` sources)

For each source you set to `csv` in step 3, download the export and upload it to the matching Lakehouse folder (created by `Lake_Init` in 4.5). If you're not sure which folder, put it in `Files/analytics_hub_uploads`: the Upload Router recognises the file and moves it.

| Source | Folder | Export from |
|---|---|---|
| Any | `Files/analytics_hub_uploads` | The router works out where it belongs |
| `agent365` | `Files/agent365` | Microsoft 365 admin center > Agents > All agents > Export (`agents.csv`) |
| `productFeedback` | `Files/product_feedback` | Microsoft 365 admin center > Health > Product feedback > Export |
| `studioCredits` | `Files/landing/studio` | Power Platform admin center > Licensing > Products > Copilot Studio: the Summary, Environments and Agents exports |
| `coworkCredits` | `Files/landing/viva` | Viva Insights > Copilot Consumption Dashboard > Export (both CSVs) |
| `workday` | `Files/org_workday` | A Workday report of active workers with Primary Work Email, exported to CSV |

You can skip this now and upload later; the ingesters just find nothing to load.

## 4.5 Run `Lake_Init`

Open `Lake_Init`. Its parameters cell is already filled in from `config.json`; check it looks right:

| Parameter | Notes |
|---|---|
| `TENANT_ID`, `CLIENT_ID`, `KEY_VAULT_URI`, `SECRET_NAME` | Saved to `ops.config`, so the other notebooks read them from there |
| `SQL_ENDPOINT` | Host only. Used by `Lake_Deploy_Models` for the model connection. |
| `SCALE`, `BACKFILL_DAYS` | From `scale` and `backfillDays`. You can override the backfill days per run later. |
| `MODULES` | The modules your `dataSources` switch on. The orchestrator skips steps for anything not listed. |
| `MODEL_ID_*` | Leave blank. `Lake_Deploy_Models` fills these in. |

Choose **Run all**. The first run takes a minute or two while Spark starts. It is safe to re-run: it never drops anything, and a blank parameter never wipes a saved value.

What it creates:

| Schema | Holds | Written by |
|---|---|---|
| `dbo` | The ingesters' working tables, exactly as the installer writes them | Ingesters and processor (step 5 and 6) |
| `bronze` | Raw extracts: parsed audit records, raw payloads, upload and load logs | `Lake_Promote_Medallion` |
| `silver` | Cleaned intermediate tables and history that the models don't read | `Lake_Promote_Medallion` |
| `gold` | Exactly the tables the semantic models read | `Lake_Promote_Medallion` |
| `ops` | `config`, `run_log`, `backfill_ledger`, `table_layers` | Every `Lake_*` notebook |

plus the `Files/` folders in 4.4 and `Files/universal_lake/`.

The notebook ends by listing any required setting that is still blank. Check it with:

```sql
SELECT * FROM ops.config ORDER BY key;
```

If it stops with "This Lakehouse is not schema-enabled", the Lakehouse was created without *Lakehouse schemas*: go back to [step 1.3](../01-fabric/README.md#13-create-the-lakehouse-tick-lakehouse-schemas). If it stops with "No default Lakehouse", see 4.2.

## 4.6 Run `Lake_Validate_Credentials`

Open it and choose **Run all**. Its parameters are filled in from `config.json`. It writes nothing, so you can run it as often as you like; run it again whenever an ingester fails with 401 or 403.

| Check | Fix if it fails |
|---|---|
| Key Vault secret readable | Give yourself *Key Vault Secrets User* on the vault. |
| Graph token | Wrong tenant or app ID, or an expired secret. Run `setup-app.ps1 -RotateSecret`. |
| Graph permissions for `<module>` | Add the missing permission and grant consent. New consent can take a few minutes to appear in tokens. |
| Audit log query API | Turn on audit logging. New tenants can take 24 hours. |
| Usage reports show real user names | Turn off report name concealment. |
| Copilot packages API | The tenant needs Copilot and Agent 365. Otherwise set `dataSources.agent365` to `csv`. |
| Azure subscription and cost query | Assign the three reader roles on that subscription. |
| Dataverse application user, transcripts readable | Add the application user and the Bot Transcript Viewer role. |

With `STRICT = True` (the default) it raises at the end if any required check failed. **Don't start step 5 until every required check passes.**

## Re-building later

* **Config change** (new module, data source or subscription): `npm run all`, then delete and re-import the notebooks that `sync` reports as changed or new.
* **New source version**: see [Where the notebook code comes from](../README.md#where-the-notebook-code-comes-from).
* **Only the models changed**: `npm run models`, re-upload `out/models`, then run `Lake_Deploy_Models` (step 7).

Next: [Step 5: Ingest](../05-ingest/README.md)
