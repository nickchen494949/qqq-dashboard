# TQQQ Risk Dashboard

> A daily updated dashboard tracking the TQQQ three-layer defense system (Fed SEP, Credit, and Volatility).

🔗 **Live Dashboard**: [https://nickchen494949.github.io/qqq-dashboard/](https://nickchen494949.github.io/qqq-dashboard/)

## Strategy Documentation

The definitive rules and logic for this strategy can be found in [STRATEGY.md](STRATEGY.md).

## Technical Architecture

- **Data Sources**: Federal Reserve SEP (PDF parsing), FRED API, Yahoo Finance
- **Automation**: GitHub Actions runs daily at 14:00 UTC+8 to fetch new data and rebuild the dashboard.
- **Hosting**: GitHub Pages serves the static HTML dashboard.
- **Live Portfolio**: Client-side JavaScript fetches real-time TQQQ and USD/MYR data every 30 minutes.

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the build script manually
python3 tools/build_dashboard.py

# View the dashboard
open tools/robustness_dashboard.html
```
