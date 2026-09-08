# 📦 JobBox

A **free, private, personal** job-alert aggregator. JobBox reads the job-alert
emails in your **own Gmail (read-only)**, aggregates and **de-duplicates** the
postings, **auto-detects your application statuses** (Applied / Interview /
Rejected), and serves a clean **web dashboard** — all on your own computer.

> **Why it exists:** the real [JobBox.cc](https://jobbox.cc) (beta) missed
> alerts that landed in Gmail's **"Updates"** tab. JobBox reads **all tabs /
> categories**, so nothing is missed.

It runs entirely locally. Your email never leaves your machine, and JobBox only
ever *reads* — it can never send, delete, or modify anything.

---

## ✨ Features

| Feature | What it does |
|---|---|
| 📥 **Reads ALL Gmail tabs** | Scans Primary, Updates, Promotions, Social — the whole point. |
| 🔀 **Aggregate + de-duplicate** | Same role from LinkedIn *and* Indeed collapses into one entry. |
| 🏷️ **Auto status detection** | Classifies application emails as **Applied / Interview / Rejected**. |
| ✅ **"Did we read this right?"** | Every auto-detected status can be confirmed or hidden — like real JobBox. |
| ⚡ **Early-apply flag** | Highlights jobs posted **< 24h** ago (configurable). |
| 🎯 **CV match scoring** | Ranks jobs 0–100% by fit to *your* CV keywords. |
| 👥 **Two-inbox profiles** | Separate `parttime` and `fulltime` inboxes, each with its own senders, keywords, token, database, and dashboard. |
| 🔖 **Saved jobs tab** | Bookmark roles you want to come back to. |
| 📈 **Insights** | Applications/week chart, application funnel, response rate. |
| 🔒 **Private + read-only** | `gmail.readonly` scope only; data stored in a local SQLite file. |

---

## 🖼️ Screenshots

The dashboard is modelled on JobBox: a **Jobs** feed grouped by date, an
**Application updates** panel with status badges, a **Saved** tab, and
**Insights** charts.

```
Sidebar:  Jobs · Saved · Insights
Jobs:     "Did we read these right?" → [Applied] [Interview] [Rejected] confirmations
          Today · 5 jobs
          Deliveroo · ⚡<24h · 80% match   Snowflake Data Analyst      London   linkedin ☆
```

---

## 🚀 Quick start

### 0. Requirements
- Python 3.9+
- A Google account (for the Gmail you want to read)

### 1. Install

```bash
git clone https://github.com/<your-username>/jobbox.git
cd jobbox
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Try it with demo data (no Gmail needed)

```bash
python -m jobbox.cli demo --profile demo
python -m jobbox.cli serve --profile demo
# open http://127.0.0.1:5000
```

This seeds synthetic emails so you can see the whole dashboard immediately.

### 3. Connect your real Gmail

You need a free Google OAuth "Desktop app" client. This is a one-time setup:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or pick one) → **APIs & Services → Library** → enable
   **Gmail API**.
3. **APIs & Services → OAuth consent screen** → choose **External**, add
   yourself as a **Test user** (your Gmail address).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** →
   application type **Desktop app**.
5. **Download JSON** and save it as `secrets/credentials.json` in this project.

> The `secrets/` folder and all token/credential files are **git-ignored** — they never get committed.

### 4. Create your profiles (two inboxes)

```bash
cp config/profile.example.yaml   config/parttime.yaml
cp config/fulltime.example.yaml  config/fulltime.yaml
```

Edit each file: set the `senders`, `keywords`, `exclusions`, and your
`cv_keywords`. See [Configuration](#-configuration) below.

### 5. Sync and view

```bash
# First run per profile opens a browser once to authorise (read-only).
python -m jobbox.cli sync  --profile parttime
python -m jobbox.cli serve --profile parttime      # http://127.0.0.1:5000

# The full-time / tech inbox is completely separate:
python -m jobbox.cli sync  --profile fulltime
python -m jobbox.cli serve --profile fulltime --port 5001
```

Each profile gets its **own** token (`secrets/token_<profile>.json`) and its
**own** database (`data/jobbox_<profile>.db`), so your two Gmail accounts stay
isolated.

---

## 🛠️ CLI

```
jobbox profiles                     # list configured profiles
jobbox sync   --profile NAME [--max N]
jobbox demo   --profile NAME        # seed synthetic data, no Gmail
jobbox serve  --profile NAME [--host H] [--port P] [--debug]
```

(If you `pip install -e .`, the `jobbox` command is available directly instead
of `python -m jobbox.cli`.)

---

## ⚙️ Configuration

Each profile is a YAML file in `config/`:

```yaml
dashboard_title: "JobBox — Part-time"

credentials_file: "secrets/credentials.json"
token_file: "secrets/token_{profile}.json"   # {profile} is filled in automatically

senders:                 # which senders count as job alerts (empty = all)
  - "jobalerts-noreply@linkedin.com"
  - "noreply@indeed.com"

keywords:                # keep a job only if it matches one of these (empty = keep all)
  - "part time"
  - "weekend"

exclusions:              # drop jobs matching any of these
  - "unpaid"

cv_keywords:             # used to compute the 0–100% match score
  - "python"
  - "sql"
  - "snowflake"

lookback_days: 30        # how far back to scan Gmail
early_apply_hours: 24    # jobs newer than this get the ⚡ flag
```

---

## 🧩 How it works

```
Gmail (read-only, ALL tabs)
        │   gmail_client.py  →  EmailMessage
        ▼
   parsers.py     LinkedIn / Indeed / Glassdoor / Otta + generic fallback  →  Job[]
        ▼
   scoring.py     filter → early-apply flag → CV match score → de-duplicate
        │
        ├─ status_detect.py   application emails → Applied / Interview / Rejected
        ▼
   storage.py     SQLite (data/jobbox_<profile>.db)
        ▼
   webapp.py      Flask dashboard: Jobs / Saved / Insights
```

- **De-duplication** keys on normalised *company + title + location*, so the
  same role arriving from two sources becomes one row.
- **Status detection** is conservative and checks *Rejected → Interview →
  Applied* in priority order, then asks you to confirm ("Did we read this
  right?").

---

## 🌐 Deploying online (optional)

JobBox is designed to run locally (it holds your Gmail token), but you can host
the **dashboard** for your portfolio using the built-in demo data — no real
inbox required:

- **Any host that runs Python + Flask** (Render, Railway, Fly.io free tiers,
  or a small VPS). Use a production WSGI server, e.g.:

  ```bash
  pip install gunicorn
  # expose a WSGI app that serves the demo profile
  gunicorn "jobbox.wsgi:app"
  ```

  A ready-made `jobbox/wsgi.py` is included that serves the `demo` profile so
  recruiters can click around a live instance safely.

> ⚠️ **Never deploy with your real Gmail token.** For a public demo, seed the
> `demo` profile (`jobbox demo`) and deploy that. Keep real syncing local.

---

## 🔐 Privacy & security

- **Read-only:** JobBox requests only `gmail.readonly`.
- **Local-first:** emails are parsed on your machine; only extracted job
  fields are stored, in a local SQLite file.
- **Secrets are git-ignored:** `credentials.json`, `token_*.json`, `*.db`, and
  your personal `config/*.yaml` never get committed.

---

## 🧪 Tests

```bash
pip install pytest
pytest -q
```

Tests cover parsing, de-duplication, match scoring, early-apply logic, and
status detection — all with fixtures, so no Gmail account is needed.

---

## 📄 License

MIT — do whatever you like. Built as a personal + portfolio project.
