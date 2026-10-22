# Shift Sync: MLSE + Rogers Centre → Google Calendar

Your MLSE and/or Rogers Centre work shifts appear in your Google Calendar automatically, with the event name, venue and address, and they update by themselves. Free, and about 15–20 minutes to set up, once.

## Set it up

**👉 Open the setup page: https://devanshu219.github.io/shift-sync/**

It walks you through each step with direct buttons and remembers your progress.

Prefer an AI assistant to guide you? Attach [`SETUP-WITH-AI.md`](SETUP-WITH-AI.md) to ChatGPT, Claude, Gemini or Copilot and say "Follow this file and help me set it up."

## What it does

- Runs on a schedule in your own **private** copy: hourly from 10 AM to 10 PM, plus 7 AM, 9 AM, 11 PM and 3 AM (Toronto time). That stays well within GitHub's free 2,000 minutes a month.
- **MLSE:** reads your personal calendar feed for shift times, then logs in to WorkForce only when needed to add the event name, venue and role.
- **Rogers Centre:** reads ESS "View My Schedule" and adds the opponent, first-pitch time and roof status from MLB. It checks every run in baseball season, and twice a day (10 AM and 4 PM) in the off-season.
- **Safety:** it only touches events it created itself, never deletes on a failed or empty read, and never deletes past shifts. Your logins live only in your repository's encrypted GitHub secrets.
- Each run's **Summary** shows a ✅ / ❌ checklist of anything that needs fixing.

This repository is a template. Its own schedule is switched off; only your copy runs.
