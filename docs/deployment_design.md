# Deployment (deploy percent) design

**Branch:** `natewalck/deploypercent` (off `Munki7_4dev`)

**Target:** Munki 7.x

Roll a new pkginfo version out to a growing percentage of the fleet over time, instead of to every machine at once.

The core mechanism: each machine has a `deploy_percent` calculated based on its serial number. A version with a `deployment` becomes available to a machine once the machine's `deploy_percent` meets the criteria of the deployment. Until then, Munki uses the next-highest version available to it. The project plan below describes this mechanism in detail.

## 1. pkginfo schema

Everything lives under one `deployment` dict. The keys present decide the mode.

| Mode | Keys | Schedule |
|---|---|---|
| Start/end (default) | `start`, `end` | Grows in steps from `start` to 100% at exactly `end` (see section 2). |
| Percent per hour | `start`, `percent_per_hour` | Grows by `percent_per_hour` per weekday hour, starting at `start`. With 10, that's 10 at `start`, 20 an hour later, … 100 nine hours after `start`. |
| Percent per day | `start`, `percent_per_day` | Same as percent per hour at a rate of `percent_per_day / 24`. With 20, it reaches 100 in about 5 weekdays. |
| Static | `percent` | fixed current_deploy_percent, no dates; the admin raises it by hand |

**`step_hours` (optional, dated modes only):** how many weekday hours each step lasts. It defaults to 1, so the value ticks up every hour. With 24, it ticks up once a day. It must be an `<integer>` of 1 or more. On a static `percent` it has nothing to step, so the client ignores it and `makecatalogs` warns. It changes how often the value updates, not how long the deployment takes.

**The modes are mutually exclusive.** `end`, `percent_per_hour`, `percent_per_day`, and `percent` can't be combined. A `deployment` with more than one of them is invalid, and the admin tools reject or flag it (see section 5).

**Invalid deployments fail closed.** If a `deployment` is malformed (more than one mode, no mode, a dated mode missing `start`, an `end` at or before `start`, bad dates, a percent or rate outside 1–100, or a `step_hours` that isn't an `<integer>` of 1 or more), the client holds that version back on every machine and logs an error, rather than letting it go out to everyone.

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
    <key>percent_per_day</key>
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

## 2. Schedule rules

- **Local Time:** dates are read the same way as `force_install_after_date` (via `subtractTZOffsetFromDate`), so `12:00:00Z` means noon local time on each machine.
- **Before start:** current_deploy_percent is 0, so no machine is eligible.
- **Steps:** a step opens at `start`, then every `step_hours` weekday hours on the hour, and at `end`. With N steps, step i sets current_deploy_percent to `ceil(100 × i / N)`. The first machines are eligible right at `start`, and the deployment reaches 100% exactly at `end`, even if the last step is shorter than `step_hours`.
- **Partial hours:** a start or end that isn't on the hour is still its own step. 08:30 → 17:00 opens steps at 8:30, 9:00, … 17:00 (10 steps). With `step_hours` 2, it opens steps at 8:30, 10:00, 12:00, 14:00, 16:00, and 17:00 (6 steps).
- **`step_hours` examples:** 08:00 → 17:00 with `step_hours` 2 opens steps at 8:00, 10:00, 12:00, 14:00, 16:00, and 17:00, so current_deploy_percent runs 17, 34, 50, 67, 84, 100.
- **Rate modes:** `percent_per_hour` and `percent_per_day` have no `end`. Each step adds `rate × step_hours`, where rate is `percent_per_hour`, or `percent_per_day / 24`, so step i sets current_deploy_percent to `min(100, ceil(i × rate × step_hours))`. `percent_per_day` 20 with `step_hours` 24 gives 20, 40, 60, 80, 100 on five consecutive weekdays.
- **Rounding:** each step rounds up to the next whole number. For example, 17 steps gives 6, 12, 18, … 100.
- **Weekends:**
  - Weekend hours aren't counted. No step opens on Saturday or Sunday (except a weekend `end`, below), so current_deploy_percent holds its Friday 23:00 value until Monday 00:00.
  - A weekend start behaves like Monday 00:00.
  - A weekend end is moved back to Saturday 00:00, so the deployment finishes at the end of Friday.
- **Once at 100:** current_deploy_percent stays at 100 permanently.

## 3. Machine deploy_percent

Every machine has two kinds of deploy_percent. Both are a number from 1 to 100, calculated as `hash(input) % 100 + 1`.

| | Machine deploy_percent (unsalted): `deploy_percent` | Package deploy_percent (salted): `package_deploy_percent` |
|---|---|---|
| Input | identifier only | identifier + item name |
| How many | one per machine | one per machine per item |
| Used for | the `deploy_percent` predicate fact, which is also recorded in the report's `Conditions` | deciding whether the machine is eligible for an item's `deployment` |

- **Identifier:** the serial number, falling back to `hardware_uuid` if there's no serial. If neither can be read (and no `DeployPercentOverride` pref is set), both values are set to 100, so the machine is in the last group and gets each version once a deployment reaches 100%.
- **Hash:** SHA-256, so the result is stable across Munki versions.
- **Why salt per item:** each item gets a different first group of machines, so the same machines don't get every new release first. The unsalted value gives admins one stable number per machine for predicates and reporting.
- **Required packages follow the package that requires them:** when the machine is eligible for a gated version of Package A, the Package B version it requires installs even if Package B's own deployment would hold it back. In every other case, including an older ungated Package A or Package B installed on its own, Package B follows its own deployment, hashed with its own name.
- **`update_for` items don't follow:** the rule above only applies to `requires`. An `update_for` item always follows its own deployment, hashed with its own name.
- **`DeployPercentOverride` pref** (in ManagedInstalls): replaces both values. The machine uses the pinned number for every item, with no per-item hashing. Admins can use it to decide who goes first, who goes last, or both:
  - **Go first:** a low number (e.g. 1) puts a machine at the front of every deployment, such as IT staff or testers who should catch problems early.
  - **Go last:** 100 puts a machine at the back of every deployment, such as VIPs or other sensitive machines that should only get a version once the rest of the fleet has it.
- **`managedsoftwareupdate --deploy-percent <n>`:** overrides both values for that run only, the same way `--id` overrides ClientIdentifier for one run. It takes precedence over the `DeployPercentOverride` pref, and a value outside 1–100 is rejected.
  - **`--deploy-percent 1`:** installs every version whose deployment has started, however low its current_deploy_percent.
  - **`--deploy-percent 100`:** skips every version whose deployment hasn't reached 100% yet.
  - **It doesn't install before a deployment's `start`.** Before start, current_deploy_percent is 0, so no value makes a machine eligible. That keeps the pause described in section 4 (moving `start` later) effective on every machine.
  - **It doesn't persist.** The next run, including background `--auto` runs, uses the machine's normal value again. Anything installed during the override stays installed, since Munki never downgrades because of a deployment. To keep a machine at the front or back permanently, use the `DeployPercentOverride` pref.
- **Eligibility:** a machine is eligible for a version when its package_deploy_percent is at or below that version's current_deploy_percent. A version with no `deployment` is always eligible, assuming there are no other conditionals applied.

## 4. Client behavior

During catalog lookup, a version the machine isn't eligible for is rejected the same way a failed `installable_condition` is. Munki then falls back to the next-highest version in the catalogs that the machine *is* eligible for. Everything below follows from that.

### New installs (`managed_installs`, item not yet installed)

- **Eligible for the newest version:** the machine installs the newest version directly, the same as if it had no `deployment`. It never installs an older version first.
- **Not eligible yet, an older eligible version exists:** the machine installs the older version now. Once it becomes eligible for the new version, it sees that as a normal update.
- **Not eligible yet, no older version exists** (the item's first release has a `deployment`): nothing is installed. The item is logged as held back and installs once the machine becomes eligible.

### Existing installs (`managed_installs` / `managed_updates`, item already installed)

- **Installed version is the newest eligible version:** no update is offered until the machine becomes eligible for the new version.
- **A newer version without a `deployment` is available:** e.g. 1.0 is installed, 1.1 has no `deployment`, and 1.2 is gated. The machine updates to 1.1 now and to 1.2 when eligible.
- **Machine already has a version it's no longer eligible for:** e.g. an admin pauses a deployment by moving its dates later or lowering a static `percent` after some machines already installed it. Those machines keep the version they have. Munki never downgrades because of a deployment.

### Optional installs (Managed Software Center)

- **Not installed, an older eligible version exists:** MSC shows and offers the older version.
- **Not installed, no eligible version exists:** the item doesn't appear in MSC until the machine becomes eligible, the same as an item whose every version fails `installable_condition`.
- **Already installed:** the update to the gated version isn't offered until the machine is eligible. After that it shows up as a normal pending update.
- **Users can't get a gated version early:** MSC only offers versions the machine is eligible for. To give a machine new versions sooner, an admin sets its `DeployPercentOverride` pref to a low number, e.g. 1.

### Other interactions

- **Existing conditions are checked first:** a version must pass every existing check (`minimum_munki_version`, `minimum_os_version` / `maximum_os_version`, `supported_architectures`, and `installable_condition`) before its `deployment` is evaluated. If any of them fails, the deployment is never evaluated: Munki moves on to the next-highest version, nothing is logged as held back, and no `Deployments` report entry is written. This lets admins stop an install with a condition unrelated to the deployment, and means a deployment hold always means "this machine could install it, it's just not its turn yet."
- **`managed_uninstalls`:** not affected. Removals are never gated.
- **`force_install_after_date` on a gated version:** only applies once the machine is eligible. If the date has already passed by then, the install is forced right away.
- **Required packages:** see "Required packages follow the package that requires them" in section 3.

### Predicates, logging, and reporting

- **Predicates:** a `deploy_percent` fact is available in `conditional_items` and `installable_condition`. It holds the machine (unsalted) deploy_percent, or the pref if one is set. It's added in `generatePredicateInfo()` alongside the other computed conditions (e.g. `machine_type`), so it's recorded in the report's existing `Conditions` dict and nowhere else.
- **Logging:** each held-back version is logged at info level, e.g. `Firefox 131.0 held back: package_deploy_percent 42 > current_deploy_percent 25 (next step 2026-10-14 10:00)`. A deployment holding a version back is the feature working as intended, so it's never logged as a warning or error:
  - When an older version is available, the fallback happens without any warning (Munki already only logs rejected versions at debug level when it finds one that works).
  - When no version is available (e.g. the item's first release is gated), the usual "Could not process item … No pkginfo found in catalogs" warning is suppressed if deployment holds are the only reason. The info-level held-back line is logged instead. If anything else also rejected a version (e.g. `minimum_os_version`), the existing warnings are logged as they are today.
  - Only an invalid `deployment` is logged as an error, since that's a real misconfiguration.
- **Overrides are logged:** when the `DeployPercentOverride` pref or `--deploy-percent` is in effect, each run logs it once at info level, e.g. `deploy_percent overridden to 1 by DeployPercentOverride preference`.
- **ManagedInstallReport** gets two new top-level keys:
  - `Deployments`: one entry for every item version evaluated against a `deployment`, so admins can see the machine's package_deploy_percent for each pending deployment. (The machine's unsalted `deploy_percent` is already in `Conditions`.)
  - `DeployPercentOverride`: present only when an override is in effect, so admins can tell a pinned value from a hashed one. It's a dict with `value` (integer, the pinned number) and `source` (`preference` or `command_line`). When it's present, `deploy_percent` in `Conditions` and every `package_deploy_percent` in `Deployments` equal `value`.

    | Key | Type | Meaning |
    |---|---|---|
    | `name` | string | item name |
    | `version` | string | version with the `deployment` |
    | `package_deploy_percent` | integer | this machine's salted deploy_percent for this package |
    | `current_deploy_percent` | integer | the deployment's value right now |
    | `eligible` | boolean | `package_deploy_percent` ≤ `current_deploy_percent`, or `true` when `required_by` is set |
    | `next_step_date` | date | when current_deploy_percent next increases (absent for `static` deployments and once at 100) |
    | `required_by` | string | name of the eligible gated package that required this one, when that let it bypass its own deployment (absent otherwise) |

## 5. Admin tooling

### Recommended workflow

A `deployment` applies to a version in every catalog its pkginfo is in, so it isn't scoped to one catalog. Use catalogs for testing and add the deployment at promotion:

1. Test the new version in your testing catalog with no `deployment`.
2. When promoting it to production, add the `deployment` in the same edit that adds the production catalog.

> **Note:** once the pkginfo has a `deployment`, a testing machine that hasn't installed the version yet (including a newly set up one) follows the production schedule too. To keep testing machines from waiting, set their `DeployPercentOverride` pref to 1 so they're in the first group of every deployment.

For a one-off run on a single machine, use `managedsoftwareupdate --deploy-percent` instead of changing the pref:

- `sudo managedsoftwareupdate --deploy-percent 1` pulls in everything that's already rolling out, e.g. to confirm a fix on a specific Mac before its turn.
- `sudo managedsoftwareupdate --deploy-percent 100` skips anything that's still rolling out, for that run only. The next background run goes back to the machine's normal value.

### Creating a deployment: `makepkginfo` and `munkiimport`

Each flag sets one key in the pkginfo's `deployment` dict:

| Flag | Sets | Needs `--deployment-start`? |
|---|---|---|
| `--deployment-start <date>` | `start` | n/a |
| `--deployment-end <date>` | `end` (start/end mode) | yes |
| `--deployment-percent-per-hour <n>` | `percent_per_hour` | yes |
| `--deployment-percent-per-day <n>` | `percent_per_day` | yes |
| `--deployment-percent <n>` | `percent` (static mode) | no |
| `--deployment-step-hours <n>` | `step_hours` (dated modes only) | yes |

Dates take a date and time, or a date alone. A date-only `--deployment-start` means 00:00 that day. A date-only `--deployment-end` means the end of that day, so `--deployment-end 2026-10-23` is written as `2026-10-24T00:00:00Z`.

Pick one mode per pkginfo. If the flags would create an invalid `deployment` (two modes, a dated mode without `--deployment-start`, or an end at or before the start), the tool exits with an error and doesn't write a pkginfo.

### Checking deployments: `makecatalogs`

`makecatalogs` prints a warning for each pkginfo whose `deployment` has a problem. It still builds the catalogs, so the admin sees the warning but the repo isn't blocked. Warnings:

- **Invalid (held back on every machine):** more than one mode, no mode (e.g. only `start`), a dated mode without `start`, an end at or before the start, a `percent` / `percent_per_hour` / `percent_per_day` outside 1–100, or a `step_hours` that isn't an `<integer>` of 1 or more.
- **Valid, but probably not what was meant:**
  - A start or end date on a weekend. The client moves a weekend start to Monday 00:00 and a weekend end to Saturday 00:00 (the end of Friday).
  - A `step_hours` on a static `percent`. The client ignores it.

### Seeing deployment status: `deploymentutil` (new tool)

Lists every pkginfo in the repo that has a `deployment`, and shows where each one is right now.

It connects to the repo the same way `makecatalogs` and `manifestutil` do, so it works with any repo plugin, not just repos on local disk. The repo comes from `--repo-url`, a repo path argument, or the `repo_url` admin pref, and the plugin from `--plugin` or the `plugin` admin pref (default `FileRepo`). It only reads the repo: `list("pkgsinfo")` to find pkginfos and `get("pkgsinfo/…")` to read each one, both of which every plugin implements.

```
$ deploymentutil
NAME       VERSION  MODE       START             END               STEP    CURRENT  NEXT STEP         STATUS
Firefox    131.0    start/end  2026-10-12 00:00  2026-10-24 00:00  58/241  25       2026-10-14 10:00  in progress
Zoom       6.2.1    start/end  2026-10-20 09:00  2026-10-20 17:00  -       0        2026-10-20 09:00  scheduled
Slack      4.41     static     -                 -                 -       25       -                 static
```

`CURRENT` is the deployment's current_deploy_percent. `STEP` is which step of the schedule it's on, out of the total.

By default it only shows deployments that still need attention: `scheduled`, `in progress`, `static` (below 100), and `invalid`. Finished deployments are hidden.

| Option | Effect |
|---|---|
| `--repo-url <url>` | repo to read, overriding the `repo_url` admin pref |
| `--plugin <name>` | repo plugin to connect with, overriding the `plugin` admin pref |
| `--all` | also show finished (`complete`) deployments |
| `--catalog <name>` | only show pkginfos in that catalog |
| `--serial <serial>` | add `PACKAGE DEPLOY %` and `ELIGIBLE` columns showing where that machine falls, calculated the same way the client does |
| `--schedule <name>` | print one item's full schedule: each step's time and its current_deploy_percent |
| `--json` | print JSON instead of a table |

**Status values:**

| Status | Meaning |
|---|---|
| `scheduled` | the start date hasn't arrived yet |
| `in progress` | started, below 100 |
| `static` | a `percent` deployment below 100 |
| `complete` | at 100, including a `static` deployment set to 100 |
| `invalid` | the `deployment` is malformed; the reason is shown |

**Notes:**

- It reads the pkginfos, not the catalogs, so it's accurate even before `makecatalogs` has been run.
- It shows each deployment on its own schedule. It doesn't show the required-package bypass from section 3, because that depends on what a particular machine has installed.

## 6. Code touchpoints

| Area | File |
|---|---|
| Schedule, current_deploy_percent, and hash logic (pure functions, easy to test) | new `shared/deployment.swift` |
| Version gating, as the last check in the chain after `installableConditionOK` | `shared/updatecheck/catalogs.swift` |
| Letting a required package bypass its deployment when the requiring package's gated version is eligible | `shared/updatecheck/analyze.swift` |
| `deploy_percent` fact | `generatePredicateInfo()` in `shared/facts.swift` |
| `DeployPercentOverride` pref | `shared/prefs.swift` |
| `--deploy-percent` run-only override | `managedsoftwareupdate/msuoptions.swift` |
| Report entries (`Deployments`, `DeployPercentOverride`) | `shared/updatecheck/updatecheck.swift` |
| CLI flags | `shared/admin/pkginfoOptions.swift`, `pkginfolib.swift` |
| Validation | `shared/admin/makecatalogslib.swift` |
| `deploymentutil` | new `deploymentutil/` target (Package.swift + Xcode project), reusing `shared/deployment.swift` and connecting through `repoConnect(url:plugin:)` in `shared/munkirepo/RepoFactory.swift`; added to the tool lists in `code/tools/build_swift_munki.sh` and `code/tools/make_swift_munki_pkg.sh` so it ships with the admin tools |
| Unit tests | new `munkiCLItesting/deploymentTests.swift` |

## 7. Milestones

1. Schedule and hash logic, with tests covering the strategy examples, partial hours, weekends, rounding, rate modes, `step_hours`, and hash stability.
2. Client gating, including fallback and the required-package bypass.
3. `DeployPercentOverride` pref, `--deploy-percent` flag, `deploy_percent` fact, logging, and report entries.
4. `makepkginfo` / `munkiimport` flags and `makecatalogs` validation.
5. `deploymentutil`.
6. Docs and a PR to `munki/munki:Munki7_4dev`.
