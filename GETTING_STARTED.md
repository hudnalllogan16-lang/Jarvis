# Getting started with Jarvis

Jarvis runs small businesses for you. You open one app, it starts everything it needs, and it
asks you before doing anything that matters. This guide is the everyday version — no internals,
just how to use it.

---

## 1. What you need installed (one time)

- **Docker Desktop** — Jarvis keeps its records in services that run inside Docker. You never
  interact with them; they just need to be able to start. Install from docker.com and make sure
  the whale icon says it's running.
- **uv** — the tool that installs and runs the project. One command from astral.sh/uv installs it.
- **A model API key** — this is what lets your companies think. An Anthropic or OpenAI key works,
  or Ollama if you'd rather run a local model for free.

## 2. Set it up (one time)

In a terminal, inside the Jarvis folder:

```bash
uv sync --all-extras        # add: --extra desktop  if you want Jarvis in its own window
cp .env.example .env
```

Open `.env` in any editor and fill in two lines:

```
JARVIS_LLM__MODEL=claude-sonnet-4-5      # or another model you have access to
JARVIS_LLM__API_KEY=sk-...               # your key
```

That's the whole setup.

## 3. Start Jarvis

```bash
uv run python -m jarvis
```

What happens next, in order:

1. Jarvis checks its own health and prints a short checklist — ✓ for ready, ~ for "running
   without this for now", ✗ for "can't continue".
2. If its Docker services aren't up, it starts them itself. The very first launch downloads
   them, which can take a minute or two. After that it's seconds.
3. The dashboard opens — in its own window if you installed the desktop extra, otherwise in
   your browser at **http://localhost:8000**.

You don't need to start anything else, ever. If a part of Jarvis hiccups while running, it
restarts itself and tells you in the app.

**To stop Jarvis:** close the window (if you're using one) or press `Ctrl-C` in the terminal.

## 4. Your first company

1. Click **New company** (top right).
2. Pick a template. Right now there's one: **Affiliate publisher** — it researches topics,
   drafts posts with affiliate links, checks them against rules, and asks you before publishing.
3. Give it a name and a monthly budget, then **Create and start**.

Your company appears as a card showing:

- **Health** — a 10-segment meter. Green is fine; the line under it tells you the reason if not.
- **Spent** — what it has used of the budget you gave it. It cannot go over.
- **Doing now** — the latest thing it did, in plain words.

## 5. When Jarvis asks you something

Companies never take a real action — publishing, spending on anything — without your OK. When
one wants to act, a red-edged card appears at the top of the dashboard: what it wants to do,
how much it costs, why now, and what could go wrong.

- **Approve** — it goes ahead.
- **Say no** — it doesn't, and it takes the hint.
- **Why?** — see everything that led up to the ask.

There's no rush: if you don't answer for a day it reminds you, and if a week passes it pauses
that company rather than assuming yes. Jarvis never assumes yes.

After you approve the same kind of routine action five times in a row without changes, the
company earns the right to do *that one thing* on its own. You'll see it listed under the
company's details with an **Undo** button — one click and it's back to asking. Anything
involving real money always asks, always.

## 6. The controls you'll actually use

- **Pause / Start** on any company card — freeze or resume a company whenever you like. Paused
  companies cost nothing.
- **Details** — everything the company has done and why, newest first. If you're ever curious
  about the raw record, "Full details" at the bottom shows it — you'll never need it, but it's
  there.
- **Settings** — two things live here:
  - **What Jarvis can run** — turn whole templates on or off. Off means it disappears from
    "New company". Companies you already created aren't touched; they have their own Pause.
  - **Parts of the app** — Jarvis's own moving pieces and whether they're running. If one says
    "restarting itself", that's Jarvis handling a hiccup; you don't need to do anything.

## 7. Reading the banners

A yellow or red strip under the header is Jarvis telling you something, always with what to do:

| Banner says | What it means | What to do |
|---|---|---|
| *Companies can't act right now* | The part that runs them is still starting | Usually nothing — wait a few seconds; it connects itself |
| *Companies can't think yet* | No model key configured | Add the two lines to `.env`, restart |
| *Jarvis can't reach its database* | Docker isn't running | Start Docker Desktop, run Jarvis again |
| *Jarvis paused spending — daily limit reached* | The platform-wide daily cap was hit | Nothing spends more today; it resets tomorrow |

## 8. Honest fine print

- **This is a development build.** The Affiliate publisher is the first and currently only
  template; more arrive milestone by milestone and will show up in the same app.
- **Publishing needs somewhere to publish.** Approving a post is real, but delivering it needs
  a webhook URL for your blog and its access key in Jarvis's secrets — if you haven't set one
  up, approvals still work end to end and the delivery step will tell you what's missing.
- **First launch is the slowest** — Docker downloads its services once. Every launch after
  that is quick.

That's everything. Open it, make a company, and answer when it asks.
