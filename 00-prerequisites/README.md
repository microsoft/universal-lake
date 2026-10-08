# Stage 0: Prerequisites

Check everything here **before** you start. Most failures in later stages come from a role or a tenant setting that is missing here.

## People and roles

| You need | Used in | Why |
|---|---|---|
| An **active Fabric capacity** (F2 or larger, or a trial), and **Admin** or **Member** on a workspace that runs on it | 2-7 | The Lakehouse, notebooks and models live there. Notebooks run as **you**. |
| Permission to **register apps** in Entra (the default user setting), or an existing app you own | 1 | The notebooks call Graph and Azure as this app. |
| A **Global Administrator** or **Privileged Role Administrator** | 1 | Grants admin consent for the Graph application permissions. `setup-app.ps1` does it if you are one; otherwise it prints the consent URL to send them. |
| **Contributor** on a resource group (to create a Key Vault), or **Key Vault Secrets Officer** on an existing vault | 1 | Stores the client secret. It never goes into a notebook or `config.json`. |
| **Key Vault Secrets User** on that vault, for **you** (the person running the notebooks) | 3-7 | Notebooks read the secret with your identity (`notebookutils.credentials.getSecret`). |
| A **Fabric administrator** to turn on the tenant settings below | 6 | The model connection and data check use a service principal and the Execute Queries API. |
| For credit consumption: **Owner** or **User Access Administrator** on each Azure subscription | 1 | To give the app Reader, Cost Management Reader and Monitoring Reader. |
| For the Agent Evaluator: **System Administrator** in each Power Platform environment | 1 | To add the app as an application user with the Bot Transcript Viewer role. |

## Tenant settings

| Setting | Where | Needed for |
|---|---|---|
| **Audit logging on** (Purview *Start recording user and admin activity*) | Purview portal > Audit | Core. Copilot interactions come from the audit log. New tenants can take up to 24 hours to start recording. |
| **Display concealed user, group and site names in all reports** set to off | Microsoft 365 admin center > Settings > Org settings > Reports | Licensed users and M365 activity. Otherwise names are hashed and won't join to the audit data. |
| *Service principals can call Fabric public APIs* | Fabric admin portal > Tenant settings | Stage 6 (connection binding with `CONNECTION_MODE = 'spn'`) |
| *Semantic Model Execute Queries REST API* | Fabric admin portal > Tenant settings | The row-count probe in stage 6 and the data check |
| *Users can create Fabric items* and schema-enabled Lakehouses (on by default) | Fabric admin portal > Tenant settings | Stage 2 |

The installer also needs *Fabric App items*. This repo doesn't publish an app, so you can skip it unless you package the report yourself.

## Permissions per module

Pick the modules you want. Only grant what they need. `setup-app.ps1 -Modules ...` adds exactly these.

| Module | Graph application permissions | Other access for the app | Data source if you have no access |
|---|---|---|---|
| `core` (always on) | `AuditLogsQuery.Read.All`, `Reports.Read.All` | none | none; core is required |
| `orgData` | `User.Read.All` | none | CSV upload (HR or Workday export) |
| `m365Activity` | `Reports.Read.All` | none | none |
| `agent365` | `CopilotPackages.Read.All`, `Application.Read.All`, `User.Read.All` | none | CSV upload from the Agent 365 admin page |
| `productFeedback` | none | none | CSV upload (Microsoft 365 admin center export) |
| `consumption` | none | **Reader**, **Cost Management Reader** and **Monitoring Reader** on each subscription with Azure AI or Copilot Studio PAYG meters | CSV upload of Studio and Cowork credits |
| `agentEvaluator` | none | A **Dataverse application user** with the **Bot Transcript Viewer** security role in each environment | none |

`npm run sync` prints the exact Graph permission list for the modules and data sources in your `config.json`, and writes it to `out/SOURCE.lock.json`.

## Tools on your PC

| Tool | Version | Check |
|---|---|---|
| Git | any | `git --version` |
| Node.js | 20.12 or later | `node --version` |
| Python | 3.9 or later (the notebook builder uses the standard library only) | `python --version` |
| Azure CLI, signed in to the right tenant | 2.50 or later | `az account show --query tenantId` |
| PowerShell | 5.1 or 7+ | `$PSVersionTable.PSVersion` |
| A clone of the source repo ([microsoft/ValueLens-for-Microsoft-Copilot](https://github.com/microsoft/ValueLens-for-Microsoft-Copilot), the open-source installer whose notebooks and model templates are reused) at the commit in `pinnedCommit` | | `npm run check` |

## Checklist

- [ ] Capacity and workspace chosen; you are Admin or Member.
- [ ] Key Vault chosen; you can write secrets (or a vault admin will), and you can read them.
- [ ] Consent admin lined up.
- [ ] Audit logging on, report concealment off.
- [ ] Fabric tenant settings on.
- [ ] Modules chosen; the subscription and Dataverse owners are lined up for optional modules.
- [ ] `config.json` created from `config.template.json`, with `sourceRepo` set.

Next: [Stage 1: App registration](../01-app-registration/README.md)
