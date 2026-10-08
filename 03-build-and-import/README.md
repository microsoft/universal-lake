# Stage 3: Build and import

The installer fills in each notebook's settings and uploads it through the Fabric API. Here you **build the same files on your PC from the installer's own code**, look at them if you want, and import them yourself.

## 3.1 Build

`config.json` must have the app values (stage 1) and the workspace and Lakehouse values (stage 2).

```powershell
npm run all
```

Each step is also its own script, so you can re-run just one:

| Script | Does | Output |
|---|---|---|
| `npm run check` | Confirms the source repo clone is at `pinnedCommit` and lists any local changes that would be baked in. `node scripts/check_source.mjs --strict` fails instead of warning. | console |
| `npm run sync` | Runs the installer's notebook transform (`catalog.js`, `transform/notebook.js`, `steps/fabric.js`). It fills in tenant, app, Key Vault, workspace, Lakehouse, backfill days and data sources, and binds the default Lakehouse. It picks only the notebooks your modules and data sources need, prints the Graph permissions they need, and **lists what changed since the last sync**. | `out/notebooks/*.ipynb`, `MANIFEST.json`, `out/SOURCE.lock.json` |
| `npm run models` | Runs the installer's model transform (`transform/model.js`) for each model, pointed at your SQL endpoint and Lakehouse, with the schema **`dbo` replaced by `gold`**. It fails if a template has no `dbo` reference left to replace. | `out/models/<key>/definition.json` (deployable), `model.bim`, `relationships.txt`, `lakehouse_tables.txt`, `out/models/gold_tables.json`, `SUMMARY.json` |
| `npm run notebooks` | Builds this repo's notebooks from `notebook-src/*.py` into the stage folders, plus copies bound to your Lakehouse in `out/notebooks/` | `0x-*/*.ipynb`, `out/notebooks/` |

A setting missing from `config.json` becomes a visible `<placeholder>` in the notebook and a warning, never a silent default.

`out/SOURCE.lock.json` records the commit, the modules, the permissions and a SHA-256 of every notebook, so you can always tell what is deployed.

## 3.2 Import the notebooks

In the workspace, choose **Import > Notebook > From this computer** and select **every `.ipynb` in `out/notebooks/`**. Keep the file names: the orchestrator calls notebooks by display name, and `%run lake_ops` needs that exact name.

| Group | Notebooks |
|---|---|
| This repo | `lake_ops`, `01_Validate_Credentials`, `02_Init_Lakehouse`, `05_Promote_Medallion`, `06_Deploy_Models`, `07_Orchestrator` |
| Core | `Copilot_Audit_Log_Direct_Ingester`, `Copilot_Licensed_Users_Direct_Ingester`, `Copilot_Audit_Log_Processor`, `AnalyticsHub_Upload_Router`, `AnalyticsHub_Refresh_Model`, `AnalyticsHub_Data_Check`, `AnalyticsHub_Load_Status` (not used here: it reads pipeline runs; `ops.run_log` replaces it) |
| `orgData` | `Copilot_Org_Data_Direct_Ingester` (plus `Copilot_Org_Data_Workday_Lander` when Workday is a CSV source) |
| `m365Activity` | `Copilot_M365_Activity_Ingester` |
| `agent365` | `Copilot_Agent365_Registry_Ingester`, `Copilot_Agent365_Lander` |
| `productFeedback` | `Copilot_ProductFeedback_Ingester` |
| `consumption` | `Consumption_Ingest_Azure_AI`, `Consumption_Ingest_Studio`, `Consumption_Ingest_Viva` |
| `agentEvaluator` | `AgentEval_Transcript_Parser` |

The list depends on your modules. `out/notebooks/MANIFEST.json` is the exact list.

If a notebook with that name already exists, Fabric adds a suffix instead of overwriting it. Delete the old one first, or open it and use *Edit > Replace from file*.

**Check the Lakehouse binding.** Open any notebook. The explorer should show `UniversalLake_LH` pinned as default. If it doesn't (because `config.json` had no Lakehouse ID when you built), add it and pin it in each notebook.

## 3.3 Upload the model files

In the Lakehouse, go to **Files > universal_lake** (created by `02_Init_Lakehouse`) and choose **Upload > Upload folder**. Pick `out/models`. You should end up with:

```
Files/universal_lake/models/gold_tables.json
Files/universal_lake/models/universal/definition.json
Files/universal_lake/models/consumption/definition.json
Files/universal_lake/models/agentEvaluator/definition.json
```

The other files in those folders (`model.bim`, `relationships.txt` and so on) are there for you to read or diff. The notebooks ignore them.

## 3.4 Run the two check notebooks

1. `02_Init_Lakehouse` ([stage 2](../02-lakehouse/README.md#23-initialise-it-02_init_lakehouse)), if you haven't run it yet.
2. `01_Validate_Credentials` ([stage 1](../01-app-registration/README.md#check-it-01_validate_credentials)). **All checks must pass before you ingest.**

## Re-building later

* **Config change** (new module, new data source, new subscription): `npm run all`, then re-import the notebooks `sync` reports as changed or new.
* **New source version**: see [Updating the source code](../README.md#updating-the-source-code).
* **Only the models changed**: `npm run models`, re-upload `out/models`, then run `06_Deploy_Models` (stage 6).

Next: [Stage 4: Ingest](../04-ingest/README.md)
