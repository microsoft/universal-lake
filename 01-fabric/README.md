# Step 1: Fabric capacity, workspace and Lakehouse

Everything lives in **one Fabric workspace**: one Lakehouse, about 20 notebooks and up to three semantic models. Have `config.json` open from [Before you start](../README.md#before-you-start); you'll paste values into it at the end.

## 1.1 Pick a capacity

Notebooks need a **Fabric capacity** (F SKU) or a Fabric trial. A Pro or PPU workspace alone won't do, and *My workspace* can't be used.

| Your situation | Use | Notes |
|---|---|---|
| Trying it out | **Fabric trial** (free, 60 days, F64-sized) | Fabric portal > your account picture > **Start trial**. Move to paid capacity before it ends. |
| Up to ~10,000 people with Copilot | **F2** or larger | A 30-day first load usually takes under an hour. |
| More than ~10–20k people | **F64** or larger | Also set `scale` to `large` in `config.json`. A first load can take several hours. |

Good to know:

* **Below F64**, everyone who opens a report on these models needs Power BI Pro or PPU.
* **The capacity must be running.** A paused capacity runs nothing, including schedules.
* **The capacity's region is where the data is stored.**

## 1.2 Create the workspace

1. Fabric portal > **Workspaces > New workspace**. Name it, e.g. `Universal Data Lake`.
2. **Advanced > License mode**: **Fabric capacity** (or **Trial**), pick the capacity, **Apply**.
3. Make sure you are **Admin** or **Member** (*Manage access*). Anyone else who runs notebooks needs **Contributor** or above.

## 1.3 Create the Lakehouse, with schemas

1. In the workspace: **New item > Lakehouse**. Name it `UniversalLake_LH`.
2. **Tick _Lakehouse schemas_**, then **Create**.

> **Schemas can't be turned on later.** If you missed the box, delete the Lakehouse and create it again. You'll know it's right when the Lakehouse explorer shows a **`dbo`** folder under *Tables*.

Fabric also creates a **SQL analytics endpoint** with the same name. The semantic models read through it.

## 1.4 Copy three values from Fabric

Paste each into `config.json` as you copy it. Keep them private.

**Workspace ID and Lakehouse ID are in the browser address bar.** Open the Lakehouse and look at the URL:

```
https://app.fabric.microsoft.com/groups/<workspace-id>/lakehouses/<lakehouse-id>?experience=fabric-developer
                                        ^ workspace ID            ^ lakehouse ID
```

* **Workspace ID**: the GUID right after `/groups/` → `workspace.id`. Also put the workspace's name in `workspace.name`.
* **Lakehouse ID**: the GUID right after `/lakehouses/`, up to the `?` → `lakehouse.id`.

(Each ID looks like `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`. If the URL says `/groups/me/`, you're in *My workspace*: switch to the workspace from 1.2.)

**SQL endpoint host:**

1. In the workspace list, open the item of type **SQL analytics endpoint** named `UniversalLake_LH`.
2. **Settings** (gear) > **SQL endpoint** > copy the **SQL connection string**.
3. Keep **only the host name**, which looks like `abcd1234efgh.datawarehouse.fabric.microsoft.com`. No `https://`, no port, nothing after it. → `lakehouse.sqlEndpoint`

## Checklist

- [ ] Workspace on a Fabric capacity or trial, and you are Admin or Member.
- [ ] `UniversalLake_LH` shows a `dbo` folder (schemas are on).
- [ ] `workspace.id`, `workspace.name`, `lakehouse.id` and `lakehouse.sqlEndpoint` are filled in `config.json`.

Next: [Step 2: Permissions](../02-permissions/README.md)
