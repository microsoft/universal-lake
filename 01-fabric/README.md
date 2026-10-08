# Step 1: Fabric capacity, workspace and Lakehouse

Everything this repo builds lives in **one Fabric workspace**: one Lakehouse, about 20 notebooks and up to three semantic models. This step gets that workspace ready. You need nothing from your PC yet.

## 1.1 Pick a capacity

Notebooks and Lakehouses are Fabric items, so the workspace must run on a **Fabric capacity**. A Power BI Pro or PPU workspace on its own is not enough, and *My workspace* can't be used.

| Your situation | Capacity | Notes |
|---|---|---|
| Trying it out | **Fabric trial** (free for 60 days, equivalent to F64) | Start one from *Account manager > Start trial* in the Fabric portal. When the trial ends, move the workspace to a paid capacity or the items stop running. |
| Up to about 10k people with Copilot | **F2** or larger | F2 costs about USD 263 a month pay-as-you-go (about USD 156 reserved). A 30-day first load usually finishes in under an hour. |
| More than about 10-20k people, or a very busy audit log | **F64** or larger | Also set `scale` to `large` in step 3, which uses 2-hour audit windows and longer timeouts. A first load can take several hours. |

Things that catch people out:

* **Report viewers below F64.** On F2 to F32, anyone who opens a report on these models needs a **Power BI Pro or PPU** licence. From F64 up, viewers with a free licence can read them.
* **`TooManyRequestsForCapacity`.** Small capacities and trials throttle when many notebooks start at once. The orchestrator runs steps one after another to avoid this. If it still happens, wait a few minutes and re-run only the failed steps (see [Reruns](../08-orchestrate/RERUNS.md)).
* **Paused capacity.** A paused capacity runs nothing, including schedules. Resume it before a run.
* **Region.** The capacity's region is where your data is stored. Pick one that meets your data residency rules.

## 1.2 Create the workspace

1. In the Fabric portal, go to **Workspaces > New workspace**.
2. Give it a name, for example `Universal Data Lake`.
3. Under **Advanced > License mode**, choose **Fabric capacity** (or **Trial**) and select the capacity from 1.1.
4. Choose **Apply**.

Then, in **Workspace settings**:

| Setting | Where | Set to | Why |
|---|---|---|---|
| License | *License info* | Fabric capacity or Trial | Check it again here; notebooks won't run otherwise |
| High concurrency (optional) | *Data Engineering/Science > Spark settings > High concurrency* | **On** | Lets the notebooks you run by hand in step 5 share one Spark session instead of starting a new one each time (the orchestrator already shares its session). Needs workspace **Admin**. |
| Access | *Manage access* | You as **Admin** or **Member**; anyone else who runs notebooks as **Contributor** or above | Notebooks run as the person who starts them (or the schedule owner) |

Copy the workspace **ID** from the browser address bar: `https://app.fabric.microsoft.com/groups/<workspace-id>/...`. You'll put it into `config.json` in step 3.

## 1.3 Create the Lakehouse: tick "Lakehouse schemas"

1. In the workspace, choose **New item > Lakehouse**.
2. Name it `UniversalLake_LH` (any name works, but the docs use this one).
3. **Tick _Lakehouse schemas_.** Then choose **Create**.

> **You can't turn schemas on later.** The bronze, silver, gold and ops layers are Lakehouse schemas. If you create the Lakehouse without them, delete it and create a new one. `Lake_Init` stops with a clear error if it finds a Lakehouse without schemas.

A new Lakehouse also creates a **SQL analytics endpoint** item with the same name. The semantic models read the gold tables through it.

## 1.4 Note down three values

You need these in step 3. Keep them somewhere private (not in this repo).

| Value | Where to find it |
|---|---|
| Workspace ID | The URL: `/groups/<workspace-id>/` |
| Lakehouse ID | Open the Lakehouse; the URL ends in `/lakehouses/<lakehouse-id>` |
| SQL endpoint host | Open the **SQL analytics endpoint** item, then **Settings > SQL endpoint > SQL connection string**. Copy **only the host**, which looks like `xxxx.datawarehouse.fabric.microsoft.com`. |

## Checklist

- [ ] The workspace runs on a Fabric capacity or trial (*License info*).
- [ ] You are **Admin** or **Member** of it.
- [ ] `UniversalLake_LH` exists and its explorer shows a **`dbo`** schema (that's how you know schemas are on).
- [ ] You have the workspace ID, Lakehouse ID and SQL endpoint host.

Next: [Step 2: Permissions and app registration](../02-permissions/README.md)
