# Job Agent — Autonomous Job Application Bot

A fully autonomous job-application pipeline built in Python. It discovers relevant jobs across
10+ platforms, scores them with Claude AI, tailors your resume and cover letter per listing,
submits applications via browser automation, and tracks responses — all on a daily schedule.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py (Orchestrator)               │
│   --run | --schedule | --dry-run | --dashboard | --status   │
└───────────┬────────────────────────────────────────┬────────┘
            │                                        │
    ┌───────▼──────┐    ┌──────────┐    ┌───────────▼───────┐
    │ scraper_agent│───▶│ scorer   │───▶│   tailor_agent    │
    │              │    │ _agent   │    │  (resume + cover  │
    │ 10+ platforms│    │ (Claude) │    │   letter via LLM) │
    └──────────────┘    └──────────┘    └─────────┬─────────┘
                                                  │
                                        ┌─────────▼─────────┐
                                        │   apply_agent     │
                                        │ (Playwright: Easy │
                                        │  Apply / ATS /    │
                                        │  email outbox)    │
                                        └─────────┬─────────┘
                                                  │
                              ┌───────────────────▼──────────┐
                              │         SQLite DB             │
                              │  jobs | applications |        │
                              │  responses                    │
                              └───────────────┬──────────────┘
                                              │
                    ┌─────────────────────────▼────────────┐
                    │  tracker_agent  │  dashboard/app.py  │
                    │  (Gmail IMAP    │  (Streamlit :8501) │
                    │   polling)      │                    │
                    └─────────────────────────────────────┘
```

---

## Quick Start

### 1. Install dependencies

```bash
cd job-agent
pip install -r requirements.txt
playwright install chromium
```

> Optional: install `pandoc` for PDF resume generation (`sudo apt install pandoc` / `brew install pandoc`)

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in:
#   ANTHROPIC_API_KEY — get from https://console.anthropic.com
#   LINKEDIN_EMAIL / LINKEDIN_PASSWORD — your LinkedIn credentials
#   GMAIL_ADDRESS / GMAIL_APP_PASSWORD — Gmail + App Password for IMAP polling
```

### 3. Fill in your profile

- **`config.yaml`** — name, email, phone, location, job preferences, keywords
- **`profile/resume_base.md`** — your master resume in Markdown
- **`profile/preferences.yaml`** — salary, relocation, availability

### 4. Run

```bash
# One full cycle (scrape → score → apply → track)
python main.py --run

# Schedule daily at 9 AM automatically
python main.py --schedule

# Dry run — scrape and score only, no applications submitted
python main.py --dry-run

# Launch Streamlit analytics dashboard at http://localhost:8501
python main.py --dashboard

# Print today's application summary
python main.py --status
```

---

## Docker Deployment (24/7 VPS)

```bash
cp .env.example .env   # fill in credentials
docker compose up -d

# Dashboard available at http://your-vps-ip:8501
```

For auto-deploy on every `git push` to `main`, add these GitHub repository secrets:
- `VPS_HOST` — your server IP/hostname
- `VPS_USER` — SSH username (e.g. `ubuntu`)
- `VPS_SSH_KEY` — private SSH key (contents of `~/.ssh/id_rsa`)

Then every push to `main` that touches `job-agent/` will SSH into your VPS and run
`docker compose up -d --build`.

### Systemd alternative (no Docker)

```ini
# /etc/systemd/system/job-agent.service
[Unit]
Description=Job Application Agent
After=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/opt/job-agent/job-agent
ExecStart=/usr/bin/python3 main.py --schedule
Restart=always
RestartSec=30
EnvironmentFile=/opt/job-agent/job-agent/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now job-agent
sudo journalctl -u job-agent -f
```

---

## Platform Coverage

| Platform | Method | Domains |
|---|---|---|
| LinkedIn | Guest API + Easy Apply (Playwright) | All |
| Glassdoor | HTML scrape | All |
| Indeed | HTML scrape | All |
| We Work Remotely | RSS feed | All remote |
| Remote.co | HTML scrape | All remote |
| Remotive | REST API | Tech / AI |
| eFinancialCareers | HTML scrape | Quant / Finance |
| Braintrust | HTML scrape | AI / Tech |
| SelectLeaders | HTML scrape | Real Estate |
| BISNOW | HTML scrape | Real Estate |
| Wyzant | HTML scrape | Tutoring |
| Upwork | HTML scrape | Freelance |

---

## Safety & Ethics

- **Respects `robots.txt`** — LinkedIn uses only public guest endpoints; all scrapers honour
  crawl delays and avoid disallowed paths.
- **Platform ToS** — use this tool responsibly and within each platform's terms of service.
  Automated applications are permitted on many platforms; check individually.
- **Email outbox requires human review** — email-based applications are saved to `outbox/` and
  are never sent automatically. You must review and send them manually.
- **No fabrication** — the tailor agent never invents credentials, degrees, or experience.
  It only reorders and highlights what's already in `resume_base.md`.
- **Sensitive form fields** — if a form requests SSN, bank account, or passport number, the
  apply agent aborts immediately and logs the job as `requires_human`.
- **Daily limit** — `max_applications_per_day` in `config.yaml` is a hard cap. Once reached,
  the agent stops for the day.

---

## Logs & Output

| Path | Contents |
|---|---|
| `logs/run_{timestamp}.log` | Full activity log per cycle |
| `logs/daily_digest_{date}.txt` | Human-readable daily summary |
| `logs/interviews.log` | Interview requests with extracted date/time |
| `logs/screenshots/` | Confirmation page screenshots per application |
| `outbox/` | Email application drafts awaiting your review |
| `profile/variants/` | Per-job tailored resumes (MD + PDF) |
