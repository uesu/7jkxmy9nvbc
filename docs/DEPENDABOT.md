# 🤖 Dependabot — full explanation (and how to let it update everything automatically)

> **TL;DR:** Dependabot is a **free, built-in GitHub feature** that watches your
> `requirements.txt` and your GitHub Actions and **opens pull requests** with
> safe version bumps. It **never touches `main` on its own** — every change
> waits in a PR for you to review and merge. It is **100% optional**: the
> monitor works exactly the same with it off. This repo already ships
> everything wired up (`.github/dependabot.yml` + a CI check + an opt-in
> auto-merge workflow), so enabling it costs you nothing and disabling it is
> deleting one file.

---

## 1. What is it?

Dependabot is **not** a bot you host, install, or pay for. It is a service
**built into GitHub** that runs on GitHub's own infrastructure:

1. **Scans** your repository's dependency files — here that means
   `requirements.txt` (pip) and the `uses: actions/...@v4` lines in
   `.github/workflows/*.yml` (GitHub Actions).
2. **Watches** the package registries (PyPI, the GitHub Actions marketplace)
   for new versions and published security advisories.
3. When something new (or a vulnerability fix) appears, it **opens a pull
   request** from `dependabot[bot]` with the bump — usually a **one-line diff**
   (e.g. `aiohttp>=3.9.0` → `aiohttp>=3.10.11`) plus a summary of what changed
   and links to the upstream changelog/commits.

That's the whole loop: **scan → open PR → you decide.**

## 2. Is it optional or not?

**Completely optional.** Concretely:

| Question | Answer |
|---|---|
| Does the monitor need Dependabot to run? | **No.** Zero. The cron jobs run exactly as before. |
| Does it cost money? | **No.** Free on every GitHub plan, public *and* private repos. |
| Does it need a token/API key? | **No.** It's native to GitHub. |
| Can I turn it off? | **Yes** — delete `.github/dependabot.yml` (one file) and no more update PRs appear. Security alerts can be switched off separately in Settings → Security. |
| Will it start posting to my Discord channels? | **No.** It only opens GitHub PRs. |

Think of it as a very polite roommate: it notices the milk is expiring,
leaves a note on your fridge (a PR), and waits for you to say "buy new
milk" (merge).

## 3. What exactly does it do — step by step

With the config in this repo (`.github/dependabot.yml`):

* **Every week** (schedule: `interval: weekly`), Dependabot checks:
  * **pip**: `requirements.txt` → `feedparser`, `aiohttp`, `python-dotenv`
  * **github-actions**: every workflow's `actions/checkout@v7`,
    `actions/setup-python@v7`, … (the old v4/v5 pins were auto-bumped to
    v7 by Dependabot itself — see the Node 20→24 FAQ below)
* For each outdated dependency it opens (or updates) **one PR per
  dependency**, labeled `dependencies` (+ `python` / `github-actions`),
  with a commit prefix like `deps(python): bump aiohttp from 3.9.5 to 3.10.11`.
* It also opens **security-update PRs** whenever a published vulnerability
  affects a pinned version (these are the important ones — they fix known CVEs
  before they're exploitable).
* If a PR is left open and a *newer* version lands, Dependabot **updates the
  same PR** instead of opening noise. If a PR is closed unmerged, it stops
  re-opening that exact bump.
* PRs are marked closed/replaced when the new version becomes the default.

**What it will NOT do:** run your scripts, post to Discord, change any code
other than version pins, push to `main`, merge anything, or consume your
Actions minutes for the PR itself (public repos: runs entirely free; private
repos: the check runs use your normal Actions minutes — a few seconds here).

## 4. How do I know it won't break anything? (the safety chain)

Three layers, in order:

1. **Nothing merges until you merge.** A Dependabot PR is just a branch.
   Your `main` and your live monitor are untouched until you click *Merge*
   (or auto-merge is enabled and green — see §5).
2. **CI gate (shipped in this repo — `.github/workflows/ci.yml`).** Every PR,
   including Dependabot's, runs:
   * `pip install -r requirements.txt` — a broken/renamed package fails
     **here**, before it can reach your production workflow;
   * `python -m compileall` over every script — syntax errors fail here;
   * `tests/test_smoke.py` — an offline check that all monitor scripts import
     and the card pipeline still behaves (no network, no secrets needed).
   Red check = don't merge. That's the entire review you need for a one-line
   dependency bump: **green checks + one-line diff = safe.**
3. **Revert is one click.** If a merged bump ever misbehaves (rare for these
   three stable libraries), GitHub's *Revert* button on the merge commit
   undoes it in seconds; the next Dependabot run will simply try a different
   version later.

**Extra-cautious option** (optional, matches this repo's normal update
process): after merging a bump, trigger the Reddit workflow once with
`dry_run: yes` (or a `test_post`) and skim the log — the card payloads get
logged without touching Discord. Then do one real test-channel run if you
want the full confidence. For routine patch bumps (3.9.5 → 3.9.6) the green
check is usually enough.

## 5. Making it fully automatic (PR **and** merge to main) — opt-in

Out of the box, Dependabot stops at the PR (recommended default). If you
want **automatic merge to main once checks are green**, pick ONE of:

### Option A — GitHub's built-in auto-merge (simplest)

1. Repo → **Settings → General → Pull requests** → enable **Auto-merge
   pull requests**.
2. On any green Dependabot PR, click **Enable auto-merge** → GitHub merges
   the moment checks pass (it also waits out required reviews if you have
   any). You can scope it in the same place.

### Option B — the bundled auto-merge workflow (already in the repo)

`.github/workflows/dependabot_auto_merge.yml` is included but **disabled**.
To turn it on, create **one repository variable** (not a secret — it's a
switch, not a credential):

* Repo → **Settings → Secrets and variables → Actions → Variables**
  → *New repository variable* → name **`AUTO_MERGE_DEPENDABOT`** = **`yes`**

What it then does, on every Dependabot PR:

| Gate | Check |
|---|---|
| 0 | variable `AUTO_MERGE_DEPENDABOT=yes` **and** PR author is `dependabot[bot]` (human PRs are never touched) |
| 1 | PR is not a draft and `mergeable_state` is `clean` (no conflicts) |
| 2 | **at least one check has run** (safety — never merges blind) |
| 3 | **every check is success/skipped/neutral** (the CI workflow of §4 is that check) |
| 4 | → squash-merge to `main` |

If any gate fails it logs why and does nothing. To disable again: set the
variable to anything else (or delete it).

**Why keep the check requirement?** Because "Dependabot said so" is not a
test. The CI job is cheap (~30 s) and is what actually proves the new version
still installs and compiles.

## 6. Cost & limits (the fine print)

* **Free** on all plans, public and private. No subscription, no per-PR fee.
* **Public repo:** every Dependabot feature (alerts, security updates,
  version updates, the check runs) is free and does **not** consume your
  Actions minutes.
* **Private repo:** included with your plan; the PR check runs count against
  your normal monthly Actions minutes (a few seconds — negligible here).
* **Monitoring limits:** public repos — unlimited dependencies. Private repos
  — 10 per repo on Free, 100 on Pro/Team. This repo monitors **~6
  dependencies total** (3 pip + 3 actions), so it fits any plan with room to
  grow.

## 7. Recommended review routine (60 seconds per PR)

1. Open the Dependabot PR.
2. Read the first line of the diff — should be a version number only
   (e.g. `aiohttp>=3.9.0` → `aiohttp>=3.10.11`). Anything bigger? Read the
   changelog link it provides; for a **major** version (e.g. 3.x → 4.0)
   skim the migration notes.
3. Check the **CI** tab: green ✅ (install + compile + smoke test).
4. **Merge** (or enable auto-merge per §5). Done — the next scheduled
   monitor run uses the new version automatically.

For **security-update PRs** (labeled, often marked with a vulnerability
description): treat as higher priority — review the advisory, then merge.

## 8. FAQ

* **"The 'Node.js 20 is deprecated' warning in my workflow logs is gone —
  is that because of the dependency auto-updates?"** Yes. GitHub's hosted
  runners deprecate **Node 20 as the runtime for GitHub Actions**, and older
  action versions (`actions/checkout@v4`, `actions/setup-python@v5`) still
  ran on it — which is what produced the warning line on every run.
  Dependabot opened a **github-actions** PR bumping those to **v7** (which
  run on **Node 24**), you merged it (or auto-merge did), and the warning
  disappeared. It was never a problem with *your* code or your Python
  scripts — just the runtime of the helper actions. You can verify it in
  any recent workflow log: it now downloads
  `actions/checkout@v7` / `actions/setup-python@v7` (see the 2026-09-15
  Reddit V1 run log — no deprecation warning). This is Dependabot doing
  exactly its job on the github-actions ecosystem.
* **"Will Dependabot break my `posted_reddit.json` / caches?"** No — it
  doesn't touch data files, only dependency pins.
* **"What if a bump breaks the live workflow?"** The next run logs the
  failure; hit *Revert* on the merge commit (or re-pin the old version) and
  it's back to green in one step. That's why the CI gate matters — it catches
  99% of these cases *before* they're merged.
* **"Can it update the Reddit feed scripts' *code*?"** No. Code changes are
  human work (that's what the `testing area/` process is for). Dependabot
  only manages third-party package versions.
* **"Do I get an email?"** Yes — PR notifications work like any PR. You can
  mute the `dependencies` label if it's noisy, but at weekly cadence with 6
  dependencies it's a handful of PRs a month at most.
* **"Is this the same as Dependabot alerts?"** Alerts (Security tab) just
  notify you about vulnerabilities; the PR feature here is the automated-fix
  part. Both are free; the PR part is what's configured by
  `.github/dependabot.yml`.

---

*Files involved: `.github/dependabot.yml` (the switch),
`.github/workflows/ci.yml` (the safety gate),
`.github/workflows/dependabot_auto_merge.yml` (opt-in auto-merge),
`tests/test_smoke.py` (the offline test the gate runs).*
