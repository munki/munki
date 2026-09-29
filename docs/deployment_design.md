# Deployment (deploy percent) design

**Branch:** `natewalck/deploypercent` (off `Munki7_4dev`)
**Target:** Munki 7.x

Roll a new pkginfo version out to a growing percentage of the fleet over time,
instead of to every machine at once.

## 1. pkginfo schema

Everything lives under one `deployment` dict. The keys present decide the mode.

| Mode | Keys | Schedule |
|---|---|---|
| Start/end (default) | `start`, `end` | Count the weekdays from start to end, including both. The deployment grows by an even share each weekday until it reaches 100% on the end date. With 10 weekdays, that's 10% more each day. Uneven shares round up. |
| Percent per day | `start`, `percent_per_day` | The deployment grows by `percent_per_day` each weekday until it reaches 100%. With 20, that's 20%, 40%, 60%, 80%, 100%. |
| Fastroll | `start`, `fastroll` = true | 1 → 10 → 25 → 50 → 100 over 5 weekdays |
| Static | `percent` | fixed current_deploy_percent, no dates; the admin raises it by hand |

**The modes are mutually exclusive.** `end`, `percent_per_day`, `fastroll`,
and `percent` can't be combined. A `deployment` with more than one of them is
invalid, and the admin tools reject or flag it (see section 5).

**Invalid deployments fail closed.** If a `deployment` is malformed (more than
one mode, no mode, a dated mode missing `start`, bad dates, or a percent outside
1–100), the client holds that version back on every machine and logs an error,
rather than letting it go out to everyone.

Worked examples:

- **Mon 2026-10-12 → Fri 2026-10-23:** 10 weekdays, so current_deploy_percent
  runs 10, 20, … 100.
- **Thu 2026-09-24 → Thu 2026-10-01:** 6 weekdays, so current_deploy_percent
  runs 17, 34, 50, 67, 84, 100.

### Examples

Start/end:

```xml
<key>deployment</key>
<dict>
    <key>start</key>
    <date>2026-10-12T12:00:00Z</date>
    <key>end</key>
    <date>2026-10-23T12:00:00Z</date>
</dict>
```

Percent per day:

```xml
<key>deployment</key>
<dict>
    <key>start</key>
    <date>2026-10-12T12:00:00Z</date>
    <key>percent_per_day</key>
    <integer>20</integer>
</dict>
```

Fastroll:

```xml
<key>deployment</key>
<dict>
    <key>start</key>
    <date>2026-10-12T12:00:00Z</date>
    <key>fastroll</key>
    <true/>
</dict>
```

Static:

```xml
<key>deployment</key>
<dict>
    <key>percent</key>
    <integer>25</integer>
</dict>
```

## 2. Schedule rules

- **Local Time:** dates are read the same way as
  `force_install_after_date` (via `subtractTZOffsetFromDate`), so
  `12:00:00Z` means noon local time on every machine.
- **Before start:** current_deploy_percent is 0, so no machine is eligible.
- **Day 1:** opens at the start timestamp and counts as a full day. There are
  no partial days: a noon start still gets day 1's full share for the rest of
  that day, and the schedule is never shortened or prorated to make up for it.
- **Days 2 and later:** each opens at local midnight on the next weekday.
- **Rounding:** when the days don't divide 100 evenly, each day's
  current_deploy_percent rounds up to the next whole number. For example,
  6 weekdays gives 17, 34, 50, 67, 84, 100.
- **Weekends:**
  - Saturday and Sunday are never counted as deployment days.
  - A weekend start date behaves like Monday 00:00.
  - A weekend end date is treated as the Friday before.
- **After the last step:** current_deploy_percent stays at 100 permanently.

## 3. Machine deploy_percent

Every machine has two kinds of deploy_percent. Both are a number from 1 to
100, calculated as `hash(input) % 100 + 1`.

| | Machine deploy_percent (unsalted): `deploy_percent` | Package deploy_percent (salted): `package_deploy_percent` |
|---|---|---|
| Input | identifier only | identifier + item name |
| How many | one per machine | one per machine per item |
| Used for | the `deploy_percent` predicate fact, which is also recorded in the report's `Conditions` | deciding whether the machine is eligible for an item's `deployment` |

- **Identifier:** the serial number, falling back to `hardware_uuid` if there's
  no serial. If neither can be read (and no `DeployPercent` pref is set), both
  values are set to 100, so the machine is in the last group and gets each
  version on a deployment's final day.
- **Hash:** SHA-256, so the result is stable across Munki versions.
- **Why salt per item:** each item gets a different "day 1" group of machines,
  so the same machines don't get every new release first. The unsalted value
  gives admins one stable number per machine for predicates and reporting.
- **Required packages follow the package that requires them:** when the
  machine is eligible for a gated version of Package A, the Package B version
  it requires installs even if Package B's own deployment would hold it back.
  In every other case, including an older ungated Package A or Package B
  installed on its own, Package B follows its own deployment, hashed with its
  own name.
- **`update_for` items don't follow:** the rule above only applies to
  `requires`. An `update_for` item always follows its own deployment, hashed
  with its own name.
- **`DeployPercent` pref** (in ManagedInstalls): replaces both values. The
  machine uses the pinned number for every item, with no per-item hashing.
  Admins can use it to build a canary group by hand.
- **Eligibility:** a machine is eligible for a version when its
  package_deploy_percent is at or below that version's current_deploy_percent.
  A version with no `deployment` is always eligible.

## 4. Client behavior

The core mechanism: a version the machine isn't eligible for is rejected during
catalog lookup, the same way a failed `installable_condition` is. Munki then
falls back to the next-highest version in the catalogs that the machine *is*
eligible for. Everything below follows from that.

### New installs (`managed_installs`, item not yet installed)

- **Eligible for the newest version:** the machine installs the newest version
  directly, the same as if it had no `deployment`. It never installs an older
  version first.
- **Not eligible yet, an older eligible version exists:** the machine installs
  the older version now. Once it becomes eligible for the new version, it sees
  that as a normal update.
- **Not eligible yet, no older version exists** (the item's first release has a
  `deployment`): nothing is installed. The item is logged as held back and
  installs on the day the machine becomes eligible.

### Existing installs (`managed_installs` / `managed_updates`, item already installed)

- **Installed version is the newest eligible version:** no update is offered
  until the machine becomes eligible for the new version.
- **A newer version without a `deployment` is available:** e.g. 1.0 is
  installed, 1.1 has no `deployment`, and 1.2 is gated. The machine updates to
  1.1 now and to 1.2 when eligible.
- **Machine already has a version it's no longer eligible for:** e.g. an admin
  pauses a deployment by moving its dates later or lowering a static `percent`
  after some machines already installed it. Those machines keep the version
  they have. Munki never downgrades because of a deployment.

### Optional installs (Managed Software Center)

- **Not installed, an older eligible version exists:** MSC shows and offers the
  older version.
- **Not installed, no eligible version exists:** the item doesn't appear in MSC
  until the machine becomes eligible, the same as an item whose every version
  fails `installable_condition`.
- **Already installed:** the update to the gated version isn't offered until the
  machine is eligible. After that it shows up as a normal pending update.
- **Users can't get a gated version early:** MSC only offers versions the
  machine is eligible for. To give a machine new versions sooner, an admin sets
  its `DeployPercent` pref to a low number, e.g. 1.

### Other interactions

- **`managed_uninstalls`:** not affected. Removals are never gated.
- **`force_install_after_date` on a gated version:** only applies once the
  machine is eligible. If the date has already passed by then, the install is
  forced right away.
- **Required packages:** see "Required packages follow the package that
  requires them" in section 3.

### Predicates, logging, and reporting

- **Predicates:** a `deploy_percent` fact is available in `conditional_items` and
  `installable_condition`. It holds the machine (unsalted) deploy_percent, or
  the pref if one is set. It's added in `generatePredicateInfo()` alongside the
  other computed conditions (e.g. `machine_type`), so it's recorded in the
  report's existing `Conditions` dict and nowhere else.
- **Logging:** each held-back version is logged, e.g.
  `Firefox 131.0 held back: package_deploy_percent 42 > current_deploy_percent 30 (next step 2026-10-15 00:00)`.
- **ManagedInstallReport** gets one new top-level key, `Deployments`: one entry
  for every item version evaluated against a `deployment`, so admins can see the
  machine's package_deploy_percent for each pending deployment. (The machine's
  unsalted `deploy_percent` is already in `Conditions`.)

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

- **`makepkginfo` / `munkiimport` flags:** `--deployment-start`,
  `--deployment-end`, `--deployment-percent-per-day`, `--deployment-fastroll`,
  `--deployment-percent`. Passing flags for more than one mode is an error, and
  no pkginfo is written.
- **`makecatalogs` validation** warns on:
  - more than one mode set (the client treats it as invalid)
  - no mode set (e.g. only `start`), or a dated mode missing `start`
  - end date before start date
  - a `percent` or `percent_per_day` outside 1–100
  - a weekend start or end date, which gets rolled to a weekday
- **`deploymentutil`** (new admin tool): lists every pkginfo in the
  repo that has a `deployment`, with its state calculated as of now.

  ```
  $ deploymentutil
  NAME       VERSION  MODE       START       END         DAY    CURRENT  NEXT STEP         STATUS
  Firefox    131.0    start/end  2026-10-12  2026-10-23  3/10   30       2026-10-15 00:00  in progress
  Zoom       6.2.1    fastroll   2026-10-14  2026-10-20  -      0        2026-10-14 12:00  scheduled
  Slack      4.41     static     -           -           -      25       -                 static
  ```

  | Option | Effect |
  |---|---|
  | `--all` | also list completed deployments (current_deploy_percent 100, including `static` at 100); without it, only scheduled, in-progress, static below 100, and invalid deployments are shown |
  | `--catalog <name>` | only pkginfos in that catalog |
  | `--serial <serial>` | add `PACKAGE DEPLOY %` and `ELIGIBLE` columns for that machine, using the same per-item salting as the client |
  | `--schedule <name>` | print the full day-by-day schedule (date → current_deploy_percent) for one item |
  | `--json` | machine-readable output |

  - **Status values:** `scheduled` (before start), `in progress`, `complete`
    (at 100, including `static` at 100), `static` (below 100), `invalid`
    (malformed `deployment`, with the reason).
  - **Source of truth:** reads `pkgsinfo` directly, like `repocheck`, so it
    works before `makecatalogs` has been run.
  - **Required packages:** each deployment is shown on its own schedule.
    `deploymentutil` doesn't model the required-package bypass, since that
    depends on what a given machine has installed.

## 6. Code touchpoints

| Area | File |
|---|---|
| Schedule, current_deploy_percent, and hash logic (pure functions, easy to test) | new `shared/deployment.swift` |
| Version gating, alongside `installableConditionOK` | `shared/updatecheck/catalogs.swift` |
| Letting a required package bypass its deployment when the requiring package's gated version is eligible | `shared/updatecheck/analyze.swift` |
| `deploy_percent` fact | `generatePredicateInfo()` in `shared/facts.swift` |
| `DeployPercent` pref | `shared/prefs.swift` |
| Report entries | `shared/updatecheck/updatecheck.swift` |
| CLI flags | `shared/admin/pkginfoOptions.swift`, `pkginfolib.swift` |
| Validation | `shared/admin/makecatalogslib.swift` |
| `deploymentutil` | new `deploymentutil/` target (Package.swift + Xcode project), reusing `shared/deployment.swift`; added to the tool lists in `code/tools/build_swift_munki.sh` and `code/tools/make_swift_munki_pkg.sh` so it ships with the admin tools |
| Unit tests | new `munkiCLItesting/deploymentTests.swift` |

## 7. Milestones

1. Schedule and hash logic, with tests covering both example date ranges,
   weekends, rounding, and hash stability.
2. Client gating, including fallback and the required-package bypass.
3. Pref override, `deploy_percent` fact, logging, and report entries.
4. `makepkginfo` / `munkiimport` flags and `makecatalogs` validation.
5. `deploymentutil`.
6. Docs and a PR to `munki/munki:Munki7_4dev`.
