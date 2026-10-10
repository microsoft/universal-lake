# Step 6: Check the data and deploy the models

Your step 5 run already cleaned the data and sorted it into report-ready tables. Here you check that, then run one notebook to create the semantic models.

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

## 6.2 Deploy the semantic models

`Lake_Deploy_Models` creates the models from the uploaded definitions, connects them to the gold tables and refreshes them.

| Model | Display name | Tables | Relationships | Module |
|---|---|---|---|---|
| `universal` | Universal Lake Model | 20 | 10 | copilotInteractions |
| `consumption` | Universal Lake Consumption Model | 37 | 16 | consumption |
| `agentEvaluator` | Universal Lake Agent Evaluator Model | 43 | 23 | agentEvaluator |

Models for modules you didn't pick are skipped. Models with these names already in the workspace are **updated**.

1. Open `Lake_Deploy_Models` > **Run all**.
2. It ends by counting rows per table. A table with `0` rows means its ingester loaded nothing.

**Unattended by default.** When the app's secret is available (Key Vault, or `CLIENT_SECRET` which `npm run deploy` fills in when you have no vault), the notebook adds the app to the workspace as **Viewer**, creates a cloud connection signed in as the app and binds each model to it. The orchestrator's refreshes then run with nobody signed in. One admin setting is needed: Fabric > **Settings > Admin portal > Tenant settings > Developer settings > *Service principals can call Fabric public APIs*** on for the app (or a group it is in). If it is off, the notebook says so.

| Parameter | Default | Use |
|---|---|---|
| `MODELS` | all three | Only some, e.g. `'universal'` |
| `CONNECTION_MODE` | `auto` | `auto`: the app when its secret is available, else your sign-in. `spn`: always the app. `signin`: your sign-in (below). `existing`: a connection you made, in `CONNECTION_ID`. |
| `DEPLOY` | `True` | `False`: only reconnect, refresh and count |
| `REFRESH` | `True` | `False`: deploy only |
| `REFRESH_TIMEOUT_MIN` | 60 | Raise for a big first refresh |

<details>
<summary>Use your own sign-in instead (<code>signin</code>)</summary>

Use this only if the admin setting above can't be turned on. The first refresh stops with *Sign in once* and a link. Open it (the model's settings page), expand **Gateway and cloud connections** (or **Data source credentials**) **> Edit credentials**, pick **OAuth2** and **Sign in**, for each model it names. Then run the notebook again with `DEPLOY = False`. Refreshes keep working while you have access; if you leave, a colleague opens each model > **Settings > Take over** and signs in again.

</details>

**Run it again only when** you rotated the client secret (`DEPLOY = False`), or after `npm run deploy` sent changed model files (a newer repo version, or a new `lakehouse.sqlEndpoint`). Daily refreshes are done by the orchestrator.

The models are normal Fabric semantic models: build Power BI reports on them, use them with Copilot in Power BI or a data agent, or query them with DAX. To review one before deploying, open `out/models/<model>/relationships.txt` or `model.bim` on your PC.

Next: [Step 7: Orchestrate](../07-orchestrate/README.md)
