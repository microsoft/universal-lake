# Step 6: Process and promote

**Nothing to run here**: these two steps already ran at the end of your step 5 run. This page explains what they did and how to check it.

| Step | Notebook | Does |
|---|---|---|
| `processor` | `Copilot_Audit_Log_Processor` | Classifies every audit event (app, agent, agent type), joins licences and agents, writes `dbo.copilot_interactions_curated` |
| `promote` | `Lake_Promote_Medallion` | Copies every `dbo` table into **one** of `bronze`, `silver`, `gold` |

The orchestrator runs `promote` after all ingesters, so it picks up their latest data. To run one of them again on its own: `Lake_Orchestrator` with `STEPS = 'promote'` (or `'processor,promote'`).

## The processor

* `first_load` and `backfill` **rebuild** the curated table from all audit data.
* `incremental` (daily) **merges** only new rows.
* To reclassify agents: add rows to `dbo.agent_type_overrides`, then run the processor with `RUN_MODE = 'backfill'`. No re-fetch needed.

## Promote: which table goes where

| Layer | Rule |
|---|---|
| **gold** | Every table a semantic model reads (listed in `Files/universal_lake/models/gold_tables.json`, uploaded in step 4.5) |
| **bronze** | Raw extracts and logs, e.g. `copilot_interactions_parsed`, `*_raw`, `*_staging*`, upload and load logs |
| **silver** | Everything else, e.g. `agents_365_history` |

Each copy overwrites the target, so promote is always safe to re-run. Unchanged tables are skipped.

At the end it prints **gold coverage per model**, e.g. `consumption 12/14 missing: viva_…`. Missing tables are usually a source you didn't turn on or that has no data yet; the model still deploys, those visuals stay empty.

Useful parameters (open `Lake_Promote_Medallion` to run it alone):

| Parameter | Use |
|---|---|
| `TABLES` | Only these tables, e.g. `'copilot_org_data,user_feedback'` |
| `SKIP_UNCHANGED = False` | Force a full copy |
| `DRY_RUN = True` | Show the layer for each table, change nothing |
| `LAYER_OVERRIDES_JSON` | Move a table, e.g. `{"agents_365_history": "gold"}` |
| `DROP_STALE = True` | Drop the old copy after a table changes layer |

## Check it

```sql
SELECT table_name, layer, status, rows, promoted_at FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY table_name ORDER BY promoted_at DESC) rn FROM ops.table_layers
) WHERE rn = 1 ORDER BY layer, table_name;
```

| Message | Fix |
|---|---|
| `gold_tables.json not found` | Upload `out/models` ([step 4.5](../04-import/README.md#45-upload-the-model-definitions)) |
| `Required but not in gold: copilot_interactions_curated` | Run `audit`, `licensed_users` and `processor` first |
| `WARNING: silver.x also exists` | A table changed layer. Re-run with `DROP_STALE = True` |
| Table `unchanged` but you expected new rows | Its ingester didn't write; check `ops.run_log` |

Next: [Step 7: Semantic models](../07-semantic-model/README.md)
