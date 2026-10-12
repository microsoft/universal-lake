# Step 2: Permissions

The notebooks sign in to Microsoft Graph (and, optionally, Azure and Dataverse) as an **app registration** with a client secret. In this step you register the app with the permissions for the data sources you chose in [Before you start](../README.md#before-you-start), store its secret, give it access to the data, and confirm with the checklist at the end.

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
   | `productFeedback`, credit exports, `azureAi`, `agentEvaluator` | none (CSV exports, or the access in 2.3 and 2.4) |

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

If you take this route: keep workspace access to the people who need it, don't share or export the notebooks, never commit `config.json` or `out/` (both are git-ignored), and move to Option 1 as soon as you can (set `keyVault.uri`, clear `clientSecret`, and run `npm run deploy`).

## 2.3 Give the app access

| Needed | What | Where | Why |
|---|---|---|---|
| **Always** | *Display concealed user, group, and site names in all reports* = **Off** | Microsoft 365 admin center > **Settings > Org settings > Reports** | Otherwise usage reports return hashed IDs instead of names, and they won't join to `orgData`. |
| Only for `azureAi` | Three read-only Azure roles for the app | See [2.4](#24-azure-ai-access-only-if-azureai-is-api) | Reads Azure AI resources, their cost and their token usage. |
| Only for `agentEvaluator` | App is an application user with role **Bot Transcript Viewer** | [Power Platform admin center](https://admin.powerplatform.microsoft.com) > environment > **Settings > Users + permissions > Application users > New app user** | Reads Copilot Studio conversation transcripts from Dataverse. |

You don't need to turn on audit logging: it's on by default in Microsoft 365 tenants.

**One Fabric admin setting**, so the semantic models refresh without anyone signing in: Fabric > **Settings > Admin portal > Tenant settings > Developer settings > *Service principals can call Fabric public APIs*** on for this app (or a security group it is in). It's on by default in tenants created since mid-2025. The models then read the Lakehouse as the app. `Lake_Setup` adds the app to the workspace and checks this setting in step 4. Without it, the notebooks fall back to your sign-in, given once for the workspace ([step 6](../06-models/README.md#62-the-semantic-models)).

## 2.4 Azure AI access (only if `azureAi` is `api`)

Skip this if you set `azureAi` to `skip`.

The `Ingest_Azure_AI` notebook signs in as the app and reads three things from one Azure subscription. Nothing is changed.

| Role to give the app | Scope | What it lets the app read |
|---|---|---|
| **Reader** | The subscription | The list of Azure AI resources (Foundry, Azure OpenAI) |
| **Cost Management Reader** | The subscription, plus every subscription in `azure.paygSubscriptions` | Daily Azure AI cost, and Copilot pay-as-you-go charges |
| **Monitoring Reader** | The subscription | Token counts per model deployment |

**Who can do it:** someone with **Owner**, **User Access Administrator** or **Role Based Access Control Administrator** on that subscription. This is usually the subscription owner or your Azure platform team.
* Microsoft Entra roles such as Global Administrator don't include this on their own.
* *Contributor* isn't enough.
* If **Add role assignment** is greyed out, you don't have the right role. Use the request text below.

**Where:** assign the roles on the **subscription**, in the Azure portal. The Azure AI Foundry portal (ai.azure.com) has no option for this. A role on a single Foundry resource also isn't enough, because cost is read for the whole subscription.

### Steps (Azure portal)

1. **Find the subscription.** Go to [portal.azure.com](https://portal.azure.com) and open any of your Azure AI or Foundry resources. On its **Overview** page, click the **Subscription** link. Copy the **Subscription ID** into `azure.subscriptionId` in `config.json`.
2. On the subscription page, select **Access control (IAM) > + Add > Add role assignment**.
3. **Role** tab: search for **Reader**, select it, then **Next**.
4. **Members** tab: leave *Assign access to* as **User, group, or service principal** and click **+ Select members**. Type the app name, `Universal Data Lake`. Apps only appear once you type their name. Select the app, then **Review + assign** twice.
5. Repeat steps 2–4 for **Cost Management Reader** and for **Monitoring Reader**.
6. Copilot pay-as-you-go may be billed to other subscriptions. If so, list them in `azure.paygSubscriptions` and give the app **Cost Management Reader** on each one.

**Check it:** on the subscription, open **Access control (IAM) > Check access** and search for the app. All three roles should be listed. New assignments can take about 10 minutes to apply. `Lake_Setup` checks again in step 4.

**If someone else must do it**, send them this:

> Please give the app registration **Universal Data Lake** (client ID `<appId>`) the **Reader**, **Cost Management Reader** and **Monitoring Reader** roles on subscription `<subscription-id>`. The roles are read-only. They let us report Azure AI cost and token usage.
>
> Azure CLI equivalent, run once for each role:
> `az role assignment create --assignee <appId> --role "Cost Management Reader" --scope /subscriptions/<subscription-id>`

## 2.5 Confirm before you continue

- [ ] The app exists; its **tenant ID** and **client ID** are in `config.json`.
- [ ] Admin consent shows green ticks for every Graph permission I need.
- [ ] The secret is in Key Vault and I have *Key Vault Secrets User* **— or —** I've knowingly chosen the `config.json` bypass and have the secret value.
- [ ] Concealed names in reports are off.
- [ ] Only if used: on the subscription, **Check access** shows the app with Reader, Cost Management Reader and Monitoring Reader (2.4); `agentEvaluator` has the Dataverse application user.

`Lake_Setup` re-checks most of this when you deploy in step 4, but fixing it now is quicker. New consent can take a few minutes to reach tokens.

## Optional: do 2.1–2.4 with a script

If you have the Azure CLI and a Key Vault you can write to, `setup-app.ps1` (run from the `UniversalLake` folder) registers the app, adds and consents the permissions, stores the secret in the vault and assigns the subscription roles. Assigning the roles needs the subscription access described in 2.4. It is safe to re-run; add `-WhatIf` to preview.

```powershell
az login --tenant <tenant-id>
./02-permissions/setup-app.ps1 -KeyVaultName <vault> -Modules copilotInteractions,orgData,m365Activity
```

Other parameters: `-AppName`, `-SecretName`, `-SecretYears`, `-AzureSubscriptionIds`, `-SkipConsent` (prints a consent link for an admin), `-RotateSecret`. You still do the concealed-names setting and the Dataverse application user by hand.

## When the secret expires

Create a new secret on the app (2.1 step 5), then:

* **Key Vault**: update the secret in the vault. Notebooks pick it up on the next run.
* **`config.json` bypass**: update `clientSecret` and run `npm run deploy` (step 4).

In both cases, the next orchestrator run gives the models' connection the new secret (its `models` step reconnects them every run).

Next: [Step 3: Configure](../03-configure/README.md)
