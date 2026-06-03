target: qqq-dashboard

# Task
Fix TQQQ dashboard price not updating.

## Problem found by ChatGPT
The dashboard is static GitHub Pages output. `tools/robustness_dashboard.html` contains stale embedded data: `generated_at` is old and TQQQ source date/price are stale.

The workflow `.github/workflows/deploy-dashboard.yml` currently has only:

```yaml
on:
  schedule:
    - cron: '*/10 * * * *'
  workflow_dispatch:
```

It does NOT run on push, so repo commits do not automatically rebuild/deploy the dashboard. If the GitHub schedule is paused, delayed, or failing, the Pages artifact stays stale.

Also, `tools/build_dashboard.py` silently falls back to old TQQQ close when yfinance/fast_info fails, so stale prices can pass without warning.

## Required fixes

### 1. Add push trigger to workflow
Edit `.github/workflows/deploy-dashboard.yml` so it becomes:

```yaml
on:
  push:
    branches: [main]
  schedule:
    - cron: '*/10 * * * *'
  workflow_dispatch:
```

Keep all existing jobs/permissions/deploy logic unchanged.

### 2. Add stale data hard fail
In `tools/build_dashboard.py`, after `source_dates` is created, add a hard check for QQQ/TQQQ freshness.

Use logic like:

```python
today = pd.Timestamp.utcnow().normalize().tz_localize(None)
max_age_days = 5

for k in ['qqq', 'tqqq']:
    age = (today - pd.Timestamp(source_dates[k])).days
    if age > max_age_days:
        raise RuntimeError(f"{k.upper()} data stale: {source_dates[k]}, age={age} days")
```

Reason: never silently deploy a dashboard with stale TQQQ data.

### 3. Add build diagnostics
Print these during build:

```python
print('source_dates:', source_dates)
print('cur_price:', cur_price)
print('tqqq_mkt:', tqqq_mkt)
print('usd_myr:', usd_myr)
```

### 4. Run local validation
Run:

```bash
python tools/build_dashboard.py
```

Confirm:
- `tools/robustness_dashboard.html` is regenerated
- `generated_at` is current
- TQQQ source date is latest trading day
- TQQQ price is not stuck at 84.56 / 2026-05-29

### 5. Commit and push

```bash
git add .github/workflows/deploy-dashboard.yml tools/build_dashboard.py tools/robustness_dashboard.html
git commit -m "fix: rebuild dashboard on push and fail on stale TQQQ data"
git push origin main
```

### 6. Verify after push
Check GitHub Actions:
- `Update Dashboard` starts automatically from push
- build succeeds
- Pages deploy succeeds

Check live dashboard:
- `generated_at` is current
- TQQQ price/source date are current

## Report back
Return:
- commit SHA
- GitHub Actions run status
- dashboard generated_at
- TQQQ price
- TQQQ source date
