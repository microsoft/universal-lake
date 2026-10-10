# Step 7: Semantic models

`Lake_Deploy_Models` creates the semantic models from the files you uploaded in [step 4.5](../04-import/README.md#45-upload-the-model-definitions), connects them to the gold tables and refreshes them. The tables and relationships come from the definitions in [models/](../models).

| Model | Display name | Tables | Relationships | Module |
|---|---|---|---|---|
| `universal` | Universal Lake Model | 20 | 10 | copilotInteractions |
| `consumption` | Universal Lake Consumption Model | 37 | 16 | consumption |
| `agentEvaluator` | Universal Lake Agent Evaluator Model | 43 | 23 | agentEvaluator |

Models for modules you didn't pick are skipped. If models with these names already exist in the workspace, they are **updated**, so use a different workspace or rename the old ones first.

To review a model before deploying, open `out/models/<model>/relationships.txt` or `model.bim` on your PC.

## Run it

1. Make sure your [step 5](../05-ingest/README.md) run succeeded, so gold has data. Otherwise the refresh fails with *table … not found*.
2. Open `Lake_Deploy_Models` > **Run all**.

For each model it: finds or creates it, replaces its definition, connects it, refreshes it, and counts rows per table. A table with `0` rows means its ingester loaded nothing.

**Unattended by default.** When the app's secret is available (Key Vault, or `CLIENT_SECRET` which the build fills in when you have no vault), the notebook adds the app to the workspace as **Viewer**, creates a cloud connection signed in as the app and binds each model to it. The orchestrator's refreshes then run with nobody signed in. It needs one admin setting: Fabric > **Settings > Admin portal > Tenant settings > Developer settings > *Service principals can call Fabric public APIs*** on for the app (on by default in tenants created since mid-2025). If it is off, the notebook says so.

The model IDs are saved in `ops.config`. **The orchestrator's refresh steps are skipped until this notebook has run once.**

## Parameters

| Parameter | Default | Use |
|---|---|---|
| `MODELS` | all three | Only some, e.g. `'universal'` |
| `CONNECTION_MODE` | `auto` | `auto`: the app when its secret is available, else your sign-in. `spn`: always the app. `signin`: your sign-in (below). `existing`: a connection you made yourself, in `CONNECTION_ID`. |
| `DEPLOY` | `True` | `False`: don't change the definition; only reconnect, refresh and count |
| `REFRESH` | `True` | `False`: deploy only |
| `REFRESH_TIMEOUT_MIN` | 60 | Raise for a big first refresh |

**Optional: use your own sign-in (`signin`).** Only if the admin setting can't be turned on. The first refresh stops with *Sign in once* and a link. Open it (the model's settings page), expand **Gateway and cloud connections** (or **Data source credentials**) **> Edit credentials**, pick **OAuth2** and **Sign in**, for each model it names. Then run the notebook again with `DEPLOY = False`. If you leave, a colleague opens each model > **Settings > Take over** and signs in again.

## When to run it again

Daily refreshes are done by the orchestrator, not this notebook. Run `Lake_Deploy_Models` again only when:

* you rotated the client secret: `DEPLOY = False`;
* you changed the source version or `lakehouse.sqlEndpoint`: `npm run models`, re-upload `out/models`, then run it.

## Use the models

They are normal Fabric semantic models: build Power BI reports on them, use them with Copilot in Power BI or a data agent, or query them with DAX.

```sql
SELECT step, status, error FROM ops.run_log
WHERE step LIKE 'deploy:%' AND event = 'end' ORDER BY ended_at DESC LIMIT 10;
```

Next: [Step 8: Orchestrate](../08-orchestrate/README.md)
