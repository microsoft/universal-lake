# Stage 1: App registration

The ingesters sign in to Graph, Azure and Dataverse **as an app registration** with a client secret. The secret lives in **Key Vault**. Notebooks read it with your identity at run time, so it never appears in a notebook, in `config.json` or in this repo.

This replaces the installer's *sign in*, *register app*, *grant consent* and *store secret* steps.

## Option A: script (recommended)

`setup-app.ps1` uses the Azure CLI. It is idempotent: it reuses an app with the same name and only adds what is missing. Use `-WhatIf` to see what it would do.

```powershell
az login --tenant <tenant-id>
./01-app-registration/setup-app.ps1 -KeyVaultName <vault> `
    -Modules core,orgData,m365Activity,agent365,consumption,agentEvaluator `
    -AzureSubscriptionIds <sub-guid>       # only with consumption
```

| Parameter | Default | Meaning |
|---|---|---|
| `-KeyVaultName` | required | Existing vault. You need to write secrets to it. |
| `-AppName` | `Universal Data Lake` | Display name. An existing app with this name is reused. |
| `-SecretName` | `universal-lake-client-secret` | Key Vault secret name, the same as `keyVault.secretName` in `config.json` |
| `-Modules` | `core,orgData,m365Activity` | Adds the Graph permissions for these modules only (see [stage 0](../00-prerequisites/README.md#permissions-per-module)) |
| `-SecretYears` | `1` | Secret lifetime. The expiry date is set on the Key Vault secret too, so you can alert on it. |
| `-AzureSubscriptionIds` | none | Assigns Reader, Cost Management Reader and Monitoring Reader to the app on each subscription |
| `-SkipConsent` | off | Don't grant admin consent; print the consent URL for an admin instead |
| `-RotateSecret` | off | Make a new secret even if the vault already has one |

The script prints the values for `config.json` (`tenantId`, `appId`, `keyVault.uri`, `keyVault.secretName`) and a list of the manual follow-ups that it can't do itself:

1. Give **yourself** (and anyone who will run the notebooks) **Key Vault Secrets User** on the vault.
2. **Agent Evaluator**: in each Power Platform environment, go to *Settings > Users + permissions > Application users*. Add the app and give it the **Bot Transcript Viewer** security role.
3. If report concealment is on, turn it off (see [stage 0](../00-prerequisites/README.md#tenant-settings)).

## Option B: portal

1. **Entra admin center > App registrations > New registration.** Use single tenant and no redirect URI.
2. **API permissions > Add > Microsoft Graph > Application permissions.** Add the permissions for your modules from the [stage 0 table](../00-prerequisites/README.md#permissions-per-module), then choose **Grant admin consent**.
3. **Certificates & secrets > New client secret.** Copy the value straight into **Key Vault > Secrets > Generate/Import**, using the same name as `keyVault.secretName`, and set its expiry date.
4. Consumption: on each subscription, go to **Access control (IAM)** and give the app **Reader**, **Cost Management Reader** and **Monitoring Reader**.
5. Do the manual follow-ups listed under option A.

## Check it: `01_Validate_Credentials`

You run this notebook in Fabric after the import in [stage 3](../03-build-and-import/README.md). It needs no Lakehouse and writes nothing, so it is safe to re-run at any time. Re-run it whenever an ingester fails with 401 or 403.

Fill in its parameters cell from `config.json` (`TENANT_ID`, `CLIENT_ID`, `KEY_VAULT_URI`, `SECRET_NAME`, `MODULES`, `AZURE_SUBSCRIPTION_IDS`, `DATAVERSE_URLS`) and choose **Run all**.

| Check | Fix if it fails |
|---|---|
| Key Vault secret readable | Give yourself *Key Vault Secrets User* on the vault. |
| Graph token | Wrong tenant or app ID, or an expired secret. Run `setup-app.ps1 -RotateSecret`. |
| Graph permissions for `<module>` | Add the missing permission and grant consent. New consent can take a few minutes to appear in tokens. |
| Audit log query API | Turn on audit logging. New tenants can take 24 hours. |
| Usage reports show real user names | Turn off report concealment. |
| Copilot packages API | The tenant needs Copilot and Agent 365. Otherwise set `dataSources.agent365` to `csv`. |
| Azure subscription and cost query | Assign the roles on that subscription. |
| Dataverse application user, transcripts readable | Add the application user and the Bot Transcript Viewer role. |

With `STRICT = True` (the default) the notebook raises at the end if any required check failed. **Don't run the ingesters until it passes.**

## Rotating the secret later

```powershell
./01-app-registration/setup-app.ps1 -KeyVaultName <vault> -RotateSecret
```

The notebooks read the vault on every run, so you don't need to change anything else.

Next: [Stage 2: Lakehouse](../02-lakehouse/README.md)
