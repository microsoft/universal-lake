# Step 3: Configure

On your PC: fill in **one file** (`config.json`) and run **one command** (`npm run all`). That generates the notebooks and model files, with your IDs already filled in, into `out/`. Nothing goes to Fabric yet; that's step 4.

## 3.1 Install the tools

Git, **Node.js 20.12+** and **Python 3.9+** (no extra packages). Check with `git --version`, `node --version`, `python --version`.

## 3.2 Get the code

The ingester notebooks and model definitions are generated from a fixed version of the open-source installer (the *source repo*). Clone both repos next to each other (use the URL from **Code > Clone** at the top of this repo's GitHub page):

```powershell
git clone <this-repo-url> UniversalLake
git clone https://github.com/microsoft/ValueLens-for-Microsoft-Copilot source-repo
cd UniversalLake
copy config.template.json config.json
```

`config.json` is git-ignored, so your IDs never get committed.

## 3.3 Fill in `config.json`

Replace every `<...>` value.

| Field | Value | Where you got it |
|---|---|---|
| `sourceRepo` | `../source-repo` | 3.2 |
| `pinnedCommit` | leave as it is | |
| `tenantId` | Directory (tenant) ID | [2.3](../02-permissions/README.md#23-register-the-app), app Overview |
| `appId` | Application (client) ID | [2.3](../02-permissions/README.md#23-register-the-app), app Overview |
| `keyVault.uri` | `https://<name>.vault.azure.net/` | [2.4](../02-permissions/README.md#24-store-the-client-secret), vault Overview. Leave as is if you use the bypass. |
| `keyVault.secretName` | `universal-lake-client-secret` | 2.4 |
| `clientSecret` | **Leave `""`** with Key Vault. Bypass only (not recommended): the secret value. | 2.4 |
| `workspace.id` | GUID after `/groups/` in the URL | [1.4](../01-fabric/README.md#14-copy-three-values-from-fabric) |
| `workspace.name` | The workspace name | 1.2 |
| `lakehouse.id` | GUID after `/lakehouses/` in the URL | [1.4](../01-fabric/README.md#14-copy-three-values-from-fabric) |
| `lakehouse.name` | `UniversalLake_LH` | 1.3 |
| `lakehouse.sqlEndpoint` | Host only: `xxxx.datawarehouse.fabric.microsoft.com` | [1.4](../01-fabric/README.md#14-copy-three-values-from-fabric) |
| `scale` | `standard`, or `large` above ~20k Copilot users | 1.1 |
| `backfillDays` | Days of audit history in the first load. **30** is a good start; max 180. | |
| `dataSources` | `api`, `csv` or `skip` per source (below) | 2.1 |
| `azure.subscriptionId` | Only if `azureAi` is `api`; otherwise leave `""` | |
| `dataverseEnvironments` | Only if `agentEvaluator` is `api`: `{ "url": "https://<org>.crm.dynamics.com", "name": "..." }`. Otherwise delete the sample row. | |
| `semanticModels`, `modelSchema` | leave as they are | |

**`dataSources`**: set anything you're not using to `skip`. The template turns most sources on.

| Source | Allowed | Notes |
|---|---|---|
| `core`, `orgData` | `api` | Always on |
| `m365Activity` | `api`, `skip` | |
| `agent365` | `api`, `csv`, `skip` | `csv` if you lack Agent 365 or the Graph permissions |
| `workday` | `csv`, `skip` | Only if org data comes from a Workday export |
| `productFeedback`, `studioCredits`, `coworkCredits` | `csv`, `skip` | You upload exports in step 4 |
| `azureAi` | `api`, `skip` | Needs `azure.subscriptionId` |
| `agentEvaluator` | `api`, `skip` | Needs `dataverseEnvironments` |

## 3.4 Generate the files to import

```powershell
npm run all
```

This only writes files on your PC. It checks the source repo, picks the notebooks your `dataSources` need, fills in your IDs, builds the semantic model definitions for the `gold` schema, and builds this repo's `Lake_*` notebooks. Output:

| Folder | Contains | Used in |
|---|---|---|
| `out/notebooks/` | Every notebook to import, with your Lakehouse attached; `MANIFEST.json` lists them | Step 4.1 |
| `out/models/` | One `definition.json` per semantic model, plus readable `model.bim` and `relationships.txt`, and `gold_tables.json` | Step 4.5 |

**Read the console output:**

* **Warnings** mean a value is still a placeholder. Fix `config.json` and run `npm run all` again until there are none.
* It prints the **Graph permissions** your notebooks need. Compare them with step 2.
* *"notebooks are unbound"* means `workspace.id` or `lakehouse.id` is missing.
* With the bypass, it warns that the secret was written into `out/notebooks`. That's expected; don't share that folder.

(`npm` is just the script runner here. `npm run all` = `check`, `sync`, `models`, `notebooks`; each can be run on its own.)

Next: [Step 4: Import into Fabric](../04-import/README.md)
