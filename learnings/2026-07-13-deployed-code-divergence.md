# Dashboard bug that was already fixed — just never deployed

## Problem
The live dashboard showed the YVR→LON one-way and return rows with the identical
fare ($413, dep 29 Aug), even though the trip-shape filter separating them existed
in the codebase and its tests passed.

## Approach
1. **Reproduce from the data, not the code.** Loaded the committed `docs/data.json`
   locally — it showed `None` for both rows, contradicting the user's screenshot.
   A contradiction between local output and observed output means *different code
   or different data is producing the live page*.
2. **Find where the thing actually runs.** Checked `.github/workflows/` — the
   runner executes in GitHub Actions on `origin/main`, not on this machine.
3. **Diff local vs deployed.** `git status` showed local `main` ahead by 2 commits;
   the unpushed commit (e4c4267) contained exactly the trip-shape filter. Root
   cause: fix written, committed, never pushed — deployed code was weeks of
   behavior behind.
4. **Rebase before push, expect semantic conflicts.** `origin/main` had merged PRs
   local never pulled. Two conflict types appeared:
   - *Textual* (runner.py): both sides wanted — keep the PR's `else: log.warning`
     AND the local `verify_queue.append` inside `if all_kept:`.
   - *Semantic* (report.py): rebase succeeded cleanly but tests failed — a PR had
     changed `build_data()["inspiration"]` from a list to a
     `{"domestic": [...], "international": [...]}` dict, and the rebased report.py
     still iterated it as a list. **A clean rebase is not a correct rebase; run the
     full suite after.**
5. **Verify on the deployed surface.** After pushing, triggered the workflow with
   `gh workflow run`, pulled the regenerated `data.json`, and read the actual row
   values. That verification exposed a second live bug (stale scan-day fallback
   showing already-departed fares), which local tests had never exercised because
   they seed only fresh data.

## Judgment calls
- Did NOT patch the symptom in the dashboard JS — the fix already existed; the
  deliverable was getting it deployed correctly.
- Did NOT force-push or skip the diverged origin commits — origin's PRs were real
  fixes (deadline pricing via month_matrix) that had to survive.
- Left the residual Aug-29 fare on the YVR one-way row alone: it's a real bookable
  fare stored by the morning's pre-fix run under the same scan-day key; it washes
  out on the next scan day rather than warranting a data migration.

## Reusable rule
When behavior contradicts code that "already fixes" it, stop reading the code and
ask **which commit is actually running where** — `git status` vs the deploy
target's ref answers it in one step. And after any rebase over diverged history,
trust only the test suite, never the absence of conflict markers.
