# Step 2: Permissions

The notebooks sign in to Microsoft Graph (and, optionally, Azure and Dataverse) as an **app registration** with a client secret. In this step you turn on a few tenant settings, register the app in the portal, store its secret, and confirm everything with the checklist at the end.

Most failures later are a missing setting from this page, so **don't skip the checklist**.

## 2.1 Pick your data sources

`core` is required. Add others now or later; only grant what you pick.

| Module | Graph application permissions | Other access |
|---|---|---|
| `core` | `AuditLogsQuery.Read.All`, `Reports.Read.All` | |
| `orgData` | `User.Read.All` | |
| `m365Activity` | `Reports.Read.All` | |
| `agent365` | `CopilotPackages.Read.All`, `Application.Read.All`, `User.Read.All` | or use a CSV export instead |
| `productFeedback` | none | CSV export |
| `consumption` | none | For Azure AI cost: Reader, Cost Management Reader, Monitoring Reader on the subscription. Credits come from CSV exports. |
| `agentEvaluator` | none | App added as a Dataverse application user with **Bot Transcript Viewer** |

## 2.2 Turn on tenant settings

Ask the admin who owns each portal if it isn't you.

| Setting | Where | Set to |
|---|---|---|
| Audit logging | Microsoft Purview portal > **Audit**. If you see *Start recording user and admin activity*, click it. | **On**. A new tenant can take **24 hours** to start. |
| *Display concealed user, group, and site names in all reports* | Microsoft 365 admin center > **Settings > Org settings > Reports** | **Off** (unticked). Otherwise reports show hashed IDs instead of names. |
| *Service principals can use Fabric APIs* | Fabric > **Settings (gear) > Admin portal > Tenant settings** | **On** (whole org, or a group containing the app) |
| *Semantic Model Execute Queries REST API* | Same page | **On** |

## 2.3 Register the app

All in the [Entra admin center](https://entra.microsoft.com):

1. **Applications > App registrations > New registration.** Name it `Universal Data Lake`, *Accounts in this organizational directory only*, no redirect URI. **Register**.
2. On the app's **Overview** page, copy:
   * **Application (client) ID** → `appId` in step 3
   * **Directory (tenant) ID** → `tenantId` in step 3
3. **API permissions > Add a permission > Microsoft Graph > Application permissions.** Tick the permissions for your modules (2.1), **Add permissions**.
4. **Grant admin consent for _your tenant_.** Every row should show a green tick. Only a Global Administrator or Privileged Role Administrator can do this; if the button is greyed out, send them the app name.
5. **Certificates & secrets > Client secrets > New client secret.** Pick an expiry (e.g. 12 months), **Add**, and copy the **Value** column right away. It is shown only once. (Not the *Secret ID*.)

## 2.4 Store the client secret

### Option 1: Azure Key Vault (recommended)

The secret stays in the vault; the notebooks fetch it each run as the person running them.

1. In the Azure portal, open your Key Vault (or create one) > **Objects > Secrets > Generate/Import**.
2. Name `universal-lake-client-secret`, Value = the secret from 2.3, set the same expiry date. **Create**.
3. **Access control (IAM) > Add role assignment > Key Vault Secrets User**, for **you** and anyone else who will run notebooks or own the schedule. (Being vault Owner isn't enough on an RBAC vault.)
4. Copy the **Vault URI** from the vault's **Overview** (`https://<name>.vault.azure.net/`) → `keyVault.uri` in step 3.

You need *Key Vault Secrets Officer* (or a vault admin's help) to create the secret.

### Option 2: put the secret in `config.json` (not recommended)

Use this only if you don't have a Key Vault yet, or can't get the Secrets Officer role, and want a first run working.

* In step 3, leave `keyVault.uri` as it is and paste the secret into `"clientSecret"` in `config.json`.
* The build then writes the secret **into the generated notebooks**. Anyone who can open those notebooks in the workspace can read it.

If you take this route: keep workspace access to the people who need it, don't share or export the notebooks, never commit `config.json` or `out/` (both are git-ignored), and move to Option 1 as soon as you can (set `keyVault.uri`, clear `clientSecret`, rebuild and re-import).

## 2.5 Give the app access to what it reads

1. **Fabric workspace** (always): workspace > **Manage access > Add people or groups**, search the app name, role **Viewer**. The semantic models connect to the Lakehouse as the app.
2. **`consumption` only**: on each Azure subscription > **Access control (IAM) > Add role assignment**, give the app **Reader**, **Cost Management Reader** and **Monitoring Reader**.
3. **`agentEvaluator` only**: [Power Platform admin center](https://admin.powerplatform.microsoft.com) > environment > **Settings > Users + permissions > Application users > New app user**, add the app, role **Bot Transcript Viewer**.

## 2.6 Confirm before you continue

- [ ] Audit logging is on (24 hours on a new tenant).
- [ ] Concealed names in reports are off.
- [ ] The two Fabric tenant settings are on.
- [ ] The app exists; I have its **tenant ID** and **client ID**.
- [ ] Admin consent shows green ticks for every Graph permission I need.
- [ ] The secret is in Key Vault and I have *Key Vault Secrets User* **— or —** I've knowingly chosen the `config.json` bypass and have the secret value.
- [ ] The app is **Viewer** on the workspace.
- [ ] `consumption`: the app has the three reader roles. `agentEvaluator`: the app is a Dataverse application user.

`Lake_Validate_Credentials` re-checks most of this in step 4, but fixing it now is quicker. New consent can take a few minutes to reach tokens.

## Optional: do 2.3–2.5 with a script

If you have the Azure CLI and a Key Vault you can write to, `setup-app.ps1` registers the app, adds and consents the permissions, stores the secret in the vault and assigns the subscription roles. It is safe to re-run; add `-WhatIf` to preview.

```powershell
az login --tenant <tenant-id>
./02-permissions/setup-app.ps1 -KeyVaultName <vault> -Modules core,orgData,m365Activity
```

Other parameters: `-AppName`, `-SecretName`, `-SecretYears`, `-AzureSubscriptionIds`, `-SkipConsent` (prints a consent link for an admin), `-RotateSecret`. You still do the workspace Viewer and Dataverse steps by hand.

## When the secret expires

Create a new secret on the app (2.3 step 5), then:

* **Key Vault**: update the secret in the vault. Notebooks pick it up on the next run.
* **`config.json` bypass**: update `clientSecret`, run `npm run all`, delete and re-import the notebooks (step 4).

In both cases, then run `Lake_Deploy_Models` with `DEPLOY = False` so the models' connection gets the new secret (step 7).

Next: [Step 3: Configure](../03-configure/README.md)
