# Step 6: Check the data and the models

Your step 5 run already cleaned the data and sorted it into report-ready tables. It also created, connected and refreshed the semantic models. Here you check both.

## 6.1 Check the data

Two steps at the end of the step 5 run did this:

| Step | Notebook | Does |
|---|---|---|
| `processor` | `Copilot_Audit_Log_Processor` | Classifies every audit event (app, agent, agent type), joins licences and agents, writes `dbo.copilot_interactions_curated` |
| `promote` | `Lake_Promote_Medallion` | Copies every `dbo` table into **one** of `bronze`, `silver`, `gold` |

At the end, `promote` prints **gold coverage per model**, e.g. `consumption 12/14 missing: viva_…`. Missing tables are usually a source you didn't turn on or that has no data yet; the model still deploys, those visuals stay empty.

To see where every table went, run this in the Lakehouse's SQL analytics endpoint:

```sql
SELECT table_name, layer, status, rows, promoted_at FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY table_name ORDER BY promoted_at DESC) rn FROM ops.table_layers
) WHERE rn = 1 ORDER BY layer, table_name;
```

| Layer | Rule |
|---|---|
| **gold** | Every table a semantic model reads (listed in `Files/universal_lake/models/gold_tables.json`, which deploy uploaded) |
| **bronze** | Raw extracts and logs, e.g. `copilot_interactions_parsed`, `*_raw`, `*_staging*`, upload and load logs |
| **silver** | Everything else, e.g. `agents_365_history` |

Promote messages and its parameters are in [TROUBLESHOOTING.md](../TROUBLESHOOTING.md#promote-messages).

## 6.2 The semantic models

The same step 5 run also created the models, connected them and refreshed them:

| Step | Does |
|---|---|
| `models` | Runs `Lake_Deploy_Models`: creates any model that doesn't exist yet and connects every model to the gold tables **as the app** |
| `refresh_*` | Refreshes each model |

| Model | Display name | Tables | Relationships | Module |
|---|---|---|---|---|
| `universal` | Universal Lake Model | 20 | 10 | copilotInteractions |
| `consumption` | Universal Lake Consumption Model | 37 | 16 | consumption |
| `agentEvaluator` | Universal Lake Agent Evaluator Model | 43 | 23 | agentEvaluator |

Find them in the workspace (type *Semantic model*). Models for modules you didn't pick aren't created.

**Nobody has to sign in.** The models read the Lakehouse with the app's secret, so refreshes run unattended. This needs one admin setting, which `Lake_Setup` checks in step 4 (*App can call Fabric*): Fabric > **Settings > Admin portal > Tenant settings > Developer settings > *Service principals can call Fabric public APIs*** on for the app (or a group it is in). It is on by default in tenants created since mid-2025, so usually there's nothing to do.

<details>
<summary>If the setting is off: sign in once</summary>

The `models` step then falls back to your own sign-in by itself and prints a link per model; the refresh steps fail with *credentials* and print the same link. Either ask your Fabric admin to turn the setting on (the next run connects as the app), or sign in once. Open the printed link (any one model) > **Gateway and cloud connections** > **Maps to** > **Create a connection** > **OAuth 2.0** > **Edit credentials** (a sign-in window opens) > **Create** > **Apply**. You do this once for the workspace: every run (and every redeploy) finds that sign-in connection and attaches all the models to it, so new or recreated models need nothing. Refreshes keep working while your account has access to the workspace. If you leave, a colleague creates their own connection the same way, and deletes yours under Settings > **Manage connections and gateways**. Then rerun the orchestrator with `STEPS='refresh_universal'` (plus the other `refresh_*` steps you use).

</details>

### Run `Lake_Deploy_Models` yourself only to

* **Update** the models after `npm run deploy` sent changed model files (a newer repo version, or a new `lakehouse.sqlEndpoint`): **Run all**. The orchestrator never changes an existing model's definition.
* **Reconnect** after rotating the client secret: `DEPLOY = False`, `REFRESH = False`. (The `models` step also does this on every run.)

| Parameter | Default | Use |
|---|---|---|
| `MODELS` | all three | Only some, e.g. `'universal'` |
| `DEPLOY` | `True` | `True`: create or update. `'missing'`: create only absent models (what the orchestrator uses). `False`: only connect |
| `REFRESH` | `True` | `False`: skip the refresh and row counts |
| `CONNECTION_MODE` | `auto` | `auto`: the app, falling back to your sign-in if that fails or there's no secret. `spn`, `signin`, or `existing` (a connection you made, in `CONNECTION_ID`) |
| `REFRESH_TIMEOUT_MIN` | 60 | Raise for a big first refresh |

It ends by counting rows per table; `0` rows means that table's ingester loaded nothing.

The models are normal Fabric semantic models: build Power BI reports on them, use them with Copilot in Power BI or a data agent, or query them with DAX. To review one before deploying, open `out/models/<model>/relationships.txt` or `model.bim` on your PC.

Next: [Step 7: Orchestrate](../07-orchestrate/README.md)
