# Step 2: Permissions

The notebooks sign in to Microsoft Graph (and, optionally, Azure and Dataverse) as an **app registration** with a client secret. In this step you register the app with the permissions for the data sources you chose in [Before you start](../README.md#before-you-start), store its secret, give it access to the Lakehouse, and confirm with the checklist at the end.

Most failures later are a missing item from this page, so **don't skip the checklist**.

## 2.1 Register the app and add permissions

All in the [Entra admin center](https://entra.microsoft.com):

1. **Applications > App registrations > New registration.** Name it `Universal Data Lake`, *Accounts in this organizational directory only*, no redirect URI. **Register**.
2. On the app's **Overview** page, copy:
   * **Application (client) ID** → `appId` in `config.json`
   * **Directory (tenant) ID** → `tenantId` in `config.json`
3. **API permissions > Add a permission > Microsoft Graph > Application permissions.** Tick the permissions for each data source you'll use, then **Add permissions**:

   | Data source | Graph application permissions |
   |---|---|
   | `copilotInteractions` (**required**) | `AuditLogsQuery.Read.All`, `Reports.Read.All` |
   | `orgData` (**required**) | `User.Read.All` |
   | `m365Activity` (Teams, Outlook, Word, Excel, PowerPoint usage) | `Reports.Read.All` |
   | `agent365` | `CopilotPackages.Read.All`, `Application.Read.All`, `User.Read.All` (or skip these and use a CSV export) |
   | `productFeedback`, credit exports, `azureAi`, `agentEvaluator` | none (CSV exports, or the access in 2.3) |

4. **Grant admin consent for _your tenant_.** Every row should show a green tick. Only a Global Administrator or Privileged Role Administrator can do this; if the button is greyed out, send them the app name.
5. **Certificates & secrets > Client secrets > New client secret.** Pick an expiry (e.g. 12 months), **Add**, and copy the **Value** column right away. It is shown only once. (Not the *Secret ID*.)

## 2.2 Store the client secret

### Option 1: Azure Key Vault (recommended)

The secret stays in the vault; the notebooks fetch it each run as the person running them.

1. In the Azure portal, open your Key Vault (or create one) > **Objects > Secrets > Generate/Import**.
2. Name `universal-lake-client-secret`, Value = the secret from 2.1, set the same expiry date. **Create**.
3. **Access control (IAM) > Add role assignment > Key Vault Secrets User**, for **you** and anyone else who will run notebooks or own the schedule. (Being vault Owner isn't enough on an RBAC vault.)
4. Copy the **Vault URI** from the vault's **Overview** (`https://<name>.vault.azure.net/`) → `keyVault.uri` in `config.json`.

You need *Key Vault Secrets Officer* (or a vault admin's help) to create the secret.

### Option 2: put the secret in `config.json` (not recommended)

Use this only if you don't have a Key Vault yet, or can't get the Secrets Officer role, and want a first run working.

* Leave `keyVault.uri` as it is and paste the secret into `"clientSecret"` in `config.json`.
* The build then writes the secret **into the generated notebooks**. Anyone who can open those notebooks in the workspace can read it.

If you take this route: keep workspace access to the people who need it, don't share or export the notebooks, never commit `config.json` or `out/` (both are git-ignored), and move to Option 1 as soon as you can (set `keyVault.uri`, clear `clientSecret`, rebuild and re-import).

## 2.3 Give the app access

| Needed | What | Where | Why |
|---|---|---|---|
| **Always** | *Display concealed user, group, and site names in all reports* = **Off** | Microsoft 365 admin center > **Settings > Org settings > Reports** | Otherwise usage reports return hashed IDs instead of names, and they won't join to `orgData`. |
| Only for `azureAi` | App has **Reader**, **Cost Management Reader** and **Monitoring Reader** | Each Azure subscription > **Access control (IAM) > Add role assignment** | Reads Azure AI resources, their cost and their usage metrics. |
| Only for `agentEvaluator` | App is an application user with role **Bot Transcript Viewer** | [Power Platform admin center](https://admin.powerplatform.microsoft.com) > environment > **Settings > Users + permissions > Application users > New app user** | Reads Copilot Studio conversation transcripts from Dataverse. |

You don't need to turn on audit logging: it's on by default in Microsoft 365 tenants. You also don't need any Fabric tenant setting or workspace role for the app: the ingesters call Microsoft Graph, not Fabric, and the semantic models read the Lakehouse with your own sign-in ([step 7](../07-semantic-model/README.md#run-it)).

## 2.4 Confirm before you continue

- [ ] The app exists; its **tenant ID** and **client ID** are in `config.json`.
- [ ] Admin consent shows green ticks for every Graph permission I need.
- [ ] The secret is in Key Vault and I have *Key Vault Secrets User* **— or —** I've knowingly chosen the `config.json` bypass and have the secret value.
- [ ] Concealed names in reports are off.
- [ ] Only if used: `azureAi` has the three reader roles; `agentEvaluator` has the Dataverse application user.

`Lake_Validate_Credentials` re-checks most of this in step 4, but fixing it now is quicker. New consent can take a few minutes to reach tokens.

## Optional: do 2.1–2.3 with a script

If you have the Azure CLI and a Key Vault you can write to, `setup-app.ps1` (run from the `UniversalLake` folder) registers the app, adds and consents the permissions, stores the secret in the vault and assigns the subscription roles. It is safe to re-run; add `-WhatIf` to preview.

```powershell
az login --tenant <tenant-id>
./02-permissions/setup-app.ps1 -KeyVaultName <vault> -Modules copilotInteractions,orgData,m365Activity
```

Other parameters: `-AppName`, `-SecretName`, `-SecretYears`, `-AzureSubscriptionIds`, `-SkipConsent` (prints a consent link for an admin), `-RotateSecret`. You still do the concealed-names setting and the Dataverse application user by hand.

## When the secret expires

Create a new secret on the app (2.1 step 5), then:

* **Key Vault**: update the secret in the vault. Notebooks pick it up on the next run.
* **`config.json` bypass**: update `clientSecret`, run `npm run all`, delete and re-import the notebooks (step 4).

In both cases, then run `Lake_Deploy_Models` with `DEPLOY = False` so the models' connection gets the new secret (step 7).

Next: [Step 3: Configure](../03-configure/README.md)
