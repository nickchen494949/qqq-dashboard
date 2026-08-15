#!/usr/bin/env python3
"""
Historical Falsification Test — Stress-testing H→EPS across 2000–2023
=====================================================================
Purpose: NOT validation. Find how the strategy DIES.

Key innovations:
1. "New EPS distress" = EPS crosses below -3% AFTER exit (not pre-existing)
2. Fallback: H→(NewEPS OR H-normalize) — handles false alarms
3. Uses S&P 500 trailing 12M EPS 6M momentum as proxy (NO recalibration)

Target failure modes:
- 2004-06: Hawkish fires, no EPS collapse → stuck out?
- 2008: EPS already below -3% when Hawkish fires → immediate false re-entry?
"""

import sys, os, csv, json, urllib.request
import pandas as pd, numpy as np
from datetime import timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
KW_CSV = os.path.join(SCRIPT_DIR, 'static_data', 'kw_feds200533_snapshot.csv')

# ═══════════════════════════════════════════════════════════════════
# STEP 1: Load data
# ═══════════════════════════════════════════════════════════════════
print("Loading data...", flush=True)

# --- Kim-Wright ---
with open(KW_CSV, 'r', encoding='utf-8') as f:
    lines = f.read().strip().split('\n')
header_idx = next(i for i, l in enumerate(lines) if l.startswith('Date,'))
reader = csv.DictReader(lines[header_idx:])
kw_rows = []
for row in reader:
    try:
        kw_rows.append({'date': row['Date'], 'fwd_1y': float(row['THREEFF0100.B']),
                        'tp_1y': float(row['THREEFFTP0100.B'])})
    except: continue
kw = pd.DataFrame(kw_rows); kw['date'] = pd.to_datetime(kw['date'])
kw['exp_short_1y'] = kw['fwd_1y'] - kw['tp_1y']
kw = kw.sort_values('date').reset_index(drop=True)
print(f"  Kim-Wright: {kw.date.min().date()} -> {kw.date.max().date()}")

# --- DFF ---
dff_json = os.path.join(SCRIPT_DIR, 'static_data', 'DFF.json')
with open(dff_json) as f: dff_data = json.load(f)
dff_raw = dff_data.get('values', dff_data) if isinstance(dff_data, dict) else dff_data
dff = pd.DataFrame(dff_raw, columns=['date', 'value'])
dff['date'] = pd.to_datetime(dff['date']); dff['dff'] = pd.to_numeric(dff['value'], errors='coerce')
dff = dff[['date', 'dff']].dropna()

merged = pd.merge(kw[['date','exp_short_1y']], dff[['date','dff']], on='date', how='inner')
merged = merged.sort_values('date').reset_index(drop=True)
merged['hawkish_path'] = merged['exp_short_1y'] - merged['dff']
merged['delta_exp_4w'] = merged['exp_short_1y'] - merged['exp_short_1y'].shift(20)
merged['is_strong_hawk'] = (merged['hawkish_path'] > 0.5) & (merged['delta_exp_4w'] > 0.25)

# --- QQQ ---
ypath = os.path.join(SCRIPT_DIR, 'static_data', 'QQQ.json')
if os.path.exists(ypath):
    with open(ypath) as f: yd = json.load(f)
    vals = yd.get('values', yd) if isinstance(yd, dict) else yd
    qqq = pd.DataFrame(vals, columns=['date', 'close'])
    qqq['date'] = pd.to_datetime(qqq['date']); qqq['close'] = pd.to_numeric(qqq['close'], errors='coerce')
else:
    import yfinance as yf
    raw_df = yf.download('QQQ', start='1999-01-01', progress=False)
    qqq = raw_df[['Close']].reset_index(); qqq.columns = ['date', 'close']
    qqq['date'] = pd.to_datetime(qqq['date']).dt.tz_localize(None)

qqq = qqq.dropna().sort_values('date').reset_index(drop=True)
qqq['daily_ret'] = qqq['close'].pct_change()
qqq_dates = pd.DatetimeIndex(qqq['date'].values)
print(f"  QQQ: {qqq.date.min().date()} -> {qqq.date.max().date()}")

# --- S&P 500 Trailing EPS (monthly proxy) ---
eps_path = os.path.join(PROJ_DIR, 'data', 'valuation', 'SP500_EPS.json')
with open(eps_path) as f: eps_data = json.load(f)
eps_vals = eps_data if isinstance(eps_data, list) else eps_data.get('values', [])
eps_df = pd.DataFrame(eps_vals, columns=['date', 'eps'])
eps_df['date'] = pd.to_datetime(eps_df['date'])
eps_df['eps'] = pd.to_numeric(eps_df['eps'], errors='coerce')
eps_df = eps_df.dropna().sort_values('date').reset_index(drop=True)

# Compute trailing 12M EPS and 6M momentum
eps_df['eps_12m'] = eps_df['eps'].rolling(4, min_periods=4).sum()  # quarterly contributions summed
# Actually the data is already trailing 12M operating EPS (monthly)
# So just compute 6-month pct change directly
eps_df['eps_mom_6m'] = eps_df['eps'].pct_change(6) * 100
print(f"  S&P 500 EPS: {eps_df.date.min().date()} -> {eps_df.date.max().date()}")

# ═══════════════════════════════════════════════════════════════════
# STEP 2: Build daily signals
# ═══════════════════════════════════════════════════════════════════
print("\nBuilding daily signals...", flush=True)

def next_td(date, trading_dates):
    mask = trading_dates >= date
    return trading_dates[mask][0] if mask.any() else None

# --- Hawkish Path (publication-delayed) ---
def kw_pub_tuesday(obs_date):
    wd = obs_date.weekday()
    friday = obs_date + timedelta(days=(4 - wd) % 7)
    return friday + timedelta(days=4)

hawk_daily = merged[['date','hawkish_path','delta_exp_4w','is_strong_hawk']].copy()
hawk_daily['pub_date'] = hawk_daily['date'].apply(kw_pub_tuesday)
hawk_daily['trade_date'] = hawk_daily['pub_date'].apply(lambda d: next_td(d, qqq_dates))
hawk_daily = hawk_daily.dropna(subset=['trade_date'])

hawk_signal_series = {}
for _, row in hawk_daily.iterrows():
    td = row['trade_date']
    if td not in hawk_signal_series or row['date'] > hawk_signal_series[td]['obs_date']:
        hawk_signal_series[td] = {'obs_date': row['date'], 'hp': row['hawkish_path'],
                                   'is_strong': row['is_strong_hawk']}

# Forward-fill hawk signals, then detect rising edge
hawk_ff = pd.DataFrame(index=qqq['date'])
hawk_ff['hawk_hp'] = np.nan; hawk_ff['hawk_strong_raw'] = False
last_hp = np.nan; last_strong = False
for date in qqq['date']:
    if date in hawk_signal_series:
        last_hp = hawk_signal_series[date]['hp']
        last_strong = hawk_signal_series[date]['is_strong']
    hawk_ff.loc[date, 'hawk_hp'] = last_hp
    hawk_ff.loc[date, 'hawk_strong_raw'] = last_strong
hawk_ff['hawk_strong_prev'] = hawk_ff['hawk_strong_raw'].shift(1).fillna(False)
hawk_ff['hawk_strong_pulse'] = hawk_ff['hawk_strong_raw'] & ~hawk_ff['hawk_strong_prev']

pulse_dates = hawk_ff[hawk_ff['hawk_strong_pulse']].index.tolist()
print(f"  Hawkish pulses: {len(pulse_dates)}")
for d in pulse_dates:
    print(f"    {d.strftime('%Y-%m-%d')}  HP={hawk_ff.loc[d, 'hawk_hp']:.3f}")

# --- Trailing EPS (monthly → daily via forward-fill) ---
eps_ff = pd.DataFrame(index=qqq['date'])
eps_ff['eps_mom_6m'] = np.nan
for _, row in eps_df.iterrows():
    # Monthly data, available ~6 weeks after period end
    pub_date = row['date'] + timedelta(days=45)  # conservative pub lag
    td = next_td(pub_date, qqq_dates)
    if td is not None and pd.notna(row['eps_mom_6m']):
        eps_ff.loc[td, 'eps_mom_6m'] = row['eps_mom_6m']
eps_ff['eps_mom_6m'] = eps_ff['eps_mom_6m'].ffill()

# ═══════════════════════════════════════════════════════════════════
# STEP 3: Strategy Engine with "New Event" Logic
# ═══════════════════════════════════════════════════════════════════
SAMPLE_START = pd.Timestamp('2000-01-01')
SAMPLE_END = min(qqq['date'].max(), eps_df['date'].max() + timedelta(days=90))
mask = (qqq['date'] >= SAMPLE_START) & (qqq['date'] <= SAMPLE_END)
qqq_sample = qqq[mask].copy().reset_index(drop=True)
print(f"\n  Sample: {SAMPLE_START.date()} -> {SAMPLE_END.date()}, {len(qqq_sample)} days")

EPS_THRESHOLD = -3.0

def run_strategy(name, qqq_df, exit_fn, entry_fn):
    equity = 1.0; state = 'IN'; trade_log = []; equity_curve = []; current_trade = None
    ctx = {'exit_date': None, 'eps_at_exit': None, 'eps_was_above_since_exit': False}
    for i, row in qqq_df.iterrows():
        date = row['date']; daily_ret = row['daily_ret'] if pd.notna(row['daily_ret']) else 0.0
        hawk = hawk_ff.loc[date] if date in hawk_ff.index else pd.Series({
            'hawk_hp': np.nan, 'hawk_strong_raw': False, 'hawk_strong_pulse': False})
        eps_mom = eps_ff.loc[date, 'eps_mom_6m'] if date in eps_ff.index else np.nan
        
        if state == 'IN':
            equity *= (1 + daily_ret)
            if exit_fn(date, hawk, eps_mom, ctx):
                state = 'OUT'
                ctx['exit_date'] = date
                ctx['eps_at_exit'] = eps_mom
                # Was EPS already below threshold at exit?
                if pd.notna(eps_mom) and eps_mom >= EPS_THRESHOLD:
                    ctx['eps_was_above_since_exit'] = True
                else:
                    ctx['eps_was_above_since_exit'] = False
                current_trade = {'exit_date': date, 'exit_price': row['close'],
                                 'exit_equity': equity, 'eps_at_exit': eps_mom}
        elif state == 'OUT':
            # Track if EPS has been above threshold at any point since exit
            if pd.notna(eps_mom) and eps_mom >= EPS_THRESHOLD:
                ctx['eps_was_above_since_exit'] = True
            if entry_fn(date, hawk, eps_mom, ctx):
                state = 'IN'
                if current_trade:
                    current_trade['entry_date'] = date; current_trade['entry_price'] = row['close']
                    current_trade['entry_reason'] = ctx.get('entry_reason', '?')
                    trade_log.append(current_trade); current_trade = None
        equity_curve.append({'date': date, 'equity': equity, 'state': state})
    if current_trade:
        last = qqq_df.iloc[-1]
        current_trade['entry_date'] = last['date']; current_trade['entry_price'] = last['close']
        current_trade['still_out'] = True; current_trade['entry_reason'] = 'STILL_OUT'
        trade_log.append(current_trade)
    return pd.DataFrame(equity_curve), trade_log

def metrics(name, eq_curve, qqq_df, trade_log):
    eq = eq_curve['equity'].values; n = len(eq); years = n / 252
    if years == 0: return None
    cagr = (eq[-1]/eq[0])**(1/years) - 1
    dr = np.diff(eq)/eq[:-1]
    sharpe = np.mean(dr)/np.std(dr)*np.sqrt(252) if np.std(dr)>0 else 0
    peak = np.maximum.accumulate(eq); dd = (eq-peak)/peak; mdd = dd.min()
    calmar = cagr/abs(mdd) if mdd != 0 else np.inf
    in_mkt = (eq_curve['state']=='IN').mean()
    return {'name': name, 'cagr': cagr, 'sharpe': sharpe, 'mdd': mdd, 'calmar': calmar,
            'in_mkt': in_mkt, 'n_trades': len(trade_log), 'final': eq[-1]}

# ═══════════════════════════════════════════════════════════════════
# Signal functions
# ═══════════════════════════════════════════════════════════════════

def hawk_pulse_exit(date, hawk, eps_mom, ctx):
    return hawk['hawk_strong_pulse']

def hawk_normalize(date, hawk, eps_mom, ctx):
    hp = hawk['hawk_hp']; return pd.notna(hp) and hp < 0.5

# Simple EPS: just check level (v5 style, may cause 2008 problem)
def eps_simple_entry(date, hawk, eps_mom, ctx):
    if pd.notna(eps_mom) and eps_mom < EPS_THRESHOLD:
        ctx['entry_reason'] = 'EPS_SIMPLE'
        return True
    return False

# NEW EPS: requires crossing below threshold AFTER exit
# If EPS was already below at exit, must first recover above, then cross back below
def eps_new_event_entry(date, hawk, eps_mom, ctx):
    if not ctx.get('eps_was_above_since_exit', False):
        return False  # EPS hasn't been above threshold since exit — no new event possible
    if pd.notna(eps_mom) and eps_mom < EPS_THRESHOLD:
        ctx['entry_reason'] = 'EPS_NEW'
        return True
    return False

def make_entry_or(fn1, fn2):
    def fn(date, hawk, eps_mom, ctx):
        if fn1(date, hawk, eps_mom, ctx):
            return True
        if fn2(date, hawk, eps_mom, ctx):
            return True
        return False
    return fn

def entry_new_eps_or_hawk(date, hawk, eps_mom, ctx):
    if eps_new_event_entry(date, hawk, eps_mom, ctx):
        return True
    if hawk_normalize(date, hawk, eps_mom, ctx):
        ctx['entry_reason'] = 'HAWK_NORMALIZE'
        return True
    return False

def entry_simple_eps_or_hawk(date, hawk, eps_mom, ctx):
    if eps_simple_entry(date, hawk, eps_mom, ctx):
        return True
    if hawk_normalize(date, hawk, eps_mom, ctx):
        ctx['entry_reason'] = 'HAWK_NORMALIZE'
        return True
    return False

# ═══════════════════════════════════════════════════════════════════
# PART 1: FULL PERIOD COMPARISON (2000–2023)
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*130}")
print(f"PART 1: FULL PERIOD (2000–2023) — FALSIFICATION TEST")
print(f"{'='*130}\n")

configs = [
    ('Buy&Hold',                  lambda d,h,e,c: False,     lambda d,h,e,c: True),
    ('Hp→EPS(simple)',            hawk_pulse_exit,           eps_simple_entry),
    ('Hp→EPS(new event)',         hawk_pulse_exit,           eps_new_event_entry),
    ('Hp→(NewEPS|H)',             hawk_pulse_exit,           entry_new_eps_or_hawk),
    ('Hp→(SimpleEPS|H)',          hawk_pulse_exit,           entry_simple_eps_or_hawk),
    ('Hp→H',                      hawk_pulse_exit,           hawk_normalize),
]

all_m = []; all_results = {}
for name, exit_fn, entry_fn in configs:
    eq, trades = run_strategy(name, qqq_sample, exit_fn, entry_fn)
    m = metrics(name, eq, qqq_sample, trades)
    if m: all_m.append(m)
    all_results[name] = (eq, trades)

print(f"{'Strategy':<22} {'CAGR':>7} {'Sharpe':>7} {'MDD':>8} {'Calmar':>7} {'InMkt':>6} {'#Tr':>4} {'$1->':>8}")
print("-" * 82)
for m in all_m:
    print(f"{m['name']:<22} {m['cagr']:>+6.1%} {m['sharpe']:>7.2f} {m['mdd']:>+7.1%} {m['calmar']:>7.2f} "
          f"{m['in_mkt']:>5.0%} {m['n_trades']:>4} ${m['final']:>7.2f}")

# ═══════════════════════════════════════════════════════════════════
# PART 2: EPISODE DETAIL — every trade
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*130}")
print(f"PART 2: EVERY TRADE — EPISODE DETAIL")
print(f"{'='*130}")

for name in ['Hp→EPS(simple)', 'Hp→EPS(new event)', 'Hp→(NewEPS|H)', 'Hp→H']:
    eq, trades = all_results[name]
    print(f"\n  {name} — {len(trades)} trade(s):")
    if not trades:
        print(f"    (no trades)")
        continue
    print(f"    {'Exit Date':>12} {'Exit QQQ':>9} {'EPSatExit':>10} {'Entry Date':>12} {'Entry QQQ':>9} "
          f"{'Days':>5} {'B&H':>7} {'Reason':>15} {'Era':>25}")
    print(f"    {'-'*12} {'-'*9} {'-'*10} {'-'*12} {'-'*9} {'-'*5} {'-'*7} {'-'*15} {'-'*25}")
    for t in trades:
        days = (t['entry_date'] - t['exit_date']).days
        bh = t['entry_price']/t['exit_price']-1 if t['exit_price']>0 else 0
        eps_exit = f"{t.get('eps_at_exit', 0):+.1f}%" if pd.notna(t.get('eps_at_exit')) else "N/A"
        reason = t.get('entry_reason', '?')
        still = ' ⏳' if t.get('still_out') else ''
        
        yr = t['exit_date'].year
        if yr <= 2002: era = 'Post-dotcom'
        elif yr <= 2003: era = 'Pre-tightening'
        elif yr <= 2006: era = '2004-06 Greenspan'
        elif yr <= 2009: era = '2007-09 GFC'
        elif yr <= 2011: era = '2009-11 Recovery'
        elif yr <= 2021: era = '2017-21 Pre-tightening'
        else: era = '2022 Tightening'
        
        print(f"    {t['exit_date'].strftime('%Y-%m-%d'):>12} ${t['exit_price']:>7.0f} {eps_exit:>10} "
              f"{t['entry_date'].strftime('%Y-%m-%d'):>12} ${t['entry_price']:>7.0f} "
              f"{days:>4}d {bh:>+6.1%} {reason:>15} {era:>25}{still}")

# ═══════════════════════════════════════════════════════════════════
# PART 3: FOCUSED FAILURE MODE ANALYSIS
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*130}")
print(f"PART 3: FAILURE MODE ANALYSIS")
print(f"{'='*130}")

# --- 2004-06 Greenspan tightening ---
print(f"\n  ▼ 2004-06 GREENSPAN TIGHTENING (5 hawkish pulses, no recession)")
pulses_2004 = [d for d in pulse_dates if 2004 <= d.year <= 2005]
for d in pulses_2004:
    eps_val = eps_ff.loc[d, 'eps_mom_6m'] if d in eps_ff.index else np.nan
    qqq_row = qqq_sample[qqq_sample['date'] >= d].head(1)
    price = qqq_row['close'].values[0] if len(qqq_row)>0 else np.nan
    print(f"    Pulse: {d.strftime('%Y-%m-%d')}  QQQ=${price:.0f}  EPS_6m={eps_val:+.1f}%")

for name in ['Hp→EPS(simple)', 'Hp→EPS(new event)', 'Hp→(NewEPS|H)']:
    eq, trades = all_results[name]
    era_trades = [t for t in trades if 2004 <= t['exit_date'].year <= 2006]
    if era_trades:
        for t in era_trades:
            days = (t['entry_date'] - t['exit_date']).days
            reason = t.get('entry_reason', '?')
            print(f"    {name}: Exit {t['exit_date'].strftime('%Y-%m-%d')} -> "
                  f"Entry {t['entry_date'].strftime('%Y-%m-%d')} ({days}d) reason={reason}")
    else:
        # Check if strategy exited but never re-entered
        still_out = [t for t in trades if t['exit_date'].year <= 2006 and t.get('still_out')]
        if still_out:
            print(f"    {name}: Exit {still_out[0]['exit_date'].strftime('%Y-%m-%d')} -> NEVER RE-ENTERED ⚠️")
        else:
            print(f"    {name}: No exit in this era (pulse absorbed by earlier trade)")

# --- 2008 GFC ---
print(f"\n  ▼ 2008 GFC (hawkish pulse 2008-06-17, EPS already collapsing)")
pulse_2008 = [d for d in pulse_dates if d.year == 2008]
for d in pulse_2008:
    eps_val = eps_ff.loc[d, 'eps_mom_6m'] if d in eps_ff.index else np.nan
    qqq_row = qqq_sample[qqq_sample['date'] >= d].head(1)
    price = qqq_row['close'].values[0] if len(qqq_row)>0 else np.nan
    print(f"    Pulse: {d.strftime('%Y-%m-%d')}  QQQ=${price:.0f}  EPS_6m={eps_val:+.1f}%")

# Show EPS trajectory around GFC
print(f"\n    EPS 6M momentum around GFC:")
for _, row in eps_df[(eps_df.date >= '2007-06-01') & (eps_df.date <= '2009-12-01')].iterrows():
    if pd.notna(row['eps_mom_6m']):
        marker = " ←← HAWKISH PULSE" if any(abs((row['date'] - d).days) < 45 for d in pulse_2008) else ""
        cross = " *** CROSSES -3% ***" if -4 < row['eps_mom_6m'] < -2.5 else ""
        print(f"      {row['date'].strftime('%Y-%m')}  EPS_6m={row['eps_mom_6m']:+.1f}%{cross}{marker}")

for name in ['Hp→EPS(simple)', 'Hp→EPS(new event)', 'Hp→(NewEPS|H)']:
    eq, trades = all_results[name]
    era_trades = [t for t in trades if 2007 <= t['exit_date'].year <= 2009]
    if era_trades:
        for t in era_trades:
            days = (t['entry_date'] - t['exit_date']).days
            reason = t.get('entry_reason', '?')
            bh = t['entry_price']/t['exit_price']-1
            eps_exit = t.get('eps_at_exit', np.nan)
            eps_str = f"EPS@exit={eps_exit:+.1f}%" if pd.notna(eps_exit) else ""
            print(f"    {name}: Exit {t['exit_date'].strftime('%Y-%m-%d')} -> "
                  f"Entry {t['entry_date'].strftime('%Y-%m-%d')} ({days}d) "
                  f"B&H={bh:+.1%} reason={reason} {eps_str}")

# --- 2022 Tightening (sanity check: trailing EPS proxy vs forward EPS) ---
print(f"\n  ▼ 2022 TIGHTENING (sanity check: trailing proxy vs forward consensus)")
pulse_2022 = [d for d in pulse_dates if d.year == 2022]
for d in pulse_2022:
    eps_val = eps_ff.loc[d, 'eps_mom_6m'] if d in eps_ff.index else np.nan
    qqq_row = qqq_sample[qqq_sample['date'] >= d].head(1)
    price = qqq_row['close'].values[0] if len(qqq_row)>0 else np.nan
    print(f"    Pulse: {d.strftime('%Y-%m-%d')}  QQQ=${price:.0f}  EPS_6m={eps_val:+.1f}%")

print(f"\n    EPS 6M momentum around 2022:")
for _, row in eps_df[(eps_df.date >= '2022-01-01') & (eps_df.date <= '2023-06-01')].iterrows():
    if pd.notna(row['eps_mom_6m']):
        cross = " *** CROSSES -3% ***" if -4 < row['eps_mom_6m'] < -2.5 else ""
        print(f"      {row['date'].strftime('%Y-%m')}  EPS_6m={row['eps_mom_6m']:+.1f}%{cross}")

for name in ['Hp→EPS(simple)', 'Hp→EPS(new event)', 'Hp→(NewEPS|H)']:
    eq, trades = all_results[name]
    era_trades = [t for t in trades if 2021 <= t['exit_date'].year <= 2023]
    if era_trades:
        for t in era_trades:
            days = (t['entry_date'] - t['exit_date']).days
            reason = t.get('entry_reason', '?')
            bh = t['entry_price']/t['exit_price']-1
            print(f"    {name}: Exit {t['exit_date'].strftime('%Y-%m-%d')} -> "
                  f"Entry {t['entry_date'].strftime('%Y-%m-%d')} ({days}d) "
                  f"B&H={bh:+.1%} reason={reason}")

# ═══════════════════════════════════════════════════════════════════
# PART 4: MDD PER STRATEGY
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*130}")
print(f"PART 4: MDD INVESTIGATION")
print(f"{'='*130}\n")

for name in ['Hp→EPS(simple)', 'Hp→EPS(new event)', 'Hp→(NewEPS|H)', 'Hp→H', 'Buy&Hold']:
    if name not in all_results: continue
    eq_c = all_results[name][0]
    eq_vals = eq_c['equity'].values
    peak = np.maximum.accumulate(eq_vals)
    dd = (eq_vals - peak) / peak
    mdd_idx = np.argmin(dd)
    peak_idx = np.argmax(eq_vals[:mdd_idx+1])
    mdd_start = eq_c.iloc[peak_idx]['date']
    mdd_end = eq_c.iloc[mdd_idx]['date']
    print(f"  {name:<22}: MDD={dd[mdd_idx]:+.1%}, {mdd_start.strftime('%Y-%m-%d')} -> {mdd_end.strftime('%Y-%m-%d')}")

print(f"\n{'='*130}")
print("DONE — Historical falsification test complete.")
print(f"{'='*130}")
