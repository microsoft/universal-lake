# Step 2: Permissions and app registration

The ingesters call Microsoft Graph, Azure and Dataverse **as an app registration** with a client secret. The secret is kept in **Azure Key Vault**, and the notebooks read it at run time with the identity of whoever runs them. It never appears in a notebook, in `config.json` or in this repo.

Most failures later on are a missing role or tenant setting from this page. **Go through the checklist at the end and confirm every line before you continue.**

## 2.1 Pick your modules

Each data source is a module. `core` is always on; the others are optional, and you can add them later. Only grant what your modules need.

| Module | Data | Graph application permissions | Other access the app needs | No API access? |
|---|---|---|---|---|
| `core` | Copilot interactions (Purview audit), licensed users | `AuditLogsQuery.Read.All`, `Reports.Read.All` | none | required |
| `orgData` | Department, job title, country, manager from Entra ID | `User.Read.All` | none | CSV upload (HR or Workday export) |
| `m365Activity` | Daily Teams, Outlook, Word, Excel, PowerPoint, SharePoint, OneDrive and Viva Engage use per person | `Reports.Read.All` | none | none |
| `agent365` | Agent registry: publisher, status, owners | `CopilotPackages.Read.All`, `Application.Read.All`, `User.Read.All` | none | CSV upload from the Agent 365 admin page |
| `productFeedback` | Copilot thumbs up / down and comments | none | none | CSV upload only |
| `consumption` | Azure AI cost and tokens, Copilot Studio and Cowork credits | none | **Reader**, **Cost Management Reader** and **Monitoring Reader** on each Azure subscription | CSV upload of Studio and Cowork credits |
| `agentEvaluator` | Copilot Studio transcripts from Dataverse | none | A **Dataverse application user** with the **Bot Transcript Viewer** role in each environment | none |

## 2.2 Line up the people

| Who | Does | When |
|---|---|---|
| **You** | Admin or Member of the workspace from step 1; permission to register apps in Entra (the default user setting) | Now |
| A **Global Administrator** or **Privileged Role Administrator** | Grants admin consent for the Graph permissions. If that's you, `setup-app.ps1` does it; otherwise it prints a consent link to send them. | 2.4 |
| A **Key Vault owner** | Creates a vault (or lets you use one) where you can **write** secrets (*Key Vault Secrets Officer*), and gives **everyone who runs notebooks** *Key Vault Secrets User* | 2.4 |
| A **Fabric administrator** | Turns on the Fabric tenant settings in 2.3 | 2.3 |
| An **Azure subscription Owner** or User Access Administrator (`consumption` only) | Gives the app the three reader roles | 2.4 |
| A **Power Platform System Administrator** (`agentEvaluator` only) | Adds the app as an application user in each environment | 2.4 |

## 2.3 Tenant settings

| Setting | Where | Set to | Needed for |
|---|---|---|---|
| Audit logging (*Start recording user and admin activity*) | Purview portal > Audit | **On** | `core`. New tenants can take up to **24 hours** to start recording. |
| *Display concealed user, group, and site names in all reports* | Microsoft 365 admin center > Settings > Org settings > Reports | **Off** | Licensed users and M365 activity. Otherwise the reports return hashed IDs instead of user names and nothing joins. |
| *Service principals can use Fabric APIs* | Fabric admin portal > Tenant settings | **On** (for the app, or a group it is in) | The models' connection in step 7 |
| *Semantic Model Execute Queries REST API* | Fabric admin portal > Tenant settings | **On** | Row counts and the data check in step 7 |
| *Users can create Fabric items* | Fabric admin portal > Tenant settings | **On** (the default) | Step 1 |

## 2.4 Create the app registration

### Option A: script (recommended)

`setup-app.ps1` uses the Azure CLI. It is safe to re-run: it reuses an app with the same name and only adds what is missing. Add `-WhatIf` to see what it would do without changing anything.

```powershell
az login --tenant <tenant-id>
./02-permissions/setup-app.ps1 -KeyVaultName <vault> `
    -Modules core,orgData,m365Activity,agent365,consumption,agentEvaluator `
    -AzureSubscriptionIds <sub-guid>       # only with consumption
```

| Parameter | Default | Meaning |
|---|---|---|
| `-KeyVaultName` | required | An existing vault you can write secrets to |
| `-AppName` | `Universal Data Lake` | Display name. An existing app with this name is reused. |
| `-SecretName` | `universal-lake-client-secret` | The secret's name in Key Vault; goes into `keyVault.secretName` in step 3 |
| `-Modules` | `core,orgData,m365Activity` | Adds the Graph permissions for these modules only (table 2.1) |
| `-SecretYears` | `1` | Secret lifetime. The expiry date is also set on the Key Vault secret, so you can alert on it. |
| `-AzureSubscriptionIds` | none | Gives the app Reader, Cost Management Reader and Monitoring Reader on each subscription |
| `-SkipConsent` | off | Don't grant admin consent; print the consent link for an admin instead |
| `-RotateSecret` | off | Make a new secret even if the vault already has one |

At the end it prints the four values for step 3 (`tenantId`, `appId`, `keyVault.uri`, `keyVault.secretName`) and the follow-ups it can't do itself.

### Option B: portal

1. **Entra admin center > App registrations > New registration.** Single tenant, no redirect URI. Copy the **Application (client) ID** and **Directory (tenant) ID**.
2. **API permissions > Add a permission > Microsoft Graph > Application permissions.** Add the permissions for your modules from table 2.1, then choose **Grant admin consent**. Every row should show a green tick.
3. **Certificates & secrets > New client secret.** Copy the **Value** (not the Secret ID) straight into **Key Vault > Secrets > Generate/Import**, with the name `universal-lake-client-secret`, and set the same expiry date. Don't paste it anywhere else.
4. `consumption`: on each subscription, **Access control (IAM) > Add role assignment**, and give the app **Reader**, **Cost Management Reader** and **Monitoring Reader**.

### Follow-ups for both options

1. Give **yourself**, and anyone else who will run the notebooks or own a schedule, **Key Vault Secrets User** on the vault. Being Owner of the vault is not enough if it uses Azure RBAC.
2. `agentEvaluator`: in each Power Platform environment, go to **Settings > Users + permissions > Application users > New app user**. Add the app and give it the **Bot Transcript Viewer** security role.
3. In the Fabric workspace from step 1, choose **Manage access > Add people or groups**, search for the app by name, and give it **Viewer**. The semantic models' connection signs in as the app (step 7) and needs to read the Lakehouse SQL endpoint.
4. New consent can take **a few minutes** to show up in tokens. If a check fails straight after consent, wait and run it again.

## 2.5 Confirm before you continue

Tick every line that applies to your modules. If you can't tick one, sort it out now: the notebook `Lake_Validate_Credentials` checks most of these in step 4, but it is quicker to fix them here.

- [ ] I am **Admin** or **Member** of the workspace from step 1.
- [ ] The app registration exists, and I have its **tenant ID** and **client ID**.
- [ ] **Admin consent** is granted for every Graph permission my modules need (green ticks on *API permissions*).
- [ ] The client secret is in **Key Vault**, and I have the vault URI and the secret name.
- [ ] I (and every other notebook runner or schedule owner) have **Key Vault Secrets User** on the vault.
- [ ] **Audit logging** is on (and has been for at least 24 hours on a new tenant).
- [ ] **Concealed names** in reports are **off**.
- [ ] The two **Fabric tenant settings** for service principals and Execute Queries are on.
- [ ] The app is a **Viewer** (or above) of the workspace.
- [ ] `consumption`: the app has the three reader roles on every subscription I listed.
- [ ] `agentEvaluator`: the app is an application user with **Bot Transcript Viewer** in every environment I listed.

## Rotating the secret later

```powershell
./02-permissions/setup-app.ps1 -KeyVaultName <vault> -RotateSecret
```

The notebooks read the vault on every run, so nothing else changes. If you deployed the models with `CONNECTION_MODE = 'spn'`, re-run `Lake_Deploy_Models` with `DEPLOY = False` so their connection gets the new secret (step 7).

Next: [Step 3: Configure](../03-configure/README.md)
