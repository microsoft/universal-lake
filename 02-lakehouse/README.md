# Stage 2: Workspace and Lakehouse

The installer creates a workspace and a Lakehouse called `UniversalLake_LH`. Here you create them yourself, and a notebook checks them and lays out the medallion schemas.

## 2.1 Workspace

Use an existing workspace where you are **Admin** or **Member**, or create one. Either way it must be on a **Fabric capacity** (*Workspace settings > License info*). Copy its ID from the URL (`/groups/<workspace-id>/`) into `config.json` > `workspace`.

## 2.2 Lakehouse: must be schema-enabled

**New > Lakehouse**, name it (`UniversalLake_LH` matches the installer), and **tick _Lakehouse schemas_**.

> You can't turn schemas on later. If you create the Lakehouse without them, delete it and create a new one. `02_Init_Lakehouse` stops with a clear error if it finds a Lakehouse without the `dbo` schema.

Copy these into `config.json` > `lakehouse`:

| Value | Where |
|---|---|
| `id` | The Lakehouse URL: `/lakehouses/<lakehouse-id>` |
| `name` | Its display name |
| `sqlEndpoint` | Open the **SQL analytics endpoint** item, then *Settings > SQL connection string*. Use only the host, `xxxx.datawarehouse.fabric.microsoft.com`. |

`npm run models` builds the semantic models against this endpoint and Lakehouse, and `npm run notebooks` binds the notebooks to this Lakehouse, so fill these in **before** [stage 3](../03-build-and-import/README.md).

## 2.3 Initialise it: `02_Init_Lakehouse`

Import two notebooks into the workspace (*Import > Notebook > From this computer*). Their names must stay exactly as shown, because `%run lake_ops` finds the helper by name:

* `07-orchestrate/lake_ops.ipynb`, the shared helpers (run log, ledger and config)
* `02-lakehouse/02_Init_Lakehouse.ipynb`

You can also run `npm run all` first and import from `out/notebooks/` instead. Those copies already have the Lakehouse attached. Otherwise, open `02_Init_Lakehouse`, choose **Add Lakehouse** in the explorer and pin `UniversalLake_LH` as the **default**.

Fill in the parameters cell from `config.json`:

| Parameter | From | Notes |
|---|---|---|
| `TENANT_ID`, `CLIENT_ID`, `KEY_VAULT_URI`, `SECRET_NAME` | `tenantId`, `appId`, `keyVault.*` | Saved to `ops.config`, so the orchestrator and other notebooks read them from there |
| `SQL_ENDPOINT` | `lakehouse.sqlEndpoint` | Used by `06_Deploy_Models` for the connection |
| `SCALE` | `scale` | `standard`, or `large` for more than about 20k Copilot users or a very busy audit log. Large uses 2-hour audit chunks and longer time budgets. |
| `BACKFILL_DAYS` | `backfillDays` | How much audit history the **first load** fetches (1-180). You can override it per run. |
| `MODULES` | the modules you picked | The orchestrator skips steps for modules not listed here |
| `MODEL_ID_*` | leave blank | `06_Deploy_Models` fills these in |

Choose **Run all**. It is safe to re-run: it never drops anything, and blank parameters never wipe a saved setting.

### What you get

| Schema | Holds | Written by |
|---|---|---|
| `dbo` | The ingesters' working tables, exactly as the installer writes them | Installer notebooks, unchanged |
| `bronze` | Raw extracts: parsed audit records, raw payloads, upload and load logs | `05_Promote_Medallion` |
| `silver` | Cleaned intermediate tables and history that the models don't read | `05_Promote_Medallion` |
| `gold` | Exactly the tables the semantic models read | `05_Promote_Medallion` |
| `ops` | `config`, `run_log`, `backfill_ledger`, `table_layers` | `02`, `05`, `06`, `07` |

and these `Files/` folders:

| Folder | Put here |
|---|---|
| `Files/analytics_hub_uploads` | Any CSV export. The Upload Router recognises it and moves it to the right folder. |
| `Files/agent365` | `agents.csv` from the Microsoft 365 admin center (CSV mode, or the API fallback) |
| `Files/product_feedback` | Product feedback exports |
| `Files/landing/studio`, `Files/landing/viva` | Copilot Studio and Cowork credit exports |
| `Files/org_workday` | Workday org extract (Workday CSV source only) |
| `Files/universal_lake/models` | The whole `out/models` folder from `npm run models` (stage 3): `gold_tables.json` and `<key>/definition.json` |

Check it:

```sql
SELECT * FROM ops.config ORDER BY key;
```

The notebook ends by listing any required setting that is still blank.

Next: [Stage 3: Build and import](../03-build-and-import/README.md)
