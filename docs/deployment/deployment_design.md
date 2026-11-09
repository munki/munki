# Deployment (deploy percent) design

**Branch:** `deployment` (off `Munki7_5dev`)

**Target:** Munki 7.5

Roll a new item out to a growing percentage of the fleet over time, instead of to every machine at once.

The core mechanism: each machine has a `deploy_percent` calculated based on its serial number. A version with a `deployment` becomes available to a machine once the machine's `deploy_percent` meets the criteria of the deployment. Until then, Munki uses the next-highest version available to it. The project plan below describes this mechanism in detail.

**A deployment only decides whether a version is available to a machine,** the same way `installable_condition` does. Once a version is available, Munki processes it as it always has, including `requires`, `update_for`, and install order. A pkginfo with no `deployment` behaves exactly as it did before this feature.

## 1. pkginfo schema

Everything lives under one `deployment` dict. The keys present decide the mode.

| Mode | Keys | Schedule |
|---|---|---|
| Start/end (default) | `start`, `end` | Grows in steps from `start` to 100% at exactly `end` (see section 2). |
| Percent per hour | `start`, `percent_per_hour` | Grows by `percent_per_hour` per weekday hour, starting at `start`. With 10, that's 10 at `start`, 20 an hour later, … 100 nine hours after `start`. |
| Percent per day | `start`, `percent_per_day` | Same as percent per hour at a rate of `percent_per_day / 24`. With 20, it reaches 100 in about 5 weekdays. |
| Percent per step | `start`, `percent_per_step`, `step_hours` | Grows by `percent_per_step` every `step_hours` weekday hours, starting at `start`. With 10 and `step_hours` 24, that's 10 at `start`, 20 a weekday later, … 100 nine weekdays after `start`. |
| Static | `percent`, optional `start` | fixed current_deploy_percent; the admin raises it by hand. With `start`, it's 0 until `start`, then `percent`. |

**`step_hours`:** how many weekday hours each step lasts. It must be an `<integer>` of 1 or more.

- **Start/end:** optional, and defaults to 1, so the value ticks up every hour. With 24, it ticks up once a day. It changes how often the value updates, not when the deployment finishes.
- **Percent per step:** required.
- **Percent per hour and percent per day:** not allowed, even with a value of 1. Those modes always step hourly, and their rate already says how fast to go. To update less often, use percent per step.
- **Static:** it has nothing to step, so the client ignores it and `makecatalogs` warns.

**The modes are mutually exclusive.** `end`, `percent_per_hour`, `percent_per_day`, `percent_per_step`, and `percent` can't be combined. A `deployment` with more than one of them is invalid, and the admin tools reject or flag it (see section 5).

**Invalid deployments fail closed.** If a `deployment` is malformed (more than one mode, no mode, a dated mode missing `start`, an `end` at or before `start` (including a schedule with no weekday time between them, see section 2), bad dates, a percent or rate outside 1–100, a `step_hours` that isn't an `<integer>` of 1 or more, a `step_hours` on percent per hour or percent per day, or a `percent_per_step` without `step_hours`), the deployment includes no machines and the client logs an error, rather than letting it go out to everyone.

### Strategies

Every dated deployment is a ramp, so rollout speed comes from the dates, rates, and `step_hours` you pick, not from extra modes.

**Two-week rollout:** 10 weekdays, about 10% per day. Each day's 10% is spread evenly across its 24 hours, so the deployment grows about 0.41% per hour, reaching 100% at the end of Friday the 23rd.

```xml
<key>deployment</key>
<dict>
    <key>start</key>
    <date>2026-10-12T00:00:00Z</date>
    <key>end</key>
    <date>2026-10-24T00:00:00Z</date>
</dict>
```

**Fast roll (one workday):** 9 steps of about 11%, 100% at 17:00.

```xml
<key>deployment</key>
<dict>
    <key>start</key>
    <date>2026-10-20T09:00:00Z</date>
    <key>end</key>
    <date>2026-10-20T17:00:00Z</date>
</dict>
```

**Overnight:** 13 steps of about 8%, done before people start work.

```xml
<key>deployment</key>
<dict>
    <key>start</key>
    <date>2026-10-20T18:00:00Z</date>
    <key>end</key>
    <date>2026-10-21T06:00:00Z</date>
</dict>
```

**Hourly rate:** 10, 20, … 100 at 18:00.

```xml
<key>deployment</key>
<dict>
    <key>start</key>
    <date>2026-10-20T09:00:00Z</date>
    <key>percent_per_hour</key>
    <integer>10</integer>
</dict>
```

**Daily batches:** 10% more each weekday, at midnight, reaching 100% on Fri 2026-10-23. Each day's group of machines gets the version together, which makes it easier to tie a problem to a batch.

```xml
<key>deployment</key>
<dict>
    <key>start</key>
    <date>2026-10-12T00:00:00Z</date>
    <key>percent_per_step</key>
    <integer>10</integer>
    <key>step_hours</key>
    <integer>24</integer>
</dict>
```

**Daily rate:** About 0.83% more per hour, 100% at Fri 2026-10-16 22:00 (rounding up gets there an hour early).

```xml
<key>deployment</key>
<dict>
    <key>start</key>
    <date>2026-10-12T00:00:00Z</date>
    <key>percent_per_day</key>
    <integer>20</integer>
</dict>
```

**Canary, then by hand:** 5% of machines until the admin raises `percent` or switches to a dated mode.

```xml
<key>deployment</key>
<dict>
    <key>percent</key>
    <integer>5</integer>
</dict>
```

**Canary on a set date:** the same, but nothing until Thu 2026-11-05, then 5%.

```xml
<key>deployment</key>
<dict>
    <key>start</key>
    <date>2026-11-05T00:00:00Z</date>
    <key>percent</key>
    <integer>5</integer>
</dict>
```

## 2. Schedule rules

- **Local Time:** dates are read the same way as `force_install_after_date` (via `subtractTZOffsetFromDate`), so `12:00:00Z` means noon local time on each machine.
- **Before start:** current_deploy_percent is 0, so the deployment includes no machines.
- **Steps:** a step opens at `start`, then every `step_hours` weekday hours on the hour, and at `end`. With N steps, step i sets current_deploy_percent to `ceil(100 × i / N)`, capped at 99 until the last step. The first machines are included right at `start`, and the deployment reaches 100% exactly at `end`, even if the last step is shorter than `step_hours`.
- **Partial hours:** a start or end that isn't on the hour is still its own step. 08:30 → 17:00 opens steps at 8:30, 9:00, … 17:00 (10 steps). With `step_hours` 2, it opens steps at 8:30, 10:00, 12:00, 14:00, 16:00, and 17:00 (6 steps).
- **`step_hours` examples:** 08:00 → 17:00 with `step_hours` 2 opens steps at 8:00, 10:00, 12:00, 14:00, 16:00, and 17:00, so current_deploy_percent runs 17, 34, 50, 67, 84, 100.
- **Rate modes:** `percent_per_hour`, `percent_per_day`, and `percent_per_step` have no `end`. Each step adds its whole amount the moment it opens: `percent_per_hour`, `percent_per_day / 24`, or `percent_per_step`. So step i sets current_deploy_percent to `min(100, ceil(i × amount))`. `percent_per_step` 20 with `step_hours` 24 gives 20, 40, 60, 80, 100 on five consecutive weekdays.
- **Rounding:** each step rounds up to the next whole number. For example, 17 steps gives 6, 12, 18, … 100.
- **Weekends:**
  - Weekend hours aren't counted. No step opens on Saturday or Sunday (except a weekend `end`, below), so current_deploy_percent holds its Friday 23:00 value until Monday 00:00.
  - A weekend start behaves like Monday 00:00.
  - A weekend end is moved back to Saturday 00:00, so the deployment finishes at the end of Friday.
  - A schedule with no weekday time between its start and end (e.g. start Saturday, end Sunday) is invalid, because after these moves its end is no longer after its start.
- **Once at 100:** current_deploy_percent stays at 100 permanently.

## 3. Machine deploy_percent

Every machine has two kinds of deploy_percent. Both are a number from 1 to 100, calculated as `hash(input) % 100 + 1`.

| | Machine deploy_percent (unsalted): `deploy_percent` | Package deploy_percent (salted): `package_deploy_percent` |
|---|---|---|
| Input | identifier only | identifier + item name |
| How many | one per machine | one per machine per item |
| Used for | the `deploy_percent` predicate fact, which is also recorded in the report's `Conditions` | deciding whether an item's `deployment` includes the machine |

- **Identifier:** the serial number, falling back to `hardware_uuid` if there's no serial. If neither can be read (and no `DeployPercentOverride` pref is set), both values are set to 100, so the machine is in the last group and gets each version once a deployment reaches 100%.
- **Hash:** the first 8 bytes of SHA-256 as a big-endian integer, so the result is stable across Munki versions. The machine value hashes the identifier, and the package value hashes `identifier:name`. This can't change once released, because that would move every machine to a different group in every running deployment.
- **Why salt per item:** each item gets a different first group of machines, so the same machines don't get every new release first. The unsalted value gives admins one stable number per machine for predicates and reporting.
- **Each item follows its own deployment:** that includes items reached through `requires` or `update_for`, hashed with their own names. A deployment on Package A says nothing about Package B. See "Required packages" in section 4.
- **`DeployPercentOverride` pref** (in ManagedInstalls): replaces both values. The machine uses the pinned number for every item, with no per-item hashing. A value outside 1–100 is ignored, with a warning. Admins can use it to decide who goes first, who goes last, or both:
  - **Go first:** a low number (e.g. 1) puts a machine at the front of every deployment, such as IT staff or testers who should catch problems early.
  - **Go last:** 100 puts a machine at the back of every deployment, such as VIPs or other sensitive machines that should only get a version once the rest of the fleet has it.
- **`managedsoftwareupdate --deploy-percent <n>`:** overrides both values for that run only, the same way `--id` overrides ClientIdentifier for one run. It takes precedence over the `DeployPercentOverride` pref, and a value outside 1–100 is rejected. It's accepted with `--checkonly` and `--installonly`, but only changes the result of a check, because `--installonly` installs what the last check found.
  - **`--deploy-percent 1`:** installs every version whose deployment has started, however low its current_deploy_percent.
  - **`--deploy-percent 100`:** skips every version whose deployment hasn't reached 100% yet.
  - **It doesn't install before a deployment's `start`.** Before start, current_deploy_percent is 0, so no value gets a machine into the deployment. That keeps the pause described in section 4 (moving `start` later) effective on every machine.
  - **It doesn't persist.** The next run, including background `--auto` runs, uses the machine's normal value again. Anything installed during the override stays installed, because a deployment doesn't remove anything. To keep a machine at the front or back permanently, use the `DeployPercentOverride` pref.
- **Which machines a deployment includes:** a deployment includes a machine when the machine's package_deploy_percent is at or below that version's current_deploy_percent. A version with no `deployment` is only subject to Munki's other checks.

## 4. Client behavior

During catalog lookup, a version whose deployment doesn't include the machine is rejected the same way a failed `installable_condition` is. Munki then falls back to the next-highest version in the catalogs that is available to the machine. Everything below follows from that.

### New installs (`managed_installs`, item not yet installed)

- **The newest version's deployment includes the machine:** the machine installs the newest version directly, the same as if it had no `deployment`. It never installs an older version first.
- **The newest version's deployment doesn't include the machine yet, an older version is available:** the machine installs the older version now. Once the deployment includes it, it sees that as a normal update.
- **The deployment doesn't include the machine yet, no older version exists** (the item's first release has a `deployment`): nothing is installed. It gets the same warnings as a failed `installable_condition` on every run, and installs once the deployment includes the machine.

### Existing installs (`managed_installs` / `managed_updates`, item already installed)

- **Installed version is the newest one available:** no update is offered until the new version's deployment includes the machine.
- **A newer version without a `deployment` is available:** e.g. 1.0 is installed, 1.1 has no `deployment`, and 1.2 is gated. The machine updates to 1.1 now and to 1.2 when its deployment includes the machine.
- **Machine already has a version whose deployment no longer includes it:** e.g. an admin pauses a deployment by moving its dates later or lowering a static `percent` after some machines already installed it. Munki's normal checks decide what happens next, the same as if the newer version had failed any other check. A newer version at the same path is seen as already installed, so nothing changes. Versions at different paths are independent installs, so an older one can be installed alongside the newer one.

### Optional installs (Managed Software Center)

- **Not installed, an older version is available:** MSC shows and offers the older version.
- **Not installed, no version is available:** the item doesn't appear in MSC until its deployment includes the machine, the same as an item whose every version fails `installable_condition`.
- **Already installed:** the update to the gated version isn't offered until its deployment includes the machine, and the installed version can still be uninstalled. After that it shows up as a normal pending update.
- **`ShowOptionalInstallsForHigherOSVersions`:** the "Requires macOS X" notice for a version the machine can't run yet doesn't appear until that version's deployment includes the machine. That lookup skips the minimum OS check, not the deployment, so it also writes a `Deployments` report entry.
- **Users can't get a gated version early:** MSC only offers versions available to the machine. To give a machine new versions sooner, an admin sets its `DeployPercentOverride` pref to a low number, e.g. 1.

### Other interactions

- **Existing conditions are checked first:** a version must pass every existing check (`minimum_munki_version`, `minimum_os_version` / `maximum_os_version`, `supported_architectures`, and `installable_condition`) before its `deployment` is evaluated. If any of them fails, the deployment is never evaluated: Munki moves on to the next-highest version, and no `Deployments` report entry is written. This lets admins stop an install with a condition unrelated to the deployment.
- **`managed_uninstalls`:** a removal by name isn't affected, since it doesn't check availability, the same as for `installable_condition`. A pinned removal and an optional uninstall look up a version like any other lookup, so if no version is available they get a warning and nothing is removed or offered.
- **`autoremove`:** not affected. It works by item name and doesn't check availability, the same as for `installable_condition`.
- **`force_install_after_date` on a gated version:** only applies once its deployment includes the machine. If the date has already passed by then, the install is forced right away.
- **Required packages:** processed the way Munki always has, using whichever versions are available to the machine, the same as for `installable_condition`:
  - If Package A says `requires Package B` and Package B 2.0's deployment doesn't include the machine, Package B 1.0 is used if it's available.
  - If no version of Package B is available, Package A gets the same warning and `Can't install` problem item as when Package B fails `installable_condition`, whether or not Package A has a `deployment`. It installs once Package B is available.
  - Each item has its own group number, so two items on the same schedule don't include the same machines. To avoid `Can't install` errors, set a `deployment` on the main item and none on the items it requires, or finish Package B's deployment before starting Package A's.
  - `update_for` items follow their own deployment.
  - Munki's existing rule for pinned requirements still applies: once any version of Package B has been processed, `requires Package B-2.0` counts as met, so the first one processed wins.

### Predicates, logging, and reporting

- **Predicates:** a `deploy_percent` fact is available in `conditional_items` and `installable_condition`. It holds the machine (unsalted) deploy_percent, or the override if one is in effect. It's added in `generatePredicateInfo()` alongside the other computed conditions (e.g. `machine_type`), so it's recorded in the report's existing `Conditions` dict and nowhere else.
- **Logging:** a version whose deployment doesn't include the machine is rejected the same way as a failed `installable_condition`:
  - When an older version is available, the fallback happens with no log line above debug level. The `Deployments` report entry shows the percents.
  - When no version is available, each run logs `Rejected item Firefox, version 131.0 with deployment: package_deploy_percent 42 > current_deploy_percent 25 (next step 2026-10-14 10:00)` and the usual "Could not process item … No pkginfo found in catalogs" warning.
  - An invalid `deployment` is also logged as an error each time it's looked up, as a predicate that raises an exception is.
- **Overrides are logged:** when the `DeployPercentOverride` pref or `--deploy-percent` is in effect, each run logs it once at info level, e.g. `deploy_percent overridden to 1 by DeployPercentOverride preference`.
- **ManagedInstallReport** gets two new top-level keys:
  - `Deployments`: one entry for every item version evaluated against a `deployment`, so admins can see the machine's package_deploy_percent for each pending deployment. An invalid `deployment` has no entry, since it has no percents to report, and logs an error instead. (The machine's unsalted `deploy_percent` is already in `Conditions`.)
  - `DeployPercentOverride`: present only when an override is in effect, so admins can tell a pinned value from a hashed one. It's a dict with `value` (integer, the pinned number) and `source` (`preference` or `command_line`). When it's present, `deploy_percent` in `Conditions` and every `package_deploy_percent` in `Deployments` equal `value`.

    | Key | Type | Meaning |
    |---|---|---|
    | `name` | string | item name |
    | `version` | string | version with the `deployment` |
    | `package_deploy_percent` | integer | this machine's salted deploy_percent for this package |
    | `current_deploy_percent` | integer | the deployment's value right now |
    | `eligible` | boolean | `package_deploy_percent` ≤ `current_deploy_percent` |
    | `next_step_date` | date | when current_deploy_percent next increases (absent for `static` deployments once started, and once at 100) |

## 5. Admin tooling

### Recommended workflow

A `deployment` applies to a version in every catalog its pkginfo is in, so it isn't scoped to one catalog. Use catalogs for testing and add the deployment at promotion:

1. Test the new version in your testing catalog with no `deployment`.
2. When promoting it to production, add the `deployment` in the same edit that adds the production catalog. This is a hand edit, since the flags below only apply when creating a pkginfo.

> **Note:** once the pkginfo has a `deployment`, a testing machine that hasn't installed the version yet (including a newly set up one) follows the production schedule too. To keep testing machines from waiting, set their `DeployPercentOverride` pref to 1 so they're in the first group of every deployment.

For a one-off run on a single machine, use `managedsoftwareupdate --deploy-percent` instead of changing the pref:

- `sudo managedsoftwareupdate --checkonly --deploy-percent 1`, then `sudo managedsoftwareupdate --installonly`, pulls in everything that's already rolling out, e.g. to confirm a fix on a specific Mac before its turn. Run the install straight after: a check at the machine's normal value in between replaces what the first check found.
- `sudo managedsoftwareupdate --checkonly --deploy-percent 100` skips anything that's still rolling out, for that run only. The next background run goes back to the machine's normal value.

### Creating a deployment: `makepkginfo` and `munkiimport`

Each flag sets one key in the pkginfo's `deployment` dict:

| Flag | Sets | Needs `--deployment-start`? |
|---|---|---|
| `--deployment-start <date>` | `start` | n/a |
| `--deployment-end <date>` | `end` (start/end mode) | yes |
| `--deployment-percent-per-hour <n>` | `percent_per_hour` | yes |
| `--deployment-percent-per-day <n>` | `percent_per_day` | yes |
| `--deployment-percent-per-step <n>` | `percent_per_step` (also needs `--deployment-step-hours`) | yes |
| `--deployment-percent <n>` | `percent` (static mode) | optional |
| `--deployment-step-hours <n>` | `step_hours` (start/end and percent per step only) | yes |

Dates use the format `yyyy-mm-ddThh:mm:ssZ`, the same as `--force_install_after_date`. Other formats are rejected, including a date alone and other time zone offsets, because pkginfo dates mean local time.

Pick one mode per pkginfo. If the flags would create an invalid `deployment` (anything listed under "Invalid" below), or use `--deployment-step-hours` with `--deployment-percent`, the tool exits with an error and doesn't write a pkginfo.

### Checking deployments: `makecatalogs`

`makecatalogs` prints a warning for each pkginfo whose `deployment` has a problem, including with `--skip-pkg-check`. It still builds the catalogs and leaves the `deployment` unchanged, so the admin sees the warning but the repo isn't blocked. The catalog rebuilds in `munkiimport` and `repoclean` still only print errors, as they always have, so these warnings don't appear there. Warnings:

- **Invalid (includes no machines):** more than one mode, no mode (e.g. only `start`), a dated mode without `start`, an end at or before the start (including a schedule with no weekday time between them), a `percent` / `percent_per_hour` / `percent_per_day` / `percent_per_step` outside 1–100, a `step_hours` that isn't an `<integer>` of 1 or more, a `step_hours` on percent per hour or percent per day, or a `percent_per_step` without `step_hours`.
- **Valid, but probably not what was meant:**
  - A start or end date on a weekend. The client moves a weekend start to Monday 00:00 and a weekend end to Saturday 00:00 (the end of Friday). An end of exactly Saturday 00:00 doesn't warn, since that's how to write the end of Friday.
  - A `step_hours` on a static `percent`. The client ignores it.

### Cleaning up: `repoclean`

Machines a deployment doesn't include yet still need older versions, so `repoclean` always keeps a version with an unfinished `deployment` (`scheduled`, `in progress`, `static` below 100, or `invalid`), and it doesn't count toward `--keep`. It then keeps the newest `--keep` versions of everything else. A finished deployment counts as a normal version, a day after it finishes to allow for time zones.

With the default of 2, versions 3.0 and 2.0 rolling out, and 1.0 and 0.9 with no `deployment`, all four are kept. A repo with no deployments is cleaned exactly as before.

### Seeing deployment status: `deploymentutil` (new tool)

Lists every pkginfo in the repo that has a `deployment`, and shows where each one is right now.

It connects to the repo the same way the other admin tools do, so it works with any repo plugin, not just repos on local disk. The repo comes from `--repo-url`, a repo path argument, or the `repo_url` admin pref, and the plugin from `--plugin` or the `plugin` admin pref (default `FileRepo`). It only reads the repo: `list("pkgsinfo")` to find pkginfos and `get("pkgsinfo/…")` to read each one, both of which every plugin implements.

```
$ deploymentutil
NAME       VERSION  MODE       START             END               STEP    CURRENT  NEXT STEP         STATUS
Firefox    131.0    start/end  2026-10-12 00:00  2026-10-24 00:00  58/241  25       2026-10-14 10:00  in progress
Zoom       6.2.1    start/end  2026-10-20 09:00  2026-10-20 17:00  -       0        2026-10-20 09:00  scheduled
Slack      4.41     static     -                 -                 -       25       -                 static
```

`CURRENT` is the deployment's current_deploy_percent. `STEP` is which step of the schedule it's on, out of the total. `MODE` is `start/end`, `per hour`, `per day`, `per step`, or `static`.

By default it only shows deployments that still need attention: `scheduled`, `in progress`, `static` (below 100), and `invalid`. Finished deployments are hidden.

| Option | Effect |
|---|---|
| `--repo-url <url>` | repo to read, overriding the `repo_url` admin pref |
| `--plugin <name>` | repo plugin to connect with, overriding the `plugin` admin pref |
| `--all` | also show finished (`complete`) deployments |
| `--catalog <name>` | only show pkginfos in that catalog |
| `--serial <serial>` | add `PACKAGE DEPLOY %` and `ELIGIBLE` columns showing where that machine falls, calculated the same way the client does. It can't see a machine's override. |
| `--schedule <name>` | print one item's full schedule, for each of its versions with a `deployment`, including finished ones: each step's time and its current_deploy_percent. Exits with an error if there's no such deployment. |
| `--json` | print JSON instead of a table |

**Status values:**

| Status | Meaning |
|---|---|
| `scheduled` | the start date hasn't arrived yet, including a `percent` deployment with a `start` |
| `in progress` | started, below 100 |
| `static` | a `percent` deployment below 100 |
| `complete` | at 100, including a `static` deployment set to 100 |
| `invalid` | the `deployment` is malformed; the reason is shown |

**Notes:**

- It reads the pkginfos, not the catalogs, so it's accurate even before `makecatalogs` has been run.
- Dates are shown on the clock of the machine running it, so around a clock change a step can differ from what a client does for about an hour.
- With a repo that needs mounting, `FileRepo` prints mount messages to stdout, which can end up in `--json` output.

## 6. Code touchpoints

| Area | File |
|---|---|
| Schedule, current_deploy_percent, and hash logic (pure functions, easy to test) | new `shared/deployment.swift` |
| Version gating, as the last check in the chain after `installableConditionOK` | `shared/updatecheck/catalogs.swift` |
| No changes to `shared/updatecheck/analyze.swift`, including `getAutoRemovalItems()` | |
| `deploy_percent` fact | `generatePredicateInfo()` in `shared/facts.swift` |
| `DeployPercentOverride` pref | `shared/prefs.swift` |
| `--deploy-percent` run-only override | `managedsoftwareupdate/msuoptions.swift` |
| Report entries (`Deployments`, `DeployPercentOverride`) | `shared/updatecheck/updatecheck.swift` |
| CLI flags | `shared/admin/pkginfoOptions.swift`, `pkginfolib.swift` |
| Validation | `deploymentWarnings()` in `shared/deployment.swift`, called from `shared/admin/makecatalogslib.swift` |
| Keeping unfinished deployments | `repoclean/repoclean.swift` |
| `deploymentutil` | new `deploymentutil/` target (Xcode project, plus an exclude in Package.swift) and `shared/admin/deploymentutillib.swift`, reusing `shared/deployment.swift` and connecting through `repoConnect(url:plugin:)` in `shared/munkirepo/RepoFactory.swift`; added to the tool lists in `code/tools/build_swift_munki.sh` and `code/tools/make_swift_munki_pkg.sh` so it ships with the admin tools |
| Unit tests | new `munkiCLItesting/deploymentTests.swift` |

## 7. Milestones

1. Schedule and hash logic, with tests covering the strategy examples, partial hours, weekends, rounding, rate modes, `step_hours`, and hash stability.
2. Client gating, including fallback.
3. `DeployPercentOverride` pref, `--deploy-percent` flag, `deploy_percent` fact, logging, and report entries.
4. `makepkginfo` / `munkiimport` flags, `makecatalogs` validation, and `repoclean`.
5. `deploymentutil`.
6. Docs and a PR to `munki/munki:Munki7_5dev`.
