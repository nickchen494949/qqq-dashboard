#!/usr/bin/env python3
"""
Auto-download FOMC SEP PDFs and check for signal changes.
Run via cron or manually after each FOMC meeting.

Usage:
    python3 auto_update_sep.py          # check & download new SEPs
    python3 auto_update_sep.py --cron   # install as monthly cron job
"""
import os, sys, re, subprocess
from datetime import datetime, timedelta
import requests

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP_DIR = os.path.join(PROJECT_DIR, 'fomc_sep')
sys.path.insert(0, os.path.join(PROJECT_DIR, 'tools'))

# FOMC SEP meetings are typically in March, June, September, December
# PDF URL pattern: https://www.federalreserve.gov/monetarypolicy/files/fomcprojtabl{YYYYMMDD}.pdf

def get_existing_sep_dates():
    """Get set of dates already downloaded."""
    dates = set()
    for f in os.listdir(SEP_DIR):
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', f)
        if m:
            dates.add(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return dates

def get_expected_sep_dates(start_year=2026, end_year=None):
    """Generate expected FOMC SEP meeting dates to check.
    SEP meetings are roughly: 3rd week of Mar, Jun, Sep, Dec."""
    if end_year is None:
        end_year = datetime.now().year
    
    # Known recent dates (Fed doesn't follow exact pattern)
    known = {
        2026: [(3,18), (6,17), (9,16), (12,16)],
        2027: [(3,17), (6,16), (9,22), (12,15)],
    }
    
    candidates = []
    for year in range(start_year, end_year + 1):
        if year in known:
            for month, day in known[year]:
                candidates.append(f"{year}-{month:02d}-{day:02d}")
        else:
            # Guess: 3rd Wednesday of Mar, Jun, Sep, Dec
            for month in [3, 6, 9, 12]:
                # Find 3rd Wednesday
                d = datetime(year, month, 15)
                while d.weekday() != 2:  # Wednesday
                    d += timedelta(days=1)
                candidates.append(d.strftime('%Y-%m-%d'))
    
    return candidates

def try_download_sep(date_str):
    """Try to download SEP PDF for a given date."""
    # URL format: fomcprojtabl{YYYYMMDD}.pdf
    date_compact = date_str.replace('-', '')
    url = f"https://www.federalreserve.gov/monetarypolicy/files/fomcprojtabl{date_compact}.pdf"
    
    dest = os.path.join(SEP_DIR, f"fomc_sep_{date_str}.pdf")
    if os.path.exists(dest):
        return False, "already exists"
    
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and len(r.content) > 10000:
            with open(dest, 'wb') as f:
                f.write(r.content)
            return True, f"downloaded ({len(r.content)//1024}KB)"
        else:
            return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)

def try_nearby_dates(year, month):
    """Try several nearby dates for a meeting."""
    for day in range(14, 22):  # meetings typically 14th-21st
        date_str = f"{year}-{month:02d}-{day:02d}"
        ok, msg = try_download_sep(date_str)
        if ok:
            return True, date_str, msg
    return False, None, "not found"

def check_signal():
    """Parse all SEPs and show current signal."""
    import strategy_engine as se
    sep_raw = se.parse_sep_pdfs(SEP_DIR)
    sep_signals = se.build_sep_signals(sep_raw)
    
    # Current state
    sep_in = True
    last_signal = None
    for s in sep_signals:
        if s['signal'] == 'EXIT':
            sep_in = False
            last_signal = s
        elif s['signal'] == 'ENTER':
            sep_in = True
            last_signal = s
    
    return sep_in, sep_signals, last_signal

def main():
    if '--cron' in sys.argv:
        install_cron()
        return
    
    print("=" * 60)
    print("  FOMC SEP AUTO-UPDATE")
    print("=" * 60)
    
    existing = get_existing_sep_dates()
    print(f"\n  Existing SEPs: {len(existing)}")
    print(f"  Latest: {max(existing)}")
    
    # Check for new SEPs
    now = datetime.now()
    print(f"\n  Checking for new SEPs up to {now.strftime('%Y-%m-%d')}...")
    
    new_found = []
    # Check current year
    for month in [3, 6, 9, 12]:
        target_date = datetime(now.year, month, 15)
        if target_date > now:
            continue
        # Check if we already have this quarter
        has_quarter = any(f"{now.year}-{month:02d}" in d for d in existing)
        if has_quarter:
            continue
        
        ok, date_str, msg = try_nearby_dates(now.year, month)
        if ok:
            new_found.append(date_str)
            print(f"  ✅ Downloaded: {date_str} ({msg})")
        else:
            print(f"  ⬜ {now.year}-{month:02d}: {msg}")
    
    if not new_found:
        print("  No new SEPs found.")
    
    # Parse and show signal
    print(f"\n{'─' * 60}")
    sep_in, signals, last_signal = check_signal()
    
    print(f"\n  Last 5 meetings:")
    for s in signals[-5:]:
        sig = s['signal'] or '—'
        pce = f"{s['pce']:.1f}" if s['pce'] else '?'
        rate = f"{s['rate']:.2f}" if s['rate'] else '?'
        prev_pce = f"{s['prev_pce']:.1f}" if s['prev_pce'] else '?'
        prev_rate = f"{s['prev_rate']:.2f}" if s['prev_rate'] else '?'
        print(f"    {s['date']}  PCE: {prev_pce}→{pce}  Rate: {prev_rate}→{rate}  [{sig}]")
    
    state = "✅ IN (3x leverage)" if sep_in else "🔴 OUT (0x — cash)"
    print(f"\n  ═══════════════════════════════")
    print(f"  CURRENT SEP STATE: {state}")
    print(f"  ═══════════════════════════════")
    
    if last_signal:
        print(f"  Last signal change: {last_signal['signal']} on {last_signal['date']}")

def install_cron():
    """Install cron job to run on FOMC dates."""
    script_path = os.path.abspath(__file__)
    python_path = sys.executable
    log_path = os.path.join(PROJECT_DIR, 'sep_update.log')
    
    # Run on the 15th-20th of Mar, Jun, Sep, Dec at 3pm ET (8pm UTC)
    cron_line = f"0 20 15-20 3,6,9,12 * {python_path} {script_path} >> {log_path} 2>&1"
    
    print(f"To install, add this line to your crontab (crontab -e):")
    print(f"\n  {cron_line}\n")
    print(f"Or run: (crontab -l 2>/dev/null; echo '{cron_line}') | crontab -")

if __name__ == '__main__':
    main()
