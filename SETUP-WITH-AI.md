# MLSE + Rogers Centre Shifts → Google Calendar (automatic sync)

## 👋 Start here (for you, the person)

**What this gives you:** your work shifts appear in your Google Calendar automatically, from **MLSE** (WorkForce), **Rogers Centre** (ESS / Legends), or both. They come with the event name, the venue and a map address, for example:
- `🏒Marlies vs Hamilton, 2:30PM–7:00PM @CCC`
- `⚾Jays vs Orioles, 4:30PM @RogersCentre` (first pitch and roof open/closed in the event notes)

New shifts, changed times and cancelled shifts update by themselves, about every hour during the day.

**Cost:** $0. It runs on GitHub's free plan, and step 8 adds a safety cap so GitHub can never charge you.

**Time:** about 45–60 minutes, once.

**You need:**
1. A computer (a phone is too fiddly for setup).
2. For MLSE shifts: your MLSE WorkForce **User ID and password**.
3. For Rogers Centre shifts: your ESS **employee number and PIN**.
4. A personal Google account (an @gmail.com address works best).
5. A free GitHub account. You'll make one in step 5 if you don't have one.

**How to use this file:**
1. Open any AI assistant: ChatGPT, Claude, Gemini, Copilot, or anything similar.
2. Copy **everything in this file**, paste it into the chat, and send it. You can also attach the file and say "Follow this file and help me set it up."
3. The AI guides you one step at a time. Do each step, then reply "done", or describe what you see if something looks different.

**Your safety:** never type your MLSE password or ESS PIN, or paste your Google key file or calendar link, into the AI chat. The guide has you put those straight into GitHub's locked "secrets" storage. If the AI ever asks for them, say no.

---

# INSTRUCTIONS FOR THE AI ASSISTANT

You are setting up "Shift Sync" for a non-technical person. It is a small Python program that runs on GitHub Actions on a schedule and copies their **MLSE** and/or **Rogers Centre** work shifts into a Google Calendar. **Everything you need is in this document and in the template repository it links to.** Do not invent new code, change the schedule, or skip the safety steps. This exact code has been tested end to end against the real MLSE and Rogers Centre systems.

## How the system works (for you, the AI)

**MLSE (optional):**
- **Shift times** come from the person's private MLSE calendar feed. The sync logs in once and reads that link from MLSE WorkForce → My Calendar → Subscribe by itself, saves it privately, and looks it up again if it ever stops working.
- **Shift details** (event, venue, department, job class) come from logging in to MLSE WorkForce with a headless browser (Playwright) and reading the Schedule tab of their timesheet.
- It only logs in when an upcoming shift still needs details. A brand-new shift gets its details on the next run.

**Rogers Centre (optional):**
- Shifts come from logging in to ABI MasterMind ESS (venue ID `LEGENDSTBJ`) with the person's employee number and PIN. It reads "View My Schedule" for this month and next.
- Game days get the opponent and first-pitch time from the free MLB schedule. The roof status is added from about 12 hours before first pitch.
- ESS publishes only report times, so end times are estimated.
- **Seasons are automatic:** while the Jays have a Rogers Centre game within 45 days, ESS is checked on every run. In the off-season it's checked only at 10 AM and 4 PM, which still catches concerts and other events. Nothing needs updating each year.

**Shared:**
- **Google Calendar** is written through a Google Cloud service account that the person's calendar is shared with.
- **Personal values** live only in GitHub Actions secrets. The code files are identical for everyone.
  - MLSE: `MLSE_USER`, `MLSE_PASS` (the calendar link is found automatically; an optional `MLSE_ICS_URL` secret overrides it)
  - Rogers: `ESS_USER`, `ESS_PIN`
  - Always: `GCAL_SERVICE_KEY`, `CALENDAR_ID`
  - A source whose secrets aren't set is simply skipped.
- **Schedule (Toronto time):** hourly from 10 AM to 10 PM, plus 7 AM, 9 AM, 11 PM and 3 AM. That's up to 17 runs a day, about 1 minute each. GitHub often skips or delays some runs; that is normal.
- **Free minutes:** a private repository gets 2,000 free Actions minutes a month. This setup uses roughly 200–1,000. The `$0` budget in step 8 means GitHub stops runs instead of charging if minutes ever run out.

## Rules you must follow

1. **Never ask for, accept, or repeat secrets in the chat:** the MLSE password, the ESS PIN, the Google JSON key, the MLSE feed link, or the Calendar ID. The person types them straight into GitHub. If they paste one into the chat anyway, tell them:
   - Password or PIN: change it, then use the new one in GitHub.
   - Key file: delete that key in Google Cloud and create a new one.
   - Feed link: get a new link from MLSE if it lets them.
2. **One step at a time.** Give one short step, wait for "done" or a description of what they see, confirm it worked, then move on. Use plain words, no jargon. Say exactly what to click.
3. **The repository must be Private.** Public repositories show the run logs, including shift details, to the whole internet.
4. **Do not change** the schedule, `timeout-minutes: 8`, or any code, unless a troubleshooting row below tells you to.
5. **If a screen looks different** from these steps (websites change), ask the person to describe what they see or send a screenshot. Then guide from that. Don't guess.
6. **Check every step** using the "✅ Check" line before moving on.
7. **Be honest.** If something fails, say what failed and use the troubleshooting table. Never say it works until step 9 shows it working.
8. **Only do the parts for where they work.** MLSE only: skip step 1B and the ESS secrets. Rogers only: skip step 1A and the two MLSE secrets.

## Which way to work

- **Mode A — you can run commands and edit files** (Claude Code, Codex, Cursor, or similar), and `git` plus the GitHub CLI `gh` are installed and signed in (`gh auth status` succeeds). The repository comes from the template in step 5, and trigger and read runs with `gh workflow run` and `gh run view --log`. Steps 1–5, 7 and 8 still happen in the person's own browser, because they involve logins and secrets. For the `GCAL_SERVICE_KEY` secret only, you may run `gh secret set GCAL_SERVICE_KEY --repo OWNER/shift-sync < "PATH/TO/key.json"` without ever printing the file. Every other secret goes in through the website.
- **Mode B — chat only** (most chat apps). The person does every step in their browser and you guide them. There's no code to copy: step 5 creates their copy of the code in one click.

Start by greeting the person in one or two sentences, then ask the questions in step 0.

---

## Step 0 — Quick check

Ask the person:
1. "Do you work at MLSE, Rogers Centre, or both?" Remember the answer; it decides which steps to do (rule 8).
2. "Are you on a computer (not a phone)?"
3. "Do you have your login details handy?" That's the MLSE User ID and password, and/or the ESS employee number and PIN.
4. "Do you have a personal Google account (like an @gmail.com address)?"
5. "Do you already have a GitHub account?" If not, that's fine; step 5 makes one.

Tell them to keep a **notes app** open (Notes, Notepad, Google Keep). They'll temporarily save 2 things in it: the Calendar ID and a robot email address. Remind them not to paste any of these into this chat.

## Step 1A — Test the MLSE login (MLSE only)

1. Open https://mlse.wta-ca3.wfs.cloud/workforce/Desktop.do
2. **Type** the User ID and password by hand. Don't let the browser or a password manager fill them in, because the sync will use exactly what they type later.
3. Click **Log In**.

✅ Check: they reach the WorkForce home page. If it says "Login failed. Check password and/or user ID", they should use **Forgot Your Password?** on that page, or ask their MLSE manager, before continuing. Make sure they're on this page and not a different "SSO" sign-in page; a different login page uses different credentials.

## Step 1B — Test the Rogers Centre ESS login (Rogers only)

1. Open https://ess.abimm.com/ABIMM_ASP/Request.aspx
2. For the venue, type `LEGENDSTBJ` and submit.
3. **Type** the employee number and PIN by hand, then log in.
4. Click **View My Schedule**.

✅ Check: they see a month calendar with their shifts. Each shift shows a start time, and on game days something like `PHI (Mon - 7:00PM)`. Tell them it's fine if this month is empty in the off-season.

**For supervisors and other roles:** if their ESS has no "View My Schedule" page, or their shifts look very different, ask them to describe the screen. The sync reads exactly that page. If their shifts are on a different page, Rogers syncing may not work for them. MLSE still works, so continue, and tell them so honestly.

## Step 2 — (nothing to do)

The sync finds their MLSE calendar link by itself after logging in. Go to step 3.

## Step 3 — Make a new Google Calendar for shifts

1. Go to https://calendar.google.com
2. On the left, next to **Other calendars**, click **+** → **Create new calendar**.
3. Name it `Work Shifts` → **Create calendar**.
4. Open that calendar's settings: hover over "Work Shifts" in the left list → ⋮ → **Settings and sharing**.
5. Scroll to **Integrate calendar** and copy the **Calendar ID**. It looks like `long-letters-and-numbers@group.calendar.google.com`. Save it in the notes app as "Calendar ID".
6. Keep this settings page open. They'll come back to it in step 4.

✅ Check: the Calendar ID ends with `@group.calendar.google.com`.

Why a separate calendar: it keeps work shifts separate, and they can hide or delete it any time without touching their personal events.

## Step 4 — Create the "robot" Google account (service account)

This gives the sync permission to write to that one calendar, and nothing else.

1. Go to https://console.cloud.google.com and sign in with the **same** Google account. Accept the terms if asked. **No credit card is needed**: if it offers a free trial or billing, skip or close it.
2. At the top, click the project picker (it may say "Select a project") → **New project** → name it `shift-sync` → **Create**. Make sure the new project is selected at the top.
3. In the top search bar, type `Google Calendar API` → click it → **Enable**.
4. In the search bar, type `Service accounts` → open **Service Accounts** (under IAM & Admin) → **Create service account**.
5. Name: `calendar-sync` → **Create and continue**. Skip the optional permission steps (**Continue**, then **Done**).
6. Click the new service account's email in the list. Copy that email, which ends with `.iam.gserviceaccount.com`, into the notes app as "Robot email".
7. Open the **Keys** tab → **Add key** → **Create new key** → **JSON** → **Create**. A `.json` file downloads. This key is like a password: keep it private and never post it anywhere.
8. Go back to the calendar settings page from step 3 → **Share with specific people or groups** → **Add people and groups** → paste the robot email → set permission to **Make changes to events** → **Send**. If Google says it can't send an email to that address, that's fine.

✅ Check: the robot email appears in the calendar's sharing list with "Make changes to events", and they have a downloaded `.json` file.

If Google says **"Service account key creation is disabled"**: they're using a work or school Google account. Start step 4 again with a personal @gmail.com account. The calendar from step 3 must belong to that same account, or be shared with the robot email from it.

## Step 5 — Get their own private copy of the code (1 click)

1. Go to https://github.com. Sign up for free if needed, and verify the email.
2. Open this link: https://github.com/new?owner=@me&template_owner=devanshu219&template_name=shift-sync&name=shift-sync&visibility=private
3. Check the name is `shift-sync` and **Private** is selected. Then click **Create repository**.

✅ Check: their new repository shows `shift-sync` with a **Private** label, and contains `sync.py`, `config.py` and a `.github` folder. All the code is already there; there's nothing to copy by hand.

## Step 6 — (nothing to do)

The code came with the copy in step 5. Go straight to step 7.

## Step 7 — Add the secrets (the private values)

In the repository: **Settings** tab → left side **Secrets and variables** → **Actions** → **New repository secret**. Add each one that applies: type the **Name** exactly, put the value in **Secret**, click **Add secret**.

| Name | Who | What to put in "Secret" |
|---|---|---|
| `GCAL_SERVICE_KEY` | everyone | Open the downloaded `.json` key file in a text editor (Notepad, TextEdit), select **all** of it from the first `{` to the last `}`, copy, paste. |
| `CALENDAR_ID` | everyone | The Calendar ID from step 3. |
| `MLSE_USER` | MLSE | MLSE User ID. |
| `MLSE_PASS` | MLSE | MLSE password. **Type it by hand**, exactly as in step 1A. No autofill, and no spaces before or after. |
| `ESS_USER` | Rogers | ESS employee number. |
| `ESS_PIN` | Rogers | ESS PIN. **Type it by hand**, exactly as in step 1B. |

✅ Check: the Actions secrets list shows `GCAL_SERVICE_KEY` and `CALENDAR_ID`, plus the MLSE three and/or the Rogers two. GitHub never shows the values again, which is normal. To fix a value, click the pencil next to it and save a new one.

After this, they can delete the `.json` key file from Downloads (GitHub has a copy), and clear the notes.

## Step 8 — Safety cap: GitHub can never charge you

1. Click their profile picture (top right) → **Settings** → left side **Billing and licensing** → **Budgets and alerts**.
2. If an **Actions** budget already exists: click ⋯ → **Edit** → set **Budget amount** to `0` → tick **Stop usage when budget limit is reached** → **Update budget**.
3. If not: **New budget** → **Product-level budget** → choose **Actions** → **Next: Configure budget** → scope **Account** → amount `0` → tick **Stop usage when budget limit is reached** → **Create budget**.

✅ Check: the list shows **Actions**, **$0 budget**, **Stop usage: Yes**. This doesn't block the 2,000 free minutes; it only blocks anything paid.

## Step 9 — First runs and proof it works

**Rogers in the off-season:** Rogers is checked only at 10 AM and 4 PM between seasons. To test it right now, add one more secret, `ROGERS_FORCE_CHECK` with the value `1`. **Delete it after step 9**, so the off-season schedule takes over again.

1. In the repository, open the **Actions** tab. If GitHub asks, click **I understand my workflows, go ahead and enable them**.
2. On the left, click **Sync work shifts** → **Run workflow** (right side) → **Run workflow**.
3. Wait 2–3 minutes and refresh. A green ✓ means success; a red ✗ means look at the log.
4. To read the log: click the run → **sync** → **Run the sync**.

A good first run says something like:
```
Using calendar 'Work Shifts'.
Feed parsed: 12 shift(s) found.
MLSE feed sync: 12 created, 0 updated, 0 unchanged, 0 deleted.
No shifts need details; skipping the MLSE login.
Rogers: checking ESS (baseball season).
ESS: October 2026 -> 3 shift(s)
Rogers sync: 3 created, 0 updated, 0 unchanged, 0 deleted.
=== Done ===
```
Shifts now show in their Google Calendar. MLSE shifts first appear as **"MLSE Shift"**. Rogers shifts appear with their details straight away.

5. **MLSE only: wait at least 1 minute, then run it once more** (same buttons). This second run adds the MLSE details:
```
Adding details to 9 shift(s) via MLSE WorkForce (through 2026-11-02) ...
Added details to 9 of 9 shift(s).
```
Upcoming MLSE shifts now read like `🎵Steve Lacy, 6:30PM–11:00PM @CCC`, with the venue address. Past shifts stay as "MLSE Shift"; that's by design.

✅ Check: green ✓ runs, and shifts show in the calendar with names. If ESS showed `0 shift(s)` for both months, that's fine in the off-season; check again in season. If anything is red, use the troubleshooting table. Remind them to delete `ROGERS_FORCE_CHECK` if they added it.

## Step 10 — Finish

Tell the person, in plain words:
- It now runs by itself: about every hour 10 AM–10 PM, plus 7 AM, 9 AM, 11 PM and 3 AM. GitHub sometimes runs it late or skips one; that's fine.
- **MLSE:** a new shift shows up with its time first, and gets its details on the next run.
- **Rogers Centre:** checked every run during baseball season. Between seasons it checks at 10 AM and 4 PM, so concerts still show up the same day. It switches by itself every year, from MLB's schedule.
- **On their phone:**
  - Google Calendar app: the "Work Shifts" calendar appears automatically. If not, tick it in the app's menu.
  - iPhone Calendar app: the Google account must be added (Settings → Calendar → Accounts). If "Work Shifts" doesn't appear, open https://calendar.google.com/calendar/syncselect on a computer and tick it.
- GitHub emails them if a run fails. Most failures fix themselves on the next run. If emails keep coming, use the table below, or paste the red error text into an AI chat along with this file.
- **If they change their MLSE password or ESS PIN**, update the matching secret the same day.
- **To stop it:** Actions tab → **Sync work shifts** → ⋯ (top right) → **Disable workflow**. To remove the shifts, delete the "Work Shifts" calendar.

## Troubleshooting (find the matching message in the red log)

| What the log or email says | What it means | What to do |
|---|---|---|
| `MLSE login failed` (red note, exit code 3) | MLSE rejected the User ID or password, usually because the password changed or expired. Shift times still sync. | Do step 1A again (type it, no autofill). If that works, re-save the **same** password as `MLSE_PASS`. If they can't fix it today, **disable the workflow**, because repeated failed logins could lock the account. Re-enable it once fixed. |
| `Rogers ESS login failed` (red note, exit code 3) | ESS rejected the employee number or PIN. | Do step 1B again. If that works, re-save the same values as `ESS_USER` and `ESS_PIN`. Disable the workflow until fixed if needed. |
| `ESS: 'View My Schedule' link not found` or `Rogers/ESS failed …` every run | Their ESS looks different (some supervisor or manager accounts), or ESS changed. | Ask them to describe their ESS screen after login. If their schedule isn't on "View My Schedule", Rogers syncing can't read it: remove `ESS_USER` and `ESS_PIN` so only MLSE runs. If it happens once, ignore it. |
| `Missing GitHub secret(s): …` | A required secret is missing or misnamed. | Check the names in step 7, all uppercase, exactly as written. |
| `GCAL_SERVICE_KEY is not valid` / `not a service-account key` | The key wasn't copied completely. | Re-copy the **whole** `.json` file, from `{` to `}`, into `GCAL_SERVICE_KEY`. |
| `Cannot reach your calendar (HTTP 404)` or `(HTTP 403)` | Wrong Calendar ID, or the calendar isn't shared with the robot email. | Re-copy the Calendar ID (step 3). Re-check the sharing from step 4.8: robot email, "Make changes to events". |
| `MLSE feed failed (… 400 …)` once in a while | MLSE refuses downloads less than 30 seconds apart. The code already waits and retries. | Nothing to do. Don't click "Run workflow" twice in a row. |
| `MLSE calendar link … not found` every run | The sync couldn't find My Calendar > Subscribe for their account (some MLSE accounts look different). | Ask them to describe their MLSE My Calendar page. As a workaround, copy the link from **Subscribe** by hand and save it as an `MLSE_ICS_URL` secret; the sync then uses that instead. |
| `Rogers: off-season; next ESS check at 10 or 16:00` | Normal between baseball seasons. | Nothing to do. To force a check, add `ROGERS_FORCE_CHECK` = `1`, run, then delete it. |
| Run "cancelled" after ~15 minutes with no steps; "The job was not acquired by Runner…" | A GitHub outage, not their setup. | Check https://www.githubstatus.com. Nothing to fix; it recovers by itself. |
| A message about a budget or spending limit, and runs don't start | The free minutes for the month ran out and the $0 cap stopped the runs, so no charge happened. | Wait for the 1st of the month. To check: Settings → Billing and licensing → Usage. This setup normally uses well under half the free minutes. |
| `Could not read details from MLSE` (yellow warning) | MLSE was slow, or its pages changed. Times still synced. | If it happens once, ignore it. If every run for 2+ days, MLSE probably changed its website; ask whoever shared this file. |
| MLSE shifts stay "MLSE Shift" after 2+ successful runs | That shift isn't on the MLSE Schedule tab yet, or it's in the past. | Wait for the next runs. Past shifts never get details, by design. |
| No runs for several hours | GitHub delays scheduled runs at busy times. | Normal. They can always click **Run workflow** by hand. |
| Workflow missing from the Actions tab | `sync.yml` is in the wrong folder or has the wrong name. | It must be exactly `.github/workflows/sync.yml`. |


## Easier: the click-through setup page

If the person prefers buttons over chat, send them to https://devanshu219.github.io/shift-sync/ — the same steps with direct links and a progress checklist.
