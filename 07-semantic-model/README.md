# Step 7: Semantic models

The models and their relationships are built by **the installer's own model code**, pointed at the `gold` schema. Nothing is hand-written, so they match what the installer deploys.

| Model key | Display name | Tables | Relationships | Lakehouse (gold) tables | Module |
|---|---|---|---|---|---|
| `universal` | Universal Lake Model | 20 | 10 | 6 | core |
| `consumption` | Analytics Hub Consumption Model | 37 | 16 | 14 | consumption |
| `agentEvaluator` | Analytics Hub Agent Evaluator Model | 43 | 23 | 10 | agentEvaluator |

These are the installer's display names. If the installer already deployed models into the same workspace, use a different workspace, or rename the existing ones first. Otherwise 06 finds them by name and **updates** them.

Other tables (dates, parameters, calculated tables) live in the model itself and need no Lakehouse table.

## 1. Build on your PC

```powershell
npm run models        # or: npm run all
```

This writes to `out/models/`:

| File | What it is |
|---|---|
| `<key>/definition.json` | The Fabric item definition that `Lake_Deploy_Models` uploads |
| `<key>/model.bim` | The same model as readable TMSL, to review or diff |
| `<key>/relationships.txt` | Every relationship: `from[col] -> to[col]`, marked `(inactive)` where it applies |
| `<key>/lakehouse_tables.txt` | The gold tables this model reads |
| `gold_tables.json` | All of the above per model; `Lake_Promote_Medallion` uses it to decide what is gold |
| `SUMMARY.json` | Server, database, schema, modules and per-model counts. The source commit is in `out/SOURCE.lock.json`. |

The server and database in the models come from `lakehouse.sqlEndpoint` and `lakehouse.name` in `config.json`, and the schema is `gold`. If you change either, rebuild. If `sqlEndpoint` is blank, the build warns you and the models carry a placeholder server.

## 2. Upload

Upload the whole `out/models` folder into **`Files/universal_lake/`**, so you have `Files/universal_lake/models/<key>/definition.json` and `Files/universal_lake/models/gold_tables.json`. To do that: open the Lakehouse, click `…` next to `Files/universal_lake`, then **Upload > Upload folder**. Overwrite the files when you rebuild.

## 3. Promote first

Gold must hold the tables before the refresh, so run [step 6](../06-process/README.md) first. Otherwise the refresh fails with *"table … not found"*.

## 4. Run `Lake_Deploy_Models`

For each model in `MODELS`:

| Step | What happens | If it fails |
|---|---|---|
| Find | Looks the model up by `ops.config` `model_id.<key>`, then by display name | n/a |
| Create or update | Creates the model, or replaces its definition. An update leaves it empty until the refresh. | Fix the error and rerun. Nothing else has changed. |
| Connect | Binds the model to the Lakehouse SQL endpoint (see below) | Bind it by hand: model **Settings > Gateway and cloud connections** |
| Prints the relationships | Lists every relationship it deployed | n/a |
| Refresh | Full refresh, then waits up to `REFRESH_TIMEOUT_MIN` | The service's error is in the output and in `ops.run_log` |
| Probe | Counts the rows in each imported table through DAX | `0` rows means that gold table is empty, so check its ingester |

The model ID is saved to `ops.config` as `model_id.<key>`. **The orchestrator's refresh steps are skipped until that ID exists.**

### Parameters

| Parameter | Default | Use |
|---|---|---|
| `MODELS` | `universal,consumption,agentEvaluator` | Models that have no uploaded definition are skipped |
| `CONNECTION_MODE` | `spn` | `spn`: creates or updates a cloud connection *"Universal Lake SQL &lt;ws&gt;"* that signs in as the app, using the Key Vault secret. `existing`: uses `CONNECTION_ID`. `skip`: you bind it yourself. |
| `CONNECTION_ID`, `CONNECTION_NAME` | blank | For `existing`, or to rename the connection |
| `DEPLOY` | `True` | `False`: no definition change. It only connects, refreshes and probes (use after a manual bind). |
| `REFRESH` | `True` | `False`: deploy only |
| `REFRESH_TIMEOUT_MIN` | 60 | Raise this for a large first refresh |

`spn` needs the app to be a Viewer of the workspace ([step 2.4](../02-permissions/README.md#follow-ups-for-both-options)) and the tenant setting *"Service principals can use Fabric APIs"*. **After you rotate the secret, rerun this notebook with `DEPLOY = False`** so the connection gets the new one.

## Later refreshes

There is no need to rerun 06 for a daily refresh. The orchestrator's `refresh_universal`, `refresh_consumption` and `refresh_agent_evaluator` steps run the installer's `AnalyticsHub_Refresh_Model` against the saved model IDs. Run 06 again only when:

* you upgraded the source pin (new model definition), or
* you changed `config.json` (endpoint or Lakehouse), or
* you rotated the secret (`DEPLOY = False`).

## Connecting reports

The models are ordinary Fabric semantic models. Build your own reports on them, or connect the source repo's report template (`.pbit`).

## Checking it

```sql
SELECT step, status, exit_value, error FROM ops.run_log
WHERE step LIKE 'deploy:%' AND event = 'end' ORDER BY ended_at DESC LIMIT 10;

SELECT key, value FROM ops.config WHERE key LIKE 'model_id.%';
```

Next: [Step 8: Orchestrate](../08-orchestrate/README.md)
