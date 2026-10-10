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
2. **First time only:** the refresh stops with *Sign in once* and a link. Open the link (the model's settings page), expand **Data source credentials > Edit credentials**, pick **OAuth2** and **Sign in**. Do this for each model it names, then run the notebook again with `DEPLOY = False`.
3. It ends by counting rows per table. A table with `0` rows means its ingester loaded nothing.

The models read the gold tables with **your** sign-in, so no admin setting or app role is needed. If you leave, a colleague opens each model > **Settings > Take over** and signs in the same way. The orchestrator's refresh steps are skipped until this notebook has run once.

| Parameter | Default | Use |
|---|---|---|
| `MODELS` | all three | Only some, e.g. `'universal'` |
| `CONNECTION_MODE` | `signin` | `signin`: your sign-in (above). `spn`: reads as the app, for unattended production (below). `existing`: a connection you made, in `CONNECTION_ID`. |
| `DEPLOY` | `True` | `False`: only reconnect, refresh and count |
| `REFRESH` | `True` | `False`: deploy only |
| `REFRESH_TIMEOUT_MIN` | 60 | Raise for a big first refresh |

<details>
<summary>Run the models as the app (<code>spn</code>)</summary>

Use this when the models shouldn't depend on one person. It needs:

* Fabric > **Settings > Admin portal > Tenant settings > Developer settings > *Service principals can call Fabric public APIs*** on for the app.
* The app as **Viewer** on the workspace: **Manage access > Add people or groups**.

Then run with `CONNECTION_MODE = 'spn'`. After rotating the client secret, rerun with `DEPLOY = False`.

</details>

**Run it again only when** you rotated the secret with `spn` (`DEPLOY = False`), or after `npm run deploy` sent changed model files (a newer repo version, or a new `lakehouse.sqlEndpoint`). Daily refreshes are done by the orchestrator.

The models are normal Fabric semantic models: build Power BI reports on them, use them with Copilot in Power BI or a data agent, or query them with DAX. To review one before deploying, open `out/models/<model>/relationships.txt` or `model.bim` on your PC.

Next: [Step 7: Orchestrate](../07-orchestrate/README.md)
