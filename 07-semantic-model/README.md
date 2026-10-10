# Step 7: Semantic models

Your [step 5](../05-ingest/README.md) run already created the semantic models, connected them and refreshed them: its `models` step runs `Lake_Deploy_Models` for you, using the files you uploaded in [step 4.5](../04-import/README.md#45-upload-the-model-definitions). Nobody signs in on the models. This page is for checking them and for the rare times you run `Lake_Deploy_Models` yourself. The tables and relationships come from the definitions in [models/](../models).

| Model | Display name | Tables | Relationships | Module |
|---|---|---|---|---|
| `universal` | Universal Lake Model | 20 | 10 | copilotInteractions |
| `consumption` | Universal Lake Consumption Model | 37 | 16 | consumption |
| `agentEvaluator` | Universal Lake Agent Evaluator Model | 43 | 23 | agentEvaluator |

Models for modules you didn't pick are skipped. If models with these names already exist in the workspace, they are **updated**, so use a different workspace or rename the old ones first.

To review a model before deploying, open `out/models/<model>/relationships.txt` or `model.bim` on your PC.

## Check them

In the step 5 run output, `models` and the `refresh_*` steps should say `succeeded`. The models appear in the workspace under the display names above.

**How it stays unattended.** The `models` step creates a cloud connection signed in as the app (with its secret) and binds each model to it, so refreshes need nobody signed in. It runs on every orchestrator run, so a rotated secret is picked up automatically. It needs one admin setting: Fabric > **Settings > Admin portal > Tenant settings > Developer settings > *Service principals can call Fabric public APIs*** on for the app (on by default in tenants created since mid-2025). It is on by default, so usually there's nothing to do; `Lake_Validate_Credentials` ([step 2](../02-permissions/README.md)) warns you if it is off.

If the setting is off, the `models` step falls back to your own sign-in by itself and prints a link per model; the refresh steps fail with *credentials* and print the same link. Either ask your Fabric admin to turn it on (the next run connects as the app), or sign in once per model (below).

## Parameters

| Parameter | Default | Use |
|---|---|---|
| `MODELS` | all three | Only some, e.g. `'universal'` |
| `CONNECTION_MODE` | `auto` | `auto`: the app, falling back to your sign-in if that fails or there's no secret. `spn`: always the app. `signin`: your sign-in (below). `existing`: a connection you made yourself, in `CONNECTION_ID`. |
| `DEPLOY` | `True` | `False`: don't change the definition; only reconnect, refresh and count. `'missing'`: create missing models only (what the orchestrator uses) |
| `REFRESH` | `True` | `False`: deploy only |
| `REFRESH_TIMEOUT_MIN` | 60 | Raise for a big first refresh |

<details><summary>If the setting is off: sign in once per model</summary>

Open each printed link (the model's settings page). There: **Gateway and cloud connections > Maps to > Create a connection**, pick **OAuth 2.0 > Edit credentials** (a sign-in window opens), then **Create > Apply**. Do it once per model. If you leave, a colleague opens each model > **Settings > Take over** and signs in again. Then rerun the orchestrator with `STEPS='refresh_universal'` (plus the other `refresh_*` steps you use).

</details>

## Run `Lake_Deploy_Models` yourself only to

* update the models after you changed the source version or `lakehouse.sqlEndpoint`: `npm run models`, re-upload `out/models`, then **Run all** (the orchestrator only creates missing models, it doesn't update them).

Daily refreshes and reconnecting after a secret rotation are done by the orchestrator.

## Use the models

They are normal Fabric semantic models: build Power BI reports on them, use them with Copilot in Power BI or a data agent, or query them with DAX.

```sql
SELECT step, status, error FROM ops.run_log
WHERE step LIKE 'deploy:%' AND event = 'end' ORDER BY ended_at DESC LIMIT 10;
```

Next: [Step 8: Orchestrate](../08-orchestrate/README.md)
