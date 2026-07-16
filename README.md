# Bharat Fincare — Loan Portfolio Executive Board

Neumorphic executive dashboard comparing two loan products at a time (month-to-date),
with a toggle between **ELI vs NBL** and **LR vs CP**. Progress vs monthly target,
required daily run-rate, top-3 credit managers, top branch, and a daily disbursement
trend line. Auto-refreshes every 5 minutes.

## Local development

```bash
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```

First paint takes ~6s (it fetches per-day disbursement for the month across both products).

## Deploy to Render

The repo is Render-ready (`render.yaml` + `Procfile` + pinned `requirements.txt`).

**Option A — Blueprint (one click):**
1. Push this folder to a GitHub repo (see below).
2. In Render: **New → Blueprint**, pick the repo. It reads `render.yaml` and creates the
   web service (`gunicorn`, health check `/healthz`, Python 3.12). Click **Apply**.

**Option B — Manual web service:**
1. Render → **New → Web Service** → connect the repo.
2. Runtime **Python 3**. Build: `pip install -r requirements.txt`.
   Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`.
3. Health check path: `/healthz`. Deploy.

Render injects `PORT`; gunicorn binds to it. No secrets or database required — the app only
reads the public product report APIs.

## Push to GitHub

```bash
cd loan-dashboard
git init
git add .
git commit -m "Loan portfolio executive dashboard"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

## Configuration

| Env var           | Default | Purpose                                   |
|-------------------|---------|-------------------------------------------|
| `PORT`            | 5000    | Bind port (Render sets this)              |
| `REQUEST_TIMEOUT` | 30      | Per-upstream-request timeout (seconds)    |
| `FLASK_DEBUG`     | off     | `1` to enable Flask debug locally         |

Auto-refresh interval is client-side: `REFRESH_MS` in `static/app.js` (default 5 min).

## Data sources & normalization

Report APIs across 4 products, two schema families merged in `providers.py`:

| | CP / LR | ELI / NBL |
|---|---|---|
| Body | JSON | `x-www-form-urlencoded` |
| Keys | camelCase, numbers | PascalCase, strings |
| Shape | `data[]` + `totals{}` | `data[]` or `data.records[]` + `summary{}` |

- **Targets** from the branch target-vs-achievement API (monthly, fixed).
- **Daily trend** built by calling the sanction API once per day (~32 calls/pair, parallel).
- **SSL:** Lending Rupee serves an incomplete cert chain (missing its GoDaddy G2
  intermediate). We bundle that intermediate in `certs/` and build a combined CA bundle
  (`certifi` roots + intermediate) at startup, so verification works with full checking
  on every OS — including Render's Linux hosts. No `verify=False` anywhere.

## Project layout

```
app.py             Flask routes (/, /api/board, /healthz)
providers.py       fetch + normalize + board aggregation + CA bundle
templates/         dashboard.html
static/            style.css, app.js, chart.min.js (vendored)
certs/             GoDaddy G2 intermediate (LR chain fix)
Procfile           gunicorn start command
render.yaml        Render blueprint
requirements.txt   pinned deps (Flask, requests, certifi, gunicorn)
```
