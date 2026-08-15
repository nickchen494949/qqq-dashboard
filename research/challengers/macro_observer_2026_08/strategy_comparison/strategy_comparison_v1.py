#!/usr/bin/env python3
"""
Hawkish Exit + EPS Re-entry: Strategy Comparison Backtest
=========================================================
Common sample: 2017-04 → 2026-07 (after EPS 26w warmup)

Strategies:
  1. Buy & Hold QQQ
  2. H→H:     Hawkish exit → Hawkish normalize re-entry
  3. H→EPS:   Hawkish exit → EPS momentum re-entry
  4. EPS→EPS:  EPS danger zone exit → EPS momentum re-entry
  5. EPS→H:   EPS danger zone exit → Hawkish normalize re-entry

Execution:
  Hawkish: signal date → publication Tuesday → trade at Tuesday close
  EPS:     weekly observation → trade next business day close (T+1)
"""

import urllib.request, csv, json, os, sys
import pandas as pd, numpy as np
from datetime import timedelta, datetime

DASHBOARD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
KW_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200533.csv"
LSEG_CSV = os.path.join(os.path.dirname(__file__), 'lseg_backtest_results_v3.csv')

# ═══════════════════════════════════════════════════════════════════
# 1. DATA LOADING
# ═══════════════════════════════════════════════════════════════════
print("=" * 90)
print("LOADING DATA")
print("=" * 90)

# --- Kim-Wright ---
req = urllib.request.Request(KW_URL, headers={'User-Agent': 'Mozilla/5.0'})
resp = urllib.request.urlopen(req, timeout=30)
raw = resp.read().decode('utf-8')
lines = raw.strip().split('\n')
header_idx = next(i for i, l in enumerate(lines) if l.startswith('Date,'))
reader = csv.DictReader(lines[header_idx:])
kw_rows = []
for row in reader:
    try:
        kw_rows.append({'date': row['Date'], 'fwd_1y': float(row['THREEFF0100.B']),
                        'tp_1y': float(row['THREEFFTP0100.B'])})
    except:
        continue
kw = pd.DataFrame(kw_rows)
kw['date'] = pd.to_datetime(kw['date'])
kw['exp_short_1y'] = kw['fwd_1y'] - kw['tp_1y']
kw = kw.sort_values('date').reset_index(drop=True)

# --- DFF ---
dff_json = os.path.join(DASHBOARD_DIR, 'data', 'fred', 'DFF.json')
with open(dff_json) as f:
    dff_data = json.load(f)
dff_raw = dff_data.get('values', dff_data) if isinstance(dff_data, dict) else dff_data
dff = pd.DataFrame(dff_raw, columns=['date', 'value'])
dff['date'] = pd.to_datetime(dff['date'])
dff['dff'] = pd.to_numeric(dff['value'], errors='coerce')
dff = dff[['date', 'dff']].dropna()

# --- Merge Hawkish signal ---
merged = pd.merge(kw[['date', 'exp_short_1y', 'fwd_1y', 'tp_1y']],
                  dff[['date', 'dff']], on='date', how='inner')
merged = merged.sort_values('date').reset_index(drop=True)
merged['hawkish_path'] = merged['exp_short_1y'] - merged['dff']
merged['delta_exp_4w'] = merged['exp_short_1y'] - merged['exp_short_1y'].shift(20)
merged['is_strong_hawk'] = (merged['hawkish_path'] > 0.5) & (merged['delta_exp_4w'] > 0.25)
print(f"  Kim-Wright + DFF: {len(merged)} days, {merged['date'].min().date()} → {merged['date'].max().date()}")

# --- LSEG EPS data ---
lseg = pd.read_csv(LSEG_CSV)
lseg['date'] = pd.to_datetime(lseg['date'])
lseg = lseg.sort_values('date').reset_index(drop=True)
print(f"  LSEG EPS: {len(lseg)} weeks, {lseg['date'].min().date()} → {lseg['date'].max().date()}")

# --- QQQ prices ---
ypath = os.path.join(DASHBOARD_DIR, 'data', 'yahoo', 'QQQ.json')
if os.path.exists(ypath):
    with open(ypath) as f:
        yd = json.load(f)
    vals = yd.get('values', yd) if isinstance(yd, dict) else yd
    qqq = pd.DataFrame(vals, columns=['date', 'close'])
    qqq['date'] = pd.to_datetime(qqq['date'])
    qqq['close'] = pd.to_numeric(qqq['close'], errors='coerce')
else:
    import yfinance as yf
    raw_df = yf.download('QQQ', start='2016-01-01', progress=False)
    qqq = raw_df[['Close']].reset_index()
    qqq.columns = ['date', 'close']
    qqq['date'] = pd.to_datetime(qqq['date']).dt.tz_localize(None)

qqq = qqq.dropna().sort_values('date').reset_index(drop=True)
qqq['daily_ret'] = qqq['close'].pct_change()
print(f"  QQQ: {len(qqq)} days, {qqq['date'].min().date()} → {qqq['date'].max().date()}")


# ═══════════════════════════════════════════════════════════════════
# 2. SIGNAL CONSTRUCTION
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*90}")
print("BUILDING SIGNALS")
print("=" * 90)

# --- Hawkish: map to publication Tuesday ---
def kw_pub_tuesday(obs_date):
    wd = obs_date.weekday()
    days_to_friday = (4 - wd) % 7
    friday = obs_date + timedelta(days=days_to_friday)
    return friday + timedelta(days=4)

def next_trading_day(date, trading_dates):
    mask = trading_dates >= date
    if mask.any():
        return trading_dates[mask][0]
    return None

qqq_dates = pd.DatetimeIndex(qqq['date'].values)

# Build daily hawkish signal with pub-date delay
# For each day, check if hawkish is strong, map to when we'd KNOW it
hawk_daily = merged[['date', 'hawkish_path', 'delta_exp_4w', 'is_strong_hawk', 'exp_short_1y']].copy()

# Create a "known" signal: on each trading day, what's the latest hawkish reading we actually have?
# Kim-Wright for day D is known on the next pub Tuesday
hawk_daily['pub_date'] = hawk_daily['date'].apply(kw_pub_tuesday)
hawk_daily['trade_date'] = hawk_daily['pub_date'].apply(lambda d: next_trading_day(d, qqq_dates))
hawk_daily = hawk_daily.dropna(subset=['trade_date'])

# Build a daily series: for each QQQ trading day, what's the latest known hawkish signal?
hawk_signal_series = {}
for _, row in hawk_daily.iterrows():
    td = row['trade_date']
    # Only update if this is newer info
    if td not in hawk_signal_series or row['date'] > hawk_signal_series[td]['obs_date']:
        hawk_signal_series[td] = {
            'obs_date': row['date'],
            'hp': row['hawkish_path'],
            'delta_exp': row['delta_exp_4w'],
            'is_strong': row['is_strong_hawk'],
        }

# Forward-fill: for each QQQ trading day, the latest known hawk state
hawk_ff = pd.DataFrame(index=qqq['date'])
hawk_ff['hawk_hp'] = np.nan
hawk_ff['hawk_strong'] = False

last_hp = np.nan
last_strong = False
for date in qqq['date']:
    if date in hawk_signal_series:
        last_hp = hawk_signal_series[date]['hp']
        last_strong = hawk_signal_series[date]['is_strong']
    hawk_ff.loc[date, 'hawk_hp'] = last_hp
    hawk_ff.loc[date, 'hawk_strong'] = last_strong

print(f"  Hawkish signal: {hawk_ff['hawk_strong'].sum()} days with strong-hawk (pub-date delayed)")

# --- EPS: forward-fill weekly to daily ---
eps_ff = pd.DataFrame(index=qqq['date'])
eps_ff['eps_mom_26w'] = np.nan
eps_ff['forward_pe'] = np.nan
eps_ff['eps_danger'] = False  # exit signal
eps_ff['eps_reentry'] = False  # re-entry signal

# Map each LSEG observation to T+1 business day
for _, row in lseg.iterrows():
    obs_date = row['date']
    # T+1 execution: next trading day after observation
    trade_date = next_trading_day(obs_date + timedelta(days=1), qqq_dates)
    if trade_date is None:
        trade_date = next_trading_day(obs_date, qqq_dates)
    if trade_date is None:
        continue

    mom26 = row.get('eps_mom_26w')
    fpe = row.get('forward_pe')
    if pd.notna(mom26):
        eps_ff.loc[trade_date, 'eps_mom_26w'] = mom26
        eps_ff.loc[trade_date, 'forward_pe'] = fpe if pd.notna(fpe) else np.nan

# Forward-fill
eps_ff['eps_mom_26w'] = eps_ff['eps_mom_26w'].ffill()
eps_ff['forward_pe'] = eps_ff['forward_pe'].ffill()

# EPS exit: Mom_26w > +8% AND PE > 20x
eps_ff['eps_danger'] = (eps_ff['eps_mom_26w'] > 8.0) & (eps_ff['forward_pe'] > 20.0)
# EPS re-entry: Mom_26w < -5%
eps_ff['eps_reentry_signal'] = eps_ff['eps_mom_26w'] < -5.0
# Simpler alternative: Mom_26w < -3% (broader)
eps_ff['eps_reentry_3pct'] = eps_ff['eps_mom_26w'] < -3.0

n_danger = eps_ff['eps_danger'].sum()
n_reentry = eps_ff['eps_reentry_signal'].sum()
print(f"  EPS danger zone days: {n_danger}")
print(f"  EPS re-entry days (mom < -5%): {n_reentry}")
print(f"  EPS re-entry days (mom < -3%): {eps_ff['eps_reentry_3pct'].sum()}")


# ═══════════════════════════════════════════════════════════════════
# 3. COMMON SAMPLE
# ═══════════════════════════════════════════════════════════════════

# First valid EPS mom_26w date
first_eps = eps_ff[eps_ff['eps_mom_26w'].notna()].index.min()
# Use the later of first_eps and 2017-01-01
SAMPLE_START = max(first_eps, pd.Timestamp('2017-01-01'))
SAMPLE_END = qqq['date'].max()

mask = (qqq['date'] >= SAMPLE_START) & (qqq['date'] <= SAMPLE_END)
qqq_sample = qqq[mask].copy().reset_index(drop=True)
print(f"\n  Common sample: {SAMPLE_START.date()} → {SAMPLE_END.date()}")
print(f"  Trading days: {len(qqq_sample)}")


# ═══════════════════════════════════════════════════════════════════
# 4. STRATEGY ENGINE
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*90}")
print("RUNNING STRATEGIES")
print("=" * 90)

def run_strategy(name, qqq_df, hawk_signals, eps_signals, exit_fn, entry_fn):
    """
    State machine: IN_MARKET or OUT_OF_MARKET.
    Returns equity curve and trade log.
    """
    equity = 1.0
    state = 'IN'  # start in market
    trade_log = []
    equity_curve = []
    current_trade = None

    for i, row in qqq_df.iterrows():
        date = row['date']
        daily_ret = row['daily_ret'] if pd.notna(row['daily_ret']) else 0.0

        # Get signals for this date
        hawk = hawk_signals.loc[date] if date in hawk_signals.index else pd.Series({'hawk_hp': np.nan, 'hawk_strong': False})
        eps = eps_signals.loc[date] if date in eps_signals.index else pd.Series({'eps_mom_26w': np.nan, 'forward_pe': np.nan, 'eps_danger': False, 'eps_reentry_signal': False})

        if state == 'IN':
            # Apply market return
            equity *= (1 + daily_ret)

            # Check exit
            should_exit = exit_fn(date, hawk, eps)
            if should_exit:
                state = 'OUT'
                current_trade = {
                    'exit_date': date,
                    'exit_price': row['close'],
                    'exit_equity': equity,
                    'exit_reason': name,
                }

        elif state == 'OUT':
            # Cash: no return applied

            # Check re-entry
            should_enter = entry_fn(date, hawk, eps)
            if should_enter:
                state = 'IN'
                if current_trade:
                    current_trade['entry_date'] = date
                    current_trade['entry_price'] = row['close']
                    current_trade['entry_equity'] = equity
                    trade_log.append(current_trade)
                    current_trade = None

        equity_curve.append({'date': date, 'equity': equity, 'state': state})

    # If still out at end, close the trade
    if current_trade:
        last = qqq_df.iloc[-1]
        current_trade['entry_date'] = last['date']
        current_trade['entry_price'] = last['close']
        current_trade['entry_equity'] = equity
        current_trade['still_out'] = True
        trade_log.append(current_trade)

    return pd.DataFrame(equity_curve), trade_log


def compute_metrics(name, eq_curve, qqq_df, trade_log):
    """Compute standardized metrics."""
    eq = eq_curve['equity'].values
    n_days = len(eq)
    years = n_days / 252

    # CAGR
    total_ret = eq[-1] / eq[0]
    cagr = total_ret ** (1 / years) - 1

    # Daily returns for Sharpe
    daily_rets = np.diff(eq) / eq[:-1]
    sharpe = np.mean(daily_rets) / np.std(daily_rets) * np.sqrt(252) if np.std(daily_rets) > 0 else 0

    # MDD
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = cagr / abs(mdd) if mdd != 0 else np.inf

    # Time in market
    in_market = (eq_curve['state'] == 'IN').mean()

    # Number of trades
    n_trades = len(trade_log)

    # Avoided drawdown / missed upside
    # Compare strategy equity with B&H equity during OUT periods
    bh_curve = (qqq_df['close'].values / qqq_df['close'].values[0])
    # Normalize to same start
    bh_at_sample = bh_curve / bh_curve[0] * eq[0]

    avoided = 0.0
    missed = 0.0
    for trade in trade_log:
        exit_date = trade['exit_date']
        entry_date = trade['entry_date']

        exit_idx = qqq_df[qqq_df['date'] == exit_date].index
        entry_idx = qqq_df[qqq_df['date'] == entry_date].index

        if len(exit_idx) == 0 or len(entry_idx) == 0:
            continue

        exit_i = exit_idx[0]
        entry_i = entry_idx[0]

        # B&H return during this period
        if exit_i < len(qqq_df) and entry_i < len(qqq_df):
            bh_ret = qqq_df.iloc[entry_i]['close'] / qqq_df.iloc[exit_i]['close'] - 1
            if bh_ret < 0:
                avoided += abs(bh_ret)
            else:
                missed += bh_ret

    return {
        'name': name,
        'cagr': cagr,
        'sharpe': sharpe,
        'mdd': mdd,
        'calmar': calmar,
        'time_in_mkt': in_market,
        'n_trades': n_trades,
        'total_ret': total_ret - 1,
        'avoided_dd': avoided,
        'missed_up': missed,
        'exit_benefit': avoided - missed,
    }


def score_episodes(trade_log, qqq_df):
    """Score each exit/entry episode for timing quality."""
    episodes = []
    for trade in trade_log:
        exit_date = trade['exit_date']
        entry_date = trade['entry_date']

        exit_idx = qqq_df[qqq_df['date'] == exit_date].index
        entry_idx = qqq_df[qqq_df['date'] == entry_date].index
        if len(exit_idx) == 0 or len(entry_idx) == 0:
            continue

        exit_i = exit_idx[0]
        entry_i = entry_idx[0]

        # Prices during the out period
        if exit_i >= entry_i:
            continue

        segment = qqq_df.iloc[exit_i:entry_i + 1]
        exit_price = trade['exit_price']
        entry_price = trade['entry_price']

        # Find actual high and low during out period
        # Also look back 20 trading days before exit for the "top"
        lookback_start = max(0, exit_i - 20)
        pre_segment = qqq_df.iloc[lookback_start:entry_i + 1]
        actual_top = pre_segment['close'].max()
        actual_top_date = pre_segment.loc[pre_segment['close'].idxmax(), 'date']

        actual_bottom = segment['close'].min()
        actual_bottom_date = segment.loc[segment['close'].idxmin(), 'date']

        # B&H return during out period
        bh_ret = entry_price / exit_price - 1

        # Exit efficiency: how close to the top
        exit_from_top = (actual_top - exit_price) / actual_top  # 0% = sold at top

        # Entry efficiency: how close to the bottom
        entry_from_bottom = (entry_price - actual_bottom) / actual_bottom  # 0% = bought at bottom

        episodes.append({
            'exit_date': exit_date,
            'entry_date': entry_date,
            'days_out': (entry_date - exit_date).days,
            'exit_price': exit_price,
            'entry_price': entry_price,
            'actual_top': actual_top,
            'actual_top_date': actual_top_date,
            'actual_bottom': actual_bottom,
            'actual_bottom_date': actual_bottom_date,
            'bh_return': bh_ret,
            'exit_from_top': exit_from_top,
            'entry_from_bottom': entry_from_bottom,
            'still_out': trade.get('still_out', False),
        })

    return episodes


# ─── Define exit/entry functions ──────────────────────────────────

# Hawkish Exit: first day hawk_strong flips True (with 60-day cooldown)
last_hawk_exit = [pd.Timestamp('1900-01-01')]  # mutable closure
def hawk_exit(date, hawk, eps):
    if hawk['hawk_strong'] and (date - last_hawk_exit[0]).days >= 60:
        last_hawk_exit[0] = date
        return True
    return False

# Hawkish Re-entry: HP drops below 0.5%
def hawk_entry(date, hawk, eps):
    hp = hawk['hawk_hp']
    if pd.notna(hp) and hp < 0.5:
        return True
    return False

# EPS Exit: danger zone
last_eps_exit = [pd.Timestamp('1900-01-01')]
def eps_exit(date, hawk, eps):
    if eps['eps_danger'] and (date - last_eps_exit[0]).days >= 60:
        last_eps_exit[0] = date
        return True
    return False

# EPS Re-entry: Mom_26w < -5%
def eps_entry(date, hawk, eps):
    mom = eps['eps_mom_26w']
    if pd.notna(mom) and mom < -5.0:
        return True
    return False

# For EPS→H: EPS exit, Hawkish re-entry
# For H→EPS: Hawkish exit, EPS re-entry

# ─── Run all strategies ──────────────────────────────────────────

strategies = {}

# 1. Buy & Hold
eq_bh, trades_bh = run_strategy('Buy & Hold', qqq_sample, hawk_ff, eps_ff,
                                 lambda d, h, e: False,  # never exit
                                 lambda d, h, e: True)   # always in
strategies['Buy & Hold'] = (eq_bh, trades_bh)

# 2. H→H: Hawkish exit, Hawkish normalize re-entry
last_hawk_exit[0] = pd.Timestamp('1900-01-01')
eq_hh, trades_hh = run_strategy('H→H', qqq_sample, hawk_ff, eps_ff,
                                 hawk_exit, hawk_entry)
strategies['H→H'] = (eq_hh, trades_hh)

# 3. H→EPS: Hawkish exit, EPS re-entry
last_hawk_exit[0] = pd.Timestamp('1900-01-01')
eq_he, trades_he = run_strategy('H→EPS', qqq_sample, hawk_ff, eps_ff,
                                 hawk_exit, eps_entry)
strategies['H→EPS'] = (eq_he, trades_he)

# 4. EPS→EPS: EPS danger exit, EPS re-entry
last_eps_exit[0] = pd.Timestamp('1900-01-01')
eq_ee, trades_ee = run_strategy('EPS→EPS', qqq_sample, hawk_ff, eps_ff,
                                 eps_exit, eps_entry)
strategies['EPS→EPS'] = (eq_ee, trades_ee)

# 5. EPS→H: EPS danger exit, Hawkish normalize re-entry
last_eps_exit[0] = pd.Timestamp('1900-01-01')
eq_eh, trades_eh = run_strategy('EPS→H', qqq_sample, hawk_ff, eps_ff,
                                 eps_exit, hawk_entry)
strategies['EPS→H'] = (eq_eh, trades_eh)


# ═══════════════════════════════════════════════════════════════════
# 5. RESULTS
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*90}")
print("STRATEGY COMPARISON")
print("=" * 90)
print(f"Common sample: {SAMPLE_START.date()} → {SAMPLE_END.date()}")
print(f"Trading days: {len(qqq_sample)}\n")

all_metrics = []
for name, (eq, trades) in strategies.items():
    m = compute_metrics(name, eq, qqq_sample, trades)
    all_metrics.append(m)

# Print summary table
print(f"{'Strategy':<12} {'CAGR':>7} {'Sharpe':>7} {'MDD':>8} {'Calmar':>7} {'InMkt':>6} {'#Tr':>4} {'AvoidDD':>8} {'MissUp':>8} {'ExBen':>8}")
print("─" * 90)
for m in all_metrics:
    print(f"{m['name']:<12} {m['cagr']:>+6.1%} {m['sharpe']:>7.2f} {m['mdd']:>+7.1%} {m['calmar']:>7.2f} "
          f"{m['time_in_mkt']:>5.0%} {m['n_trades']:>4} {m['avoided_dd']:>+7.1%} {m['missed_up']:>+7.1%} {m['exit_benefit']:>+7.1%}")


# ═══════════════════════════════════════════════════════════════════
# 6. PER-EPISODE DETAIL
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*90}")
print("PER-EPISODE TIMING DETAIL")
print("=" * 90)

for name, (eq, trades) in strategies.items():
    if name == 'Buy & Hold':
        continue
    episodes = score_episodes(trades, qqq_sample)
    if not episodes:
        print(f"\n  {name}: No trades in sample period.")
        continue

    print(f"\n  {name} — {len(episodes)} trade(s):")
    print(f"    {'Exit':>12} {'Entry':>12} {'Days':>5} {'ExitP':>8} {'EntryP':>8} {'Top':>8} {'Bottom':>8} {'B&H':>8} {'ExitEff':>8} {'EntryEff':>9} {'Still?'}")
    print(f"    {'─'*105}")

    for ep in episodes:
        still = '⏳' if ep.get('still_out') else ''
        print(f"    {ep['exit_date'].strftime('%Y-%m-%d'):>12} "
              f"{ep['entry_date'].strftime('%Y-%m-%d'):>12} "
              f"{ep['days_out']:>5} "
              f"${ep['exit_price']:>7.0f} "
              f"${ep['entry_price']:>7.0f} "
              f"${ep['actual_top']:>7.0f} "
              f"${ep['actual_bottom']:>7.0f} "
              f"{ep['bh_return']:>+7.1%} "
              f"{ep['exit_from_top']:>+7.1%} "
              f"{ep['entry_from_bottom']:>+8.1%} "
              f"{still}")


# ═══════════════════════════════════════════════════════════════════
# 7. SIGNAL TIMELINE
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*90}")
print("SIGNAL TIMELINE (key dates)")
print("=" * 90)

# Show when each signal fires
hawk_fires = hawk_ff[hawk_ff['hawk_strong'] == True].index
eps_danger_fires = eps_ff[eps_ff['eps_danger'] == True].index
eps_reentry_fires = eps_ff[eps_ff['eps_reentry_signal'] == True].index

# Filter to sample period
hawk_fires = hawk_fires[(hawk_fires >= SAMPLE_START) & (hawk_fires <= SAMPLE_END)]
eps_danger_fires = eps_danger_fires[(eps_danger_fires >= SAMPLE_START) & (eps_danger_fires <= SAMPLE_END)]
eps_reentry_fires = eps_reentry_fires[(eps_reentry_fires >= SAMPLE_START) & (eps_reentry_fires <= SAMPLE_END)]

print(f"\n  Hawkish Strong days in sample: {len(hawk_fires)}")
if len(hawk_fires) > 0:
    # Show clusters
    clusters = []
    current_start = hawk_fires[0]
    current_end = hawk_fires[0]
    for d in hawk_fires[1:]:
        if (d - current_end).days <= 5:
            current_end = d
        else:
            clusters.append((current_start, current_end))
            current_start = d
            current_end = d
    clusters.append((current_start, current_end))
    for s, e in clusters:
        print(f"    {s.strftime('%Y-%m-%d')} → {e.strftime('%Y-%m-%d')} ({(e-s).days+1}d)")

print(f"\n  EPS Danger Zone days in sample: {len(eps_danger_fires)}")
if len(eps_danger_fires) > 0:
    clusters = []
    current_start = eps_danger_fires[0]
    current_end = eps_danger_fires[0]
    for d in eps_danger_fires[1:]:
        if (d - current_end).days <= 10:
            current_end = d
        else:
            clusters.append((current_start, current_end))
            current_start = d
            current_end = d
    clusters.append((current_start, current_end))
    for s, e in clusters:
        print(f"    {s.strftime('%Y-%m-%d')} → {e.strftime('%Y-%m-%d')} ({(e-s).days+1}d)")

print(f"\n  EPS Re-entry (mom<-5%) days in sample: {len(eps_reentry_fires)}")
if len(eps_reentry_fires) > 0:
    clusters = []
    current_start = eps_reentry_fires[0]
    current_end = eps_reentry_fires[0]
    for d in eps_reentry_fires[1:]:
        if (d - current_end).days <= 10:
            current_end = d
        else:
            clusters.append((current_start, current_end))
            current_start = d
            current_end = d
    clusters.append((current_start, current_end))
    for s, e in clusters:
        qqq_at_start = qqq_sample[qqq_sample['date'] == s]['close'].values
        price = f"${qqq_at_start[0]:.0f}" if len(qqq_at_start) > 0 else "N/A"
        print(f"    {s.strftime('%Y-%m-%d')} → {e.strftime('%Y-%m-%d')} ({(e-s).days+1}d) QQQ={price}")

# Final equity comparison
print(f"\n{'='*90}")
print("FINAL EQUITY (growth of $1)")
print("=" * 90)
for name, (eq, _) in strategies.items():
    final = eq['equity'].iloc[-1]
    print(f"  {name:<12} ${final:.4f}")

print(f"\n{'='*90}")
print("DONE")
print("=" * 90)
