# Step 6: Process and promote

Two steps turn the raw `dbo` tables into the medallion layers that the semantic models read.

| # | Step | Notebook | Reads | Writes |
|---|---|---|---|---|
| 4 | `processor` | `Copilot_Audit_Log_Processor` (installer, unchanged) | `dbo.copilot_interactions_parsed`, `dbo.copilot_licensed_users`, `dbo.agents_365`, `dbo.agent_type_overrides` | `dbo.copilot_interactions_curated` |
| 13 | `promote` | `Lake_Promote_Medallion` (this repo) | every `dbo` table | `bronze.*`, `silver.*`, `gold.*`, `ops.table_layers` |

The processor runs right after ingest, as step 4. Promote runs after **all** ingesters, so it captures their latest output.

## The processor

It classifies every audit event (app, agent, agent type), joins licences and agents, drops agent identities, and writes the curated fact table that Power BI reads.

| `WRITE_MODE` | When the orchestrator uses it | What happens |
|---|---|---|
| `overwrite` | `first_load`, `backfill` | Rebuilds `copilot_interactions_curated` from the whole parsed table. Use it after a backfill, or after you change `agent_type_overrides`. |
| `merge` | `incremental` | Upserts on `Id`, which is quick for the daily run. |

To run it alone: `Lake_Orchestrator` with `STEPS = 'processor'` and `RUN_MODE = 'backfill'` (for overwrite) or `'incremental'` (for merge). It needs `audit` and `licensed_users`. If they are not part of the run, the orchestrator notes that and uses the data already in `dbo`.

**Reclassifying agents.** Add rows to `dbo.agent_type_overrides`, then run the processor with overwrite. No audit re-fetch is needed.

## Promote to bronze, silver and gold

Every `dbo` table goes to **exactly one** layer:

| Layer | Rule | Examples |
|---|---|---|
| **gold** | Every table a semantic model reads, from `Files/universal_lake/models/gold_tables.json` (made by `npm run models`) | `copilot_interactions_curated`, `copilot_licensed_users`, `copilot_org_data`, `agents_365`, `user_feedback`, `m365_activity_daily`, `azure_*`, `studio_*`, `viva_*`, `agent_*` |
| **bronze** | Raw extracts and logs: `copilot_interactions_parsed`, `*_raw`, `*_staging*`, `staging_*`, `*_detail_cache`, `analytics_hub_upload_log`, `load_log`, `attempt_errors` | `copilot_interactions_parsed` |
| **silver** | Everything else | `agents_365_history`, `studio_agent_daily` |

Each copy **overwrites** the target with the current `dbo` table. A promote is always safe to rerun and always leaves the layer equal to `dbo`.

### Parameters

| Parameter | Default | Use |
|---|---|---|
| `TABLES` | blank (all) | Promote only some tables, e.g. `'copilot_org_data,user_feedback'` |
| `SKIP_UNCHANGED` | `True` | Skips a table whose `dbo` Delta version hasn't changed since its last promote. Set it to `False` to force a full copy. |
| `DRY_RUN` | `False` | Prints which layer each table would go to, and does nothing |
| `LAYER_OVERRIDES_JSON` | `{}` | Moves a table to another layer, e.g. `{"agents_365_history": "gold"}` |
| `DROP_STALE` | `False` | After a table changes layer, drops its old copy (otherwise you only get a warning) |
| `REQUIRED_GOLD` | `copilot_interactions_curated,copilot_licensed_users` | Fails the promote if these are missing from gold |
| `GOLD_TABLES_FILE` | `/lakehouse/default/Files/universal_lake/models/gold_tables.json` | The model table list; see [step 7](../07-semantic-model/README.md) |

At the end it prints the **gold coverage of each model**, e.g. `consumption 12/14 missing: viva_…`. A table can be missing because its module isn't installed or its source has no data yet. The model still deploys, but those visuals stay empty.

### Checking the layers

```sql
-- The latest result for each table
SELECT table_name, layer, status, rows, source_version, promoted_at, note FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY table_name ORDER BY promoted_at DESC) rn FROM ops.table_layers
) WHERE rn = 1 ORDER BY layer, table_name;

-- dbo row count against the gold row count for one table
SELECT (SELECT count(*) FROM dbo.copilot_interactions_curated) AS dbo_rows,
       (SELECT count(*) FROM gold.copilot_interactions_curated) AS gold_rows;
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `gold_tables.json not found` | Upload `out/models` into `Files/universal_lake/` ([step 4](../04-import/README.md)) |
| `Required but not in gold: copilot_interactions_curated` | The processor hasn't run successfully yet. Run `audit`, `licensed_users` and `processor` first. |
| `WARNING: silver.x also exists` | The layer rule changed. Rerun with `DROP_STALE = True` once you've checked it. |
| A table shows `unchanged` but you expect new rows | Its source didn't write. Check that ingester's `ops.run_log` row, or force the copy with `SKIP_UNCHANGED = False`. |

Next: [Step 7: Semantic models](../07-semantic-model/README.md)
