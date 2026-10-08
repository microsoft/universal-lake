# Step 7: Semantic models

`Lake_Deploy_Models` creates the semantic models from the files you uploaded in [step 4.5](../04-import/README.md#45-upload-the-model-definitions), connects them to the gold tables and refreshes them. The models and relationships come from the installer's own model code, so they match what the installer deploys.

| Model | Display name | Tables | Relationships | Module |
|---|---|---|---|---|
| `universal` | Universal Lake Model | 20 | 10 | copilotInteractions |
| `consumption` | Analytics Hub Consumption Model | 37 | 16 | consumption |
| `agentEvaluator` | Analytics Hub Agent Evaluator Model | 43 | 23 | agentEvaluator |

Models for modules you didn't pick are skipped. If models with these names already exist in the workspace (for example from the installer), they are **updated**, so use a different workspace or rename the old ones first.

To review a model before deploying, open `out/models/<model>/relationships.txt` or `model.bim` on your PC.

## Run it

1. Make sure [step 6](../06-process/README.md) has run, so gold has data. Otherwise the refresh fails with *table … not found*.
2. Open `Lake_Deploy_Models` > **Run all**.

For each model it: finds or creates it, replaces its definition, connects it to the Lakehouse SQL endpoint as the app, refreshes it, and counts rows per table. A table with `0` rows means its ingester loaded nothing.

The model IDs are saved in `ops.config`. **The orchestrator's refresh steps are skipped until this notebook has run once.**

## Parameters

| Parameter | Default | Use |
|---|---|---|
| `MODELS` | all three | Only some, e.g. `'universal'` |
| `CONNECTION_MODE` | `spn` | `spn`: connects as the app, using the client secret (Key Vault, or the `config.json` bypass). `existing`: use `CONNECTION_ID`. `skip`: bind it yourself in the model's **Settings > Gateway and cloud connections**. |
| `DEPLOY` | `True` | `False`: don't change the definition; only reconnect, refresh and count |
| `REFRESH` | `True` | `False`: deploy only |
| `REFRESH_TIMEOUT_MIN` | 60 | Raise for a big first refresh |

`spn` needs the app to be **Viewer** on the workspace and *Service principals can use Fabric APIs* on ([step 2](../02-permissions/README.md#23-give-the-app-access)).

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
