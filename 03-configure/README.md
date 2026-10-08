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

### Required: every setup

Replace each `<...>` value. The build warns about any you miss.

| Field | Value | Where you got it |
|---|---|---|
| `sourceRepo` | `../source-repo` | 3.2 |
| `tenantId` | Directory (tenant) ID | [2.1](../02-permissions/README.md#21-register-the-app-and-add-permissions), app Overview |
| `appId` | Application (client) ID | [2.1](../02-permissions/README.md#21-register-the-app-and-add-permissions), app Overview |
| `workspace.id` | GUID after `/groups/` in the URL | [1.4](../01-fabric/README.md#14-copy-three-values-from-fabric) |
| `workspace.name` | The workspace name | 1.2 |
| `lakehouse.id` | GUID after `/lakehouses/` in the URL | [1.4](../01-fabric/README.md#14-copy-three-values-from-fabric) |
| `lakehouse.sqlEndpoint` | Host only: `xxxx.datawarehouse.fabric.microsoft.com` | [1.4](../01-fabric/README.md#14-copy-three-values-from-fabric) |
| **Secret: one of** | **Key Vault (recommended):** `keyVault.uri` = `https://<name>.vault.azure.net/`, and leave `clientSecret` as `""`.<br>**Bypass (not recommended):** leave `keyVault.uri` as it is and put the secret value in `clientSecret`. | [2.2](../02-permissions/README.md#22-store-the-client-secret) |
| `dataSources` | Which sources to load; see the next table. Set what you don't use to `skip` (the template turns most on). | |

**`dataSources`**

| Source | Required? | Allowed | Notes |
|---|---|---|---|
| `copilotInteractions` | **Required** | `api` | Copilot prompts and responses, from the audit log |
| `orgData` | **Required** | `api` | Users, departments, managers |
| `m365Activity` | Optional | `api`, `skip` | Teams, Outlook, Word, Excel, PowerPoint usage |
| `agent365` | Optional | `api`, `csv`, `skip` | `csv` if you lack Agent 365 or its Graph permissions |
| `workday` | Optional | `csv`, `skip` | Only if org data comes from a Workday export |
| `productFeedback`, `studioCredits`, `coworkCredits` | Optional | `csv`, `skip` | You upload the exports in step 4 |
| `azureAi` | Optional | `api`, `skip` | Also fill in `azure.subscriptionId` (below) |
| `agentEvaluator` | Optional | `api`, `skip` | Also fill in `dataverseEnvironments` (below) |

### Optional: only if you turned on that source

| Field | Fill in when | Otherwise |
|---|---|---|
| `azure.subscriptionId` | `azureAi` is `api`: the subscription that holds your Azure AI resources | leave `""` |
| `azure.paygSubscriptions` | Copilot pay-as-you-go is billed to other subscriptions: list their IDs | leave `[]` |
| `dataverseEnvironments` | `agentEvaluator` is `api`: one `{ "url": "https://<org>.crm.dynamics.com", "name": "..." }` per Copilot Studio environment | delete the sample row (leave `[]`) |

### Optional: defaults are fine

| Field | Default | Change it when |
|---|---|---|
| `scale` | `standard` | Use `large` above ~20k Copilot users (see 1.1) |
| `backfillDays` | `30` | You want more audit history in the first load (max 180) |
| `keyVault.secretName` | `universal-lake-client-secret` | You named the secret differently in 2.2 |
| `lakehouse.name` | `UniversalLake_LH` | You named the Lakehouse differently in 1.3 |
| `pinnedCommit`, `semanticModels`, `modelSchema` | as shipped | Leave them |

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
