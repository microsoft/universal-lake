# Step 3: Configure

On your PC you now fill in **one file**, `config.json`, and run **one command**, `npm run all`. That builds every notebook and semantic model definition with your values already in them, ready to import in step 4.

## 3.1 Tools

| Tool | Version | Check |
|---|---|---|
| Git | any | `git --version` |
| Node.js | 20.12 or later | `node --version` |
| Python | 3.9 or later (standard library only) | `python --version` |
| PowerShell | 5.1 or 7+ | `$PSVersionTable.PSVersion` |
| Azure CLI (only for `setup-app.ps1`) | 2.50 or later | `az --version` |

## 3.2 Get the code

This repo doesn't copy the ingester notebooks or model templates. It generates them from a pinned commit of an open-source Fabric installer, the **source repo**, so you get exactly the code that the installer ships. Clone both repos side by side:

```powershell
git clone <this-repo-url> UniversalLake
git clone https://github.com/microsoft/ValueLens-for-Microsoft-Copilot source-repo
cd UniversalLake
git config core.hooksPath .githooks          # optional: scan for IDs and secrets before every commit
copy config.template.json config.json        # config.json is git-ignored
```

You don't need to check out the pinned commit yourself; `npm run check` tells you if the clone is somewhere else.

## 3.3 Fill in `config.json`

Open `config.json` and replace every `<...>` value. **Don't put the client secret here**: only its Key Vault name.

| Field | Put in | From |
|---|---|---|
| `sourceRepo` | The path to the source repo clone, for example `../source-repo` | 3.2 |
| `pinnedCommit` | Leave as it is | |
| `tenantId`, `appId` | Directory (tenant) ID and application (client) ID | Step 2 |
| `keyVault.uri` | `https://<vault>.vault.azure.net/` | Step 2 |
| `keyVault.secretName` | `universal-lake-client-secret`, unless you changed it | Step 2 |
| `workspace.id`, `workspace.name` | Workspace ID and name | Step 1.4 |
| `lakehouse.id`, `lakehouse.name` | Lakehouse ID and name | Step 1.4 |
| `lakehouse.sqlEndpoint` | The SQL endpoint **host only**, `xxxx.datawarehouse.fabric.microsoft.com`. No `https://`, no port, no database name. | Step 1.4 |
| `scale` | `standard`, or `large` for more than about 20k Copilot users or a very busy audit log | Step 1.1 |
| `backfillDays` | How many days of audit history the **first load** fetches, 1 to 180. Start with **30**; you can backfill more later. | |
| `dataSources` | For each source: `api`, `csv` or `skip` (see below) | Step 2.1 |
| `azure.subscriptionId`, `azure.paygSubscriptions` | Subscription IDs to read Azure AI cost from (`consumption` only). Leave empty otherwise. | Step 2.4 |
| `dataverseEnvironments` | `{ "url": "https://<org>.crm.dynamics.com", "name": "..." }` for each environment with Copilot Studio agents (`agentEvaluator` only). Remove the sample row if you don't use it. | Step 2.4 |
| `semanticModels.*.name` | The model display names. Change them if you like; leave `id` empty. | |
| `modelSchema` | Leave as `gold` | |

`dataSources` decides which notebooks you get:

| Source | Allowed | `api` means | `csv` means |
|---|---|---|---|
| `core`, `orgData` | `api` | Always on | |
| `workday` | `csv`, `skip` | | You upload a Workday org extract |
| `m365Activity` | `api`, `skip` | Graph usage reports | |
| `agent365` | `api`, `csv`, `skip` | Graph agent registry | You upload `agents.csv` from the admin center |
| `productFeedback` | `csv`, `skip` | | You upload feedback exports |
| `studioCredits` | `csv`, `skip` | | You upload Power Platform admin center credit exports |
| `coworkCredits` | `csv`, `skip` (`api` needs a Dataflow Gen2 that the installer creates and this repo doesn't) | | You upload Viva Insights credit exports |
| `azureAi` | `api`, `skip` | Azure Cost Management and Monitor (needs `azure.subscriptionId`) | |
| `agentEvaluator` | `api`, `skip` | Dataverse transcripts (needs `dataverseEnvironments`) | |

## 3.4 Build

```powershell
npm run all
```

This runs four scripts in order. Each one can also be run on its own:

| Script | Does | Output |
|---|---|---|
| `npm run check` | Confirms the source repo clone is at `pinnedCommit` and lists any local changes in it that would be built in | console |
| `npm run sync` | Runs the installer's own notebook code to pick the notebooks your `dataSources` need and fill in tenant, app, Key Vault, workspace, Lakehouse, backfill days and sources. Prints the Graph permissions they need and **lists what changed since the last build**. | `out/notebooks/*.ipynb`, `MANIFEST.json`, `out/SOURCE.lock.json` |
| `npm run models` | Runs the installer's model code for each semantic model, pointed at your SQL endpoint, reading schema **`gold`** | `out/models/` |
| `npm run notebooks` | Builds this repo's own notebooks (`Lake_*`, `lake_ops`) into `out/notebooks/`, attached to your Lakehouse, with the parameters of `Lake_Init` and `Lake_Validate_Credentials` filled in from `config.json` | `out/notebooks/Lake_*.ipynb` |

## 3.5 Read the output before you go on

* **Warnings.** Any value still missing becomes a visible `<placeholder>` in the notebooks and a warning in the console. It is never silently defaulted. Fix `config.json` and run `npm run all` again until there are none.
* **Permissions.** Compare the Graph permission list that `sync` prints with what you granted in step 2.
* **Notebook list.** `out/notebooks/MANIFEST.json` lists the notebooks you will import. If one you expected is missing, check its `dataSources` entry (and, for Azure AI and transcripts, `azure.subscriptionId` and `dataverseEnvironments`).
* **"notebooks are unbound" message.** If `npm run notebooks` says this, `workspace.id` or `lakehouse.id` is still a placeholder, and the notebooks will have no Lakehouse attached or parameters filled in.

`out/` is git-ignored, because the files in it contain your tenant's IDs. `out/SOURCE.lock.json` records the source commit, modules, permissions and a hash of every notebook, so you can always tell what you deployed.

Next: [Step 4: Import into Fabric](../04-import/README.md)
