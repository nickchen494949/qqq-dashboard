#!/usr/bin/env python3
"""
Strategy Comparison v4 — Corrected SEP Implementation
======================================================
Uses the ACTUAL strategy_engine.py SEP logic:
  - EXIT:  rate_up AND pce_above_2 AND pce_up  (same target year, consecutive meetings)
  - ENTER: rate <= prev_rate                    (same target year, consecutive meetings)
  - State machine: stays OUT until ENTER fires

Canonical SEP signals (verified against production):
  EXIT:  2021-09-22, 2023-06-14, 2024-06-12, 2024-12-18, 2026-06-17
  ENTER: 2023-03-22, 2023-12-13, 2024-09-18, 2025-03-19

Plus: EPS threshold sweep, full comparison, episode detail.
"""

import sys, os, csv, json, urllib.request
import pandas as pd, numpy as np
from datetime import timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
KW_CSV = os.path.join(SCRIPT_DIR, 'static_data', 'kw_feds200533_snapshot.csv')
LSEG_CSV = os.path.join(SCRIPT_DIR, 'lseg_backtest_results_v3.csv')

# ═══════════════════════════════════════════════════════════════════
# STEP 0: Import canonical SEP signals from strategy_engine.py
# ═══════════════════════════════════════════════════════════════════
print("Loading canonical SEP signals from strategy_engine.py...", flush=True)
sys.path.insert(0, SCRIPT_DIR)
from strategy_engine import parse_sep_pdfs, build_sep_signals

SEP_DIR = os.path.join(PROJ_DIR, 'data', 'fomc_sep')
sep_raw = parse_sep_pdfs(SEP_DIR)
sep_signals = build_sep_signals(sep_raw)

# Extract canonical event pulses
sep_exit_dates = []
sep_enter_dates = []
for r in sep_signals:
    if r['signal'] == 'EXIT':
        sep_exit_dates.append({
            'date': pd.Timestamp(r['date']),
            'pce': r['pce'], 'prev_pce': r['prev_pce'],
            'rate': r['rate'], 'prev_rate': r['prev_rate'],
            'target_year': r['target_year']
        })
    elif r['signal'] == 'ENTER':
        sep_enter_dates.append({
            'date': pd.Timestamp(r['date']),
            'pce': r['pce'], 'prev_pce': r['prev_pce'],
            'rate': r['rate'], 'prev_rate': r['prev_rate'],
            'target_year': r['target_year']
        })

print(f"  SEP EXIT dates:  {[d['date'].strftime('%Y-%m-%d') for d in sep_exit_dates]}")
print(f"  SEP ENTER dates: {[d['date'].strftime('%Y-%m-%d') for d in sep_enter_dates]}")

# Sanity check against known canonical dates
EXPECTED_ENTERS = ['2023-03-22', '2023-12-13', '2024-09-18', '2025-03-19']
actual_enters = [d['date'].strftime('%Y-%m-%d') for d in sep_enter_dates]
for exp in EXPECTED_ENTERS:
    if exp in actual_enters:
        print(f"    ✓ {exp} confirmed")
    else:
        print(f"    ✗ {exp} MISSING — SIGNAL DEFINITION ERROR!")
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════════
# STEP 1: Load other data sources
# ═══════════════════════════════════════════════════════════════════
print("\nLoading Hawkish + EPS + QQQ data...", flush=True)

# Kim-Wright
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

# DFF
dff_json = os.path.join(SCRIPT_DIR, 'static_data', 'DFF.json')
with open(dff_json) as f: dff_data = json.load(f)
dff_raw = dff_data.get('values', dff_data) if isinstance(dff_data, dict) else dff_data
dff = pd.DataFrame(dff_raw, columns=['date', 'value'])
dff['date'] = pd.to_datetime(dff['date']); dff['dff'] = pd.to_numeric(dff['value'], errors='coerce')
dff = dff[['date', 'dff']].dropna()

merged = pd.merge(kw[['date','exp_short_1y','fwd_1y','tp_1y']], dff[['date','dff']], on='date', how='inner')
merged = merged.sort_values('date').reset_index(drop=True)
merged['hawkish_path'] = merged['exp_short_1y'] - merged['dff']
merged['delta_exp_4w'] = merged['exp_short_1y'] - merged['exp_short_1y'].shift(20)
merged['is_strong_hawk'] = (merged['hawkish_path'] > 0.5) & (merged['delta_exp_4w'] > 0.25)

# LSEG EPS
lseg = pd.read_csv(LSEG_CSV)
lseg['date'] = pd.to_datetime(lseg['date'])
lseg = lseg.sort_values('date').reset_index(drop=True)

# QQQ
ypath = os.path.join(SCRIPT_DIR, 'static_data', 'QQQ.json')
if os.path.exists(ypath):
    with open(ypath) as f: yd = json.load(f)
    vals = yd.get('values', yd) if isinstance(yd, dict) else yd
    qqq = pd.DataFrame(vals, columns=['date', 'close'])
    qqq['date'] = pd.to_datetime(qqq['date']); qqq['close'] = pd.to_numeric(qqq['close'], errors='coerce')
else:
    import yfinance as yf
    raw_df = yf.download('QQQ', start='2016-01-01', progress=False)
    qqq = raw_df[['Close']].reset_index(); qqq.columns = ['date', 'close']
    qqq['date'] = pd.to_datetime(qqq['date']).dt.tz_localize(None)

qqq = qqq.dropna().sort_values('date').reset_index(drop=True)
qqq['daily_ret'] = qqq['close'].pct_change()
qqq_dates = pd.DatetimeIndex(qqq['date'].values)

def next_td(date, trading_dates):
    mask = trading_dates >= date
    return trading_dates[mask][0] if mask.any() else None

# ═══════════════════════════════════════════════════════════════════
# STEP 2: Build daily signal arrays
# ═══════════════════════════════════════════════════════════════════
print("Building daily signals...", flush=True)

# --- Hawkish (pub-date delayed) ---
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

hawk_ff = pd.DataFrame(index=qqq['date'])
hawk_ff['hawk_hp'] = np.nan; hawk_ff['hawk_strong'] = False
last_hp = np.nan; last_strong = False
for date in qqq['date']:
    if date in hawk_signal_series:
        last_hp = hawk_signal_series[date]['hp']
        last_strong = hawk_signal_series[date]['is_strong']
    hawk_ff.loc[date, 'hawk_hp'] = last_hp
    hawk_ff.loc[date, 'hawk_strong'] = last_strong

# --- EPS (forward-filled weekly) ---
eps_ff = pd.DataFrame(index=qqq['date'])
eps_ff['eps_mom_26w'] = np.nan; eps_ff['forward_pe'] = np.nan
for _, row in lseg.iterrows():
    obs_date = row['date']
    trade_date = next_td(obs_date + timedelta(days=1), qqq_dates)
    if trade_date is None: trade_date = next_td(obs_date, qqq_dates)
    if trade_date is None: continue
    if pd.notna(row.get('eps_mom_26w')): eps_ff.loc[trade_date, 'eps_mom_26w'] = row['eps_mom_26w']
    if pd.notna(row.get('forward_pe')): eps_ff.loc[trade_date, 'forward_pe'] = row['forward_pe']
eps_ff['eps_mom_26w'] = eps_ff['eps_mom_26w'].ffill()
eps_ff['forward_pe'] = eps_ff['forward_pe'].ffill()
eps_ff['eps_danger'] = (eps_ff['eps_mom_26w'] > 8.0) & (eps_ff['forward_pe'] > 20.0)

# --- SEP (event pulse, NOT forward-filled) ---
# Map each SEP event date to next trading day
sep_exit_td = []
for ev in sep_exit_dates:
    td = next_td(ev['date'] + timedelta(days=1), qqq_dates)
    if td: sep_exit_td.append(td)

sep_enter_td = []
for ev in sep_enter_dates:
    td = next_td(ev['date'] + timedelta(days=1), qqq_dates)
    if td: sep_enter_td.append(td)

print(f"  SEP exit trade dates:  {[d.strftime('%Y-%m-%d') for d in sep_exit_td]}")
print(f"  SEP enter trade dates: {[d.strftime('%Y-%m-%d') for d in sep_enter_td]}")

# ═══════════════════════════════════════════════════════════════════
# STEP 3: Strategy Engine
# ═══════════════════════════════════════════════════════════════════
first_eps = eps_ff[eps_ff['eps_mom_26w'].notna()].index.min()
SAMPLE_START = max(first_eps, pd.Timestamp('2017-01-01'))
SAMPLE_END = qqq['date'].max()
mask = (qqq['date'] >= SAMPLE_START) & (qqq['date'] <= SAMPLE_END)
qqq_sample = qqq[mask].copy().reset_index(drop=True)
print(f"\n  Common sample: {SAMPLE_START.date()} -> {SAMPLE_END.date()}, {len(qqq_sample)} days")

def run_strategy(name, qqq_df, exit_fn, entry_fn):
    """Run a strategy. exit_fn(date, hawk, eps) -> bool, entry_fn(date, hawk, eps) -> bool"""
    equity = 1.0; state = 'IN'; trade_log = []; equity_curve = []; current_trade = None
    for i, row in qqq_df.iterrows():
        date = row['date']; daily_ret = row['daily_ret'] if pd.notna(row['daily_ret']) else 0.0
        hawk = hawk_ff.loc[date] if date in hawk_ff.index else pd.Series({'hawk_hp': np.nan, 'hawk_strong': False})
        eps = eps_ff.loc[date] if date in eps_ff.index else pd.Series({'eps_mom_26w': np.nan, 'forward_pe': np.nan, 'eps_danger': False})
        if state == 'IN':
            equity *= (1 + daily_ret)
            if exit_fn(date, hawk, eps):
                state = 'OUT'
                current_trade = {'exit_date': date, 'exit_price': row['close'], 'exit_equity': equity}
        elif state == 'OUT':
            if entry_fn(date, hawk, eps):
                state = 'IN'
                if current_trade:
                    current_trade['entry_date'] = date; current_trade['entry_price'] = row['close']
                    trade_log.append(current_trade); current_trade = None
        equity_curve.append({'date': date, 'equity': equity, 'state': state})
    if current_trade:
        last = qqq_df.iloc[-1]
        current_trade['entry_date'] = last['date']; current_trade['entry_price'] = last['close']
        current_trade['still_out'] = True; trade_log.append(current_trade)
    return pd.DataFrame(equity_curve), trade_log

def metrics(name, eq_curve, qqq_df, trade_log):
    eq = eq_curve['equity'].values; n = len(eq); years = n / 252
    cagr = (eq[-1]/eq[0])**(1/years) - 1
    dr = np.diff(eq)/eq[:-1]
    sharpe = np.mean(dr)/np.std(dr)*np.sqrt(252) if np.std(dr)>0 else 0
    peak = np.maximum.accumulate(eq); dd = (eq-peak)/peak; mdd = dd.min()
    calmar = cagr/abs(mdd) if mdd != 0 else np.inf
    in_mkt = (eq_curve['state']=='IN').mean()
    avoided = 0.0; missed = 0.0
    for t in trade_log:
        ei = qqq_df[qqq_df['date']==t['exit_date']].index
        ni = qqq_df[qqq_df['date']==t['entry_date']].index
        if len(ei)==0 or len(ni)==0: continue
        bh = qqq_df.iloc[ni[0]]['close']/qqq_df.iloc[ei[0]]['close'] - 1
        if bh < 0: avoided += abs(bh)
        else: missed += bh
    return {'name': name, 'cagr': cagr, 'sharpe': sharpe, 'mdd': mdd, 'calmar': calmar,
            'in_mkt': in_mkt, 'n_trades': len(trade_log), 'final': eq[-1],
            'avoided': avoided, 'missed': missed, 'benefit': avoided - missed}

# ═══════════════════════════════════════════════════════════════════
# Signal functions
# ═══════════════════════════════════════════════════════════════════

# Hawkish
def hawk_exit(date, hawk, eps):
    return hawk['hawk_strong']

def hawk_normalize(date, hawk, eps):
    hp = hawk['hawk_hp']; return pd.notna(hp) and hp < 0.5

# EPS
def eps_danger_exit(date, hawk, eps):
    return eps['eps_danger']

def make_eps_entry(threshold):
    def fn(date, hawk, eps):
        m = eps['eps_mom_26w']; return pd.notna(m) and m < threshold
    return fn

# SEP — event pulse (fires only on the actual meeting trade date)
def make_sep_exit():
    """Returns a closure that fires TRUE only on SEP exit trade dates, once per date"""
    fired = set()
    def fn(date, hawk, eps):
        if date in sep_exit_td and date not in fired:
            fired.add(date)
            return True
        return False
    return fn

def make_sep_entry():
    """Returns a closure that fires TRUE only on SEP enter trade dates, once per date"""
    fired = set()
    def fn(date, hawk, eps):
        if date in sep_enter_td and date not in fired:
            fired.add(date)
            return True
        return False
    return fn

# Combined
def make_entry_or(fn1, fn2):
    def fn(date, hawk, eps): return fn1(date, hawk, eps) or fn2(date, hawk, eps)
    return fn

# ═══════════════════════════════════════════════════════════════════
# PART 1: MAIN COMPARISON
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*115}")
print(f"PART 1: STRATEGY COMPARISON (Corrected SEP)")
print(f"{'='*115}\n")

configs = [
    ('Buy&Hold',         lambda d,h,e: False,           lambda d,h,e: True),
    # Hawkish exit variants
    ('H->H',             hawk_exit,                     hawk_normalize),
    ('H->EPS(-3%)',      hawk_exit,                     make_eps_entry(-3.0)),
    ('H->SEP',           hawk_exit,                     make_sep_entry()),
    ('H->(E|H)',         hawk_exit,                     make_entry_or(make_eps_entry(-3.0), hawk_normalize)),
    ('H->(S|H)',         hawk_exit,                     make_entry_or(make_sep_entry(), hawk_normalize)),
    # SEP exit variants (pulse-based)
    ('SEP->SEP',         make_sep_exit(),               make_sep_entry()),
    ('SEP->H',           make_sep_exit(),               hawk_normalize),
    ('SEP->EPS(-3%)',    make_sep_exit(),               make_eps_entry(-3.0)),
    ('SEP->(E|H)',       make_sep_exit(),               make_entry_or(make_eps_entry(-3.0), hawk_normalize)),
]

all_m = []; all_results = {}
for name, exit_fn, entry_fn in configs:
    eq, trades = run_strategy(name, qqq_sample, exit_fn, entry_fn)
    m = metrics(name, eq, qqq_sample, trades)
    all_m.append(m); all_results[name] = (eq, trades)

print(f"{'Strategy':<16} {'CAGR':>7} {'Sharpe':>7} {'MDD':>8} {'Calmar':>7} {'InMkt':>6} {'#Tr':>4} {'$1->':>7} {'AvoidDD':>8} {'MissUp':>8} {'ExBen':>8}")
print("-" * 115)
for m in all_m:
    print(f"{m['name']:<16} {m['cagr']:>+6.1%} {m['sharpe']:>7.2f} {m['mdd']:>+7.1%} {m['calmar']:>7.2f} "
          f"{m['in_mkt']:>5.0%} {m['n_trades']:>4} ${m['final']:>6.2f} "
          f"{m['avoided']:>+7.1%} {m['missed']:>+7.1%} {m['benefit']:>+7.1%}")

# Episode detail
for name in ['H->H', 'H->EPS(-3%)', 'H->SEP', 'H->(S|H)', 'SEP->SEP', 'SEP->H', 'SEP->EPS(-3%)', 'SEP->(E|H)']:
    if name not in all_results: continue
    eq, trades = all_results[name]
    if not trades:
        print(f"\n  {name}: 0 trades")
        continue
    print(f"\n  {name} -- {len(trades)} trade(s):")
    for t in trades:
        days = (t['entry_date']-t['exit_date']).days
        ei = qqq_sample[qqq_sample['date']==t['exit_date']].index
        ni = qqq_sample[qqq_sample['date']==t['entry_date']].index
        if len(ei)==0 or len(ni)==0: continue
        seg = qqq_sample.iloc[ei[0]:ni[0]+1]
        top = seg['close'].max(); bot = seg['close'].min()
        bh = t['entry_price']/t['exit_price']-1
        ex_eff = (top - t['exit_price'])/top
        en_eff = (t['entry_price'] - bot)/bot if bot > 0 else 0
        still = ' STILL_OUT' if t.get('still_out') else ''
        print(f"    {t['exit_date'].strftime('%Y-%m-%d')} -> {t['entry_date'].strftime('%Y-%m-%d')} "
              f"({days:>4}d) ${t['exit_price']:>6.0f}->${t['entry_price']:>6.0f} "
              f"B&H={bh:>+6.1%} ExTop={ex_eff:>+5.1%} EnBot={en_eff:>+5.1%}{still}")

# ═══════════════════════════════════════════════════════════════════
# PART 2: EPS THRESHOLD SENSITIVITY
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*115}")
print(f"PART 2: EPS RE-ENTRY THRESHOLD SENSITIVITY (Hawkish Exit)")
print(f"{'='*115}\n")

thresholds = [-1.0, -2.0, -3.0, -4.0, -5.0]
sweep_m = []
for thr in thresholds:
    name = f'H->EPS({thr:+.0f}%)'
    eq, trades = run_strategy(name, qqq_sample, hawk_exit, make_eps_entry(thr))
    m = metrics(name, eq, qqq_sample, trades)
    entry_dates = [(t['entry_date'], t['entry_price']) for t in trades if (t['entry_date'] - t['exit_date']).days > 5]
    m['entry_detail'] = entry_dates
    sweep_m.append(m)

print(f"{'Threshold':<15} {'CAGR':>7} {'Sharpe':>7} {'MDD':>8} {'Calmar':>7} {'InMkt':>6} {'#Tr':>4} {'$1->':>7} {'Entry Date':>12} {'Entry QQQ':>10}")
print("-" * 115)
for m in sweep_m:
    if m['entry_detail']:
        d, p = m['entry_detail'][0]
        entry_info = f"{d.strftime('%Y-%m-%d'):>12} ${p:>8.0f}"
    else:
        entry_info = f"{'NEVER':>12} {'---':>10}"
    print(f"{m['name']:<15} {m['cagr']:>+6.1%} {m['sharpe']:>7.2f} {m['mdd']:>+7.1%} {m['calmar']:>7.2f} "
          f"{m['in_mkt']:>5.0%} {m['n_trades']:>4} ${m['final']:>6.2f} {entry_info}")

# ═══════════════════════════════════════════════════════════════════
# PART 3: CANONICAL SEP TIMELINE
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*115}")
print(f"PART 3: CANONICAL SEP SIGNAL TIMELINE (from strategy_engine.py)")
print(f"{'='*115}\n")

for r in sep_signals:
    meeting_date = pd.Timestamp(r['date'])
    if meeting_date < SAMPLE_START: continue
    qqq_row = qqq_sample[qqq_sample['date'] >= meeting_date].head(1)
    price = f"${qqq_row['close'].values[0]:.0f}" if len(qqq_row) > 0 else "N/A"
    
    pce_chg = ""
    if r['pce'] is not None and r['prev_pce'] is not None:
        d = r['pce'] - r['prev_pce']
        pce_chg = f"PCE={r['pce']:.2f}({'up' if d>0 else 'dn' if d<0 else 'eq'}{abs(d):.2f})"
    rate_chg = ""
    if r['rate'] is not None and r['prev_rate'] is not None:
        d = r['rate'] - r['prev_rate']
        rate_chg = f"Rate={r['rate']:.2f}({'up' if d>0 else 'dn' if d<0 else 'eq'}{abs(d):.2f})"
    
    signal_marker = f"<< {r['signal']}" if r['signal'] else ""
    same = "same_ty" if r['same_ty'] else "diff_ty"
    print(f"  {r['date']}  TY={r['target_year']} {same:>7}  {pce_chg:<25} {rate_chg:<25}  QQQ={price}  {signal_marker}")

# ═══════════════════════════════════════════════════════════════════
# PART 4: HEAD-TO-HEAD 2022 EPISODE
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*115}")
print(f"PART 4: 2022 BEAR MARKET HEAD-TO-HEAD")
print(f"{'='*115}\n")

print(f"  {'Strategy':<16} {'Exit Date':>12} {'Exit QQQ':>10} {'Entry Date':>12} {'Entry QQQ':>10} {'Days Out':>9} {'B&H During':>11} {'ExTop':>7} {'EnBot':>7}")
print(f"  {'-'*16} {'-'*12} {'-'*10} {'-'*12} {'-'*10} {'-'*9} {'-'*11} {'-'*7} {'-'*7}")

qqq_top_2022 = qqq_sample[(qqq_sample['date'] >= '2021-11-01') & (qqq_sample['date'] <= '2022-02-01')]['close'].max()
qqq_bot_2022 = qqq_sample[(qqq_sample['date'] >= '2022-09-01') & (qqq_sample['date'] <= '2022-11-30')]['close'].min()

for name in ['H->H', 'H->EPS(-3%)', 'H->SEP', 'H->(S|H)', 'SEP->SEP', 'SEP->H', 'SEP->EPS(-3%)', 'SEP->(E|H)']:
    if name not in all_results: continue
    eq, trades = all_results[name]
    # Find the trade that overlaps 2022
    for t in trades:
        if t['exit_date'] >= pd.Timestamp('2021-01-01') and t['exit_date'] <= pd.Timestamp('2023-01-01'):
            days = (t['entry_date'] - t['exit_date']).days
            bh = t['entry_price']/t['exit_price']-1
            ex_eff = (qqq_top_2022 - t['exit_price'])/qqq_top_2022 * 100
            en_eff = (t['entry_price'] - qqq_bot_2022)/qqq_bot_2022 * 100
            still = '⏳' if t.get('still_out') else ''
            print(f"  {name:<16} {t['exit_date'].strftime('%Y-%m-%d'):>12} ${t['exit_price']:>8.0f} "
                  f"{t['entry_date'].strftime('%Y-%m-%d'):>12} ${t['entry_price']:>8.0f} {days:>8}d "
                  f"{bh:>+10.1%} {ex_eff:>+6.1%}% {en_eff:>+6.1%}% {still}")
            break

print(f"\n  Reference: QQQ Top ≈ ${qqq_top_2022:.0f}, Bottom ≈ ${qqq_bot_2022:.0f}")

# ═══════════════════════════════════════════════════════════════════
# PART 5: MDD INVESTIGATION
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*115}")
print(f"PART 5: MDD INVESTIGATION")
print(f"{'='*115}\n")

for check_name in ['H->EPS(-3%)', 'SEP->SEP', 'Buy&Hold']:
    if check_name not in all_results: continue
    eq_c = all_results[check_name][0]
    eq_vals = eq_c['equity'].values
    peak = np.maximum.accumulate(eq_vals)
    dd = (eq_vals - peak) / peak
    mdd_idx = np.argmin(dd)
    peak_idx = np.argmax(eq_vals[:mdd_idx+1])
    mdd_start = eq_c.iloc[peak_idx]['date']
    mdd_end = eq_c.iloc[mdd_idx]['date']
    print(f"  {check_name}: MDD={dd[mdd_idx]:.1%}, {mdd_start.strftime('%Y-%m-%d')} -> {mdd_end.strftime('%Y-%m-%d')}")

print(f"\n{'='*115}")
print("DONE")
print(f"{'='*115}")
