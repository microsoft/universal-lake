# Universal Data Lake for Microsoft 365 and Copilot data

Build **one Microsoft Fabric Lakehouse** that holds your Microsoft 365 Copilot data, your agent data, and how people use Teams, Outlook, Word, Excel, PowerPoint, OneNote, SharePoint, OneDrive and Viva Engage. The data is cleaned and shaped into report-ready tables, and **semantic models** sit on top, ready for Power BI, Copilot in Power BI, data agents or your own SQL.

**Why bother?** Most Copilot and Microsoft 365 reports each collect their own copy of the data, so every new report means setting up the same sources, permissions and refreshes again. Build the lake once and that stops:

* **Plug in our Power BI templates** without repeating the setup for each report. They all read the same Lakehouse ([templates](templates/README.md)).
* **Build your own analytics and observability foundation.** All the data sits in one place you own, ready for your own reports, Fabric apps, data agents or plain SQL.
* **Know exactly what's going on.** Every step is a notebook you can open, read, change and rerun, so you can customise what's collected and how it's shaped.

**Fair warning: this is flat-pack furniture.** Setting it up feels a lot like assembling an IKEA wardrobe. You unbox everything, lay the parts out on the floor, find the tools (the Allen key is in here somewhere), do step one, then flip to the manual for step two. Repeat. There's no "install" button, and at some point you'll be convinced a part is missing (it isn't; check [Troubleshooting](TROUBLESHOOTING.md)).

The payoff: when it is done, you know exactly how this is put together. If a step goes wrong, you don't have to take the whole thing apart. You can see which step, which cell, which source and which dates failed, and redo just that one.

**You end up with**

* one Lakehouse with all the data, refreshed daily;
* semantic models with relationships and measures, ready to report on;
* a log of every step and every date range loaded.

This repo builds the lake and the models, and ships two Power BI templates that report on it ([step 8](templates/README.md)). Fabric apps and agents on top are separate deployments that connect to them.

```mermaid
flowchart LR
  S["Data sources<br/>audit log, M365 usage reports,<br/>Entra ID, Agent 365, Dataverse,<br/>credits and cost"] --> N["Ingester notebooks<br/>(step 5)"]
  N --> L[("One Lakehouse<br/>raw → cleaned → report-ready<br/>(step 6)")]
  L --> M["Semantic models<br/>(step 6)"]
  M -.-> U["Fabric apps, agents<br/>(later, separate)"]
  L --> T["Power BI templates<br/>ValueLens, AI-in-One<br/>(step 8)"]
```

## Disclaimer

> [!IMPORTANT]
> **This is not the official Copilot report.** The official sources for Copilot usage reporting are the **Microsoft 365 admin center** (Copilot usage reports) and **Viva Insights** (Copilot Dashboard). This lake builds its Copilot figures from the Purview audit log, which is not the authoritative source for usage reporting. Its numbers may not always match the official reports exactly.
>
> **You are responsible for the data once it is extracted.** Retention, deletion and other policies set in the source systems (Purview, Microsoft 365, Entra ID, Dataverse and others) do not apply to the copies this lake makes. It is up to you to manage the extracted data and comply with the requirements that apply to your organisation.

## What you need

| | Minimum |
|---|---|
| Fabric capacity | **F2**, or a free Fabric trial. **F64+** for more than ~10,000 people or for viewers without Power BI Pro. See [step 1](01-fabric/README.md#11-pick-a-capacity). |
| Fabric workspace | One, where you are **Contributor** or above. Deploy creates the Lakehouse in it. |
| Entra ID | Rights to register an app, and an admin who can grant consent |
| Azure Key Vault | **Recommended** for the app's secret. No vault yet? You can put the secret in `config.json` for a first run (not recommended; see [step 2.2](02-permissions/README.md#22-store-the-client-secret)). |
| A PC with | Git, Node.js 20.12+, Python 3.9+ (see [Before you start](#before-you-start)) |

## Before you start

**How it fits together.** All your settings go in one file, `config.json`. **You don't fill it in now**: you don't have the values yet. Steps 1 to 4 produce them, and each step tells you which line to set:

| Step | What you create | What goes into `config.json` |
|---|---|---|
| 1 | A Fabric workspace | Its name |
| 2 | An app registration with permissions | Its IDs and secret (or Key Vault) |
| 3 | Your choice of data sources, and a folder of CSV exports | `api`, `csv` or `skip` for each, and the folder |
| 4 | `npm run deploy` creates the Lakehouse and sets everything up | Deploy fills in the workspace and Lakehouse IDs itself |

**Where the data comes from.** The lake gets data in two ways:

* **APIs:** the app you register in step 2 pulls it automatically, every day. No files to handle.
* **CSV exports:** a few sources (product feedback, Copilot Studio credits, Viva Copilot credits) have no API, so someone **exports them from an admin portal**. You save them in one folder and deploy uploads them.

**1. Get the code.** Install Git, **Node.js 20.12+** and **Python 3.9+** (check with `git --version`, `node --version`, `python --version`). Then clone this repo (its URL is under **Code > Clone** at the top of its GitHub page). Everything it needs is inside; there's nothing else to download.

```powershell
git clone <this-repo-url> UniversalLake
cd UniversalLake
copy config.template.json config.json
```

Your IDs stay in `config.json` on your PC; it is never uploaded to GitHub. Leave it as it is for now. Each setting has a `//` comment saying what it is and where it comes from; leave the comments in (your editor may underline them; that's fine). There's no `npm install`: the build uses only Node.js and Python. If `npm` is blocked on your PC (e.g. a Microsoft-managed device), see [If `npm` doesn't work](03-configure/README.md#if-npm-doesnt-work).

**2. Decide which sources you want.** Look at the [data sources table](#data-sources). `copilotInteractions` and `orgData` are required; start with those and add others later if you like. Your choice decides the app's permissions in step 2, so make it now (you write it into `config.json` in step 3).

**3. Start the CSV exports now (only for CSV sources you want).** They need admin roles you may not have, so ask early:

* Find the role for each export in the [data sources table](#data-sources) and ask whoever has it.
* Save **all the exported files in one folder on your PC**, outside this repo (for example `Documents\UniversalLake-exports`). Subfolders are fine. In step 3 you put this folder in `config.json` as `exportsFolder`; deploy recognises each file by its columns and uploads it.
* [Which Studio and Viva files](03-configure/README.md#studio-and-viva-which-files).
* Can't get a file yet? You can still build the lake; that source's tables stay empty until you add it and deploy again.

## Steps

Do them in order. Each folder's README is a short checklist; if something goes wrong, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

| Step | You do | Where |
|---|---|---|
| [1. Fabric](01-fabric/README.md) | Pick a capacity, create the workspace, put its name in `config.json` | Fabric portal |
| [2. Permissions](02-permissions/README.md) | Register the app, store its secret, give it access, **confirm the checklist** | Entra, Microsoft 365 admin, Azure portals |
| [3. Configure](03-configure/README.md) | Finish `config.json`: data sources and your exports folder | Your PC |
| [4. Deploy](04-deploy/README.md) | `npm run deploy`: creates the Lakehouse, uploads notebooks, model files and CSVs, runs `Lake_Setup` to check everything | Your PC |
| [5. Ingest](05-ingest/README.md) | Run `Lake_Orchestrator` once with `first_load`: all ingesters, the first backfill, processing and promote | Fabric |
| [6. Models](06-models/README.md) | Check the report-ready tables and the semantic models the step 5 run created | Fabric |
| [7. Orchestrate](07-orchestrate/README.md) | Schedule the daily run, [re-run only what failed](07-orchestrate/RERUNS.md) | Fabric |
| [8. Reports](templates/README.md) | Open the ValueLens or AI-in-One template, point it at the Lakehouse, publish | Power BI Desktop |
**Backfill.** The first run loads 30 days of audit history by default (up to 180). Daily runs then pick up where the last one stopped. Every date range loaded is recorded in `ops.backfill_ledger`.

## Data sources

**Copilot interactions** and **Org data** are required. Pick the others before step 2 (see [Before you start](#before-you-start)), because they decide the app's permissions. You can add more later. The tables each one creates are listed in [step 6](06-models/README.md).

| Source (`config.json` name) | What you get | Needs |
|---|---|---|
| **Copilot interactions**<br/>`copilotInteractions` | Every Copilot prompt and agent run, from the Purview audit log, plus who has a Copilot licence | Graph `AuditLogsQuery.Read.All`, `Reports.Read.All` |
| **Org data**<br/>`orgData` | Department, job title, country and manager for each person, from Entra ID | Graph `User.Read.All` |
| **M365 activity**<br/>`m365Activity` | Daily use of Teams, Outlook, Word, Excel, PowerPoint, OneNote, SharePoint, OneDrive and Viva Engage | Graph `Reports.Read.All` |
| **Agent 365**<br/>`agent365` | Every agent in the tenant, with its publisher, status and owners | Graph `CopilotPackages.Read.All`, `Application.Read.All` (or a CSV export) |
| **Product feedback**<br/>`productFeedback` | Copilot thumbs up and down, with comments | CSV from Microsoft 365 admin center > **Health > Product feedback > Export**.<br/>Role: Global Administrator or Reports Reader |
| **Agent evaluator**<br/>`agentEvaluator` | Copilot Studio conversation transcripts, from Dataverse | No CSV; read directly from Dataverse. A Power Platform Administrator adds the app as an application user with **Bot Transcript Viewer** (Power Platform admin center) |
| **Consumption**<br/>`consumption` | Copilot Studio and Copilot credits, Azure AI cost and tokens | **Studio credits:** CSVs from Power Platform admin center > **Licensing > Copilot Studio** (tenant, per-agent and per-user reports; [which files](03-configure/README.md#studio-and-viva-which-files)). Role: Power Platform Administrator<br/>**Copilot credits:** CSVs from Viva Insights > **Copilot Consumption Dashboard > Export** (`PersonServiceCreditsMetrics` and `SpendingPolicyMetadata`). Role: Insights Analyst<br/>**Azure AI:** no CSV. A subscription Owner gives the app Reader, Cost Management Reader and Monitoring Reader on the subscription ([2.4](02-permissions/README.md#24-azure-ai-access-only-if-azureai-is-api)) |

## What ends up in the Lakehouse

You don't need to know these to use the lake, but you'll see them as folders (schemas) in the Lakehouse. Data moves left to right: raw, then cleaned, then report-ready.

| Folder | What's in it | Do you use it? |
|---|---|---|
| `gold` | The report-ready tables. The semantic models read only these. | **Yes.** Point reports, apps and SQL here. |
| `silver` | Cleaned data and history the models don't read | Rarely |
| `bronze` | Raw data as it arrived, and logs | Only to troubleshoot |
| `ops` | Settings, the run log, and which dates have been loaded | To check runs |
| `dbo` | The notebooks' working tables | No. Leave them alone; each daily load reads its own previous output. |

## How the ingesters work

They ask Microsoft's APIs for data a few requests at a time, stay within Purview's audit search limits, and save each finished piece, so a stopped run carries on where it left off. Spark then unpacks all the nested records at once across the cluster and updates the tables in place, so re-runs never create duplicates. Details: [ARCHITECTURE.md](ARCHITECTURE.md).

## Where the notebook code comes from

Everything is in this repo. `notebooks/` holds the ingester and processor notebooks, `models/` the semantic model definitions (`.bim`), and `scripts/build/` the code that fills in your settings. `npm run deploy` fills them in and sends them to Fabric (`npm run all` only builds them into `out/`). The `Lake_*` notebooks (sources in `notebook-src/`) set up the Lakehouse and check credentials (`Lake_Setup`), sort tables into layers, deploy the models and run everything in order.

To take a newer version of this repo: `git pull`, `npm run deploy` (it only sends what changed), then run `Lake_Deploy_Models` (updates the models) and `Lake_Orchestrator`.

## Repository layout

```
01-fabric/ … 07-orchestrate/   one folder per step: README plus that step's notebook or script
TROUBLESHOOTING.md             fixes for setup problems
config.template.json           copy to config.json (git-ignored)
scripts/                       deploy, generate notebooks and models (scripts/build/), scan for secrets
notebooks/                     ingester and processor notebook templates
models/                        semantic model definitions (.bim)
notebook-src/                  readable sources of the Lake_* notebooks
templates/                     Power BI templates (.pbit) that report on the Lakehouse (step 8)
out/                           generated, git-ignored: what deploy sends to Fabric
```

## For contributors

Only needed if you change this repo and push it back. Your IDs (and the secret, if you use the bypass) go only in `config.json` and `out/`, which are git-ignored. `npm run scan` fails if a file that would be committed has a GUID, a secret or key, a personal path or email, a notebook with outputs or a Lakehouse binding, or any term you list in `.scan-blocklist` (git-ignored). Run `git config core.hooksPath .githooks` once to scan before every commit; CI runs the same scan on every push.
