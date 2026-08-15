#!/usr/bin/env python3
"""
Strategy Comparison v5 — Final Cleanup
=======================================
Three fixes over v4:
1. Hawkish exit = episode pulse (False→True rising edge), NOT persistent state
2. H→SEP uses raw `rate <= prev_rate` meeting pulse, NOT SEP state-dependent canonical ENTER
3. All parameters frozen — no sweeps

SEP signals from strategy_engine.py (production source of truth).
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

# --- Canonical SEP exits/enters (state-machine dependent) ---
sep_exit_dates = []
sep_enter_dates = []
for r in sep_signals:
    if r['signal'] == 'EXIT':
        sep_exit_dates.append(pd.Timestamp(r['date']))
    elif r['signal'] == 'ENTER':
        sep_enter_dates.append(pd.Timestamp(r['date']))

print(f"  SEP canonical EXIT:  {[d.strftime('%Y-%m-%d') for d in sep_exit_dates]}")
print(f"  SEP canonical ENTER: {[d.strftime('%Y-%m-%d') for d in sep_enter_dates]}")

# --- RAW meeting-level reentry condition: rate <= prev_rate ---
# This is state-independent: ANY meeting where rate didn't go up
sep_raw_reentry_meetings = []
sep_raw_exit_meetings = []
for r in sep_signals:
    has_both = all(pd.notna(x) for x in [r['pce'], r['prev_pce'], r['rate'], r['prev_rate']])
    if not has_both:
        continue
    rate_up = r['rate'] > r['prev_rate']
    pce_up = r['pce'] > r['prev_pce']
    pce_above2 = r['pce'] > 2.0
    is_exit_cond = rate_up and pce_above2 and pce_up
    is_reentry_cond = r['rate'] <= r['prev_rate']
    
    if is_reentry_cond:
        sep_raw_reentry_meetings.append({
            'date': pd.Timestamp(r['date']),
            'rate': r['rate'], 'prev_rate': r['prev_rate'],
            'pce': r['pce'], 'prev_pce': r['prev_pce'],
        })
    if is_exit_cond:
        sep_raw_exit_meetings.append({
            'date': pd.Timestamp(r['date']),
            'rate': r['rate'], 'prev_rate': r['prev_rate'],
            'pce': r['pce'], 'prev_pce': r['prev_pce'],
        })

print(f"\n  RAW meetings where rate<=prev (state-independent):")
for m in sep_raw_reentry_meetings:
    canonical = "← canonical" if m['date'] in sep_enter_dates else ""
    print(f"    {m['date'].strftime('%Y-%m-%d')}  Rate={m['rate']:.2f}(prev={m['prev_rate']:.2f})  "
          f"PCE={m['pce']:.2f}(prev={m['prev_pce']:.2f})  {canonical}")

print(f"\n  RAW meetings where exit condition met (state-independent):")
for m in sep_raw_exit_meetings:
    canonical = "← canonical" if m['date'] in sep_exit_dates else ""
    print(f"    {m['date'].strftime('%Y-%m-%d')}  Rate={m['rate']:.2f}(prev={m['prev_rate']:.2f})  "
          f"PCE={m['pce']:.2f}(prev={m['prev_pce']:.2f})  {canonical}")

# ═══════════════════════════════════════════════════════════════════
# STEP 1: Load other data
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

# --- Hawkish Path (pub-date delayed) ---
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

# Build hawk_strong as forward-filled, then detect RISING EDGE
hawk_ff = pd.DataFrame(index=qqq['date'])
hawk_ff['hawk_hp'] = np.nan; hawk_ff['hawk_strong_raw'] = False
last_hp = np.nan; last_strong = False
for date in qqq['date']:
    if date in hawk_signal_series:
        last_hp = hawk_signal_series[date]['hp']
        last_strong = hawk_signal_series[date]['is_strong']
    hawk_ff.loc[date, 'hawk_hp'] = last_hp
    hawk_ff.loc[date, 'hawk_strong_raw'] = last_strong

# FIX 1: Rising edge detection for hawk_strong
# hawk_strong_pulse = True only on the FIRST day of a new hawk_strong episode
hawk_ff['hawk_strong_prev'] = hawk_ff['hawk_strong_raw'].shift(1).fillna(False)
hawk_ff['hawk_strong_pulse'] = hawk_ff['hawk_strong_raw'] & ~hawk_ff['hawk_strong_prev']

# Count episodes
n_pulses = hawk_ff['hawk_strong_pulse'].sum()
pulse_dates = hawk_ff[hawk_ff['hawk_strong_pulse']].index.tolist()
print(f"  Hawkish strong episodes (rising edges): {n_pulses}")
for d in pulse_dates:
    print(f"    {d.strftime('%Y-%m-%d')}  HP={hawk_ff.loc[d, 'hawk_hp']:.3f}")

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

# --- SEP trade dates ---
# Canonical (state-dependent)
sep_canonical_exit_td = [next_td(d + timedelta(days=1), qqq_dates) for d in sep_exit_dates]
sep_canonical_exit_td = [d for d in sep_canonical_exit_td if d is not None]
sep_canonical_enter_td = [next_td(d + timedelta(days=1), qqq_dates) for d in sep_enter_dates]
sep_canonical_enter_td = [d for d in sep_canonical_enter_td if d is not None]

# FIX 2: Raw reentry meetings (state-independent)
sep_raw_reentry_td = []
for m in sep_raw_reentry_meetings:
    td = next_td(m['date'] + timedelta(days=1), qqq_dates)
    if td: sep_raw_reentry_td.append(td)

sep_raw_exit_td = []
for m in sep_raw_exit_meetings:
    td = next_td(m['date'] + timedelta(days=1), qqq_dates)
    if td: sep_raw_exit_td.append(td)

print(f"\n  SEP canonical exit TDs:  {[d.strftime('%Y-%m-%d') for d in sep_canonical_exit_td]}")
print(f"  SEP canonical enter TDs: {[d.strftime('%Y-%m-%d') for d in sep_canonical_enter_td]}")
print(f"  SEP raw reentry TDs:     {[d.strftime('%Y-%m-%d') for d in sep_raw_reentry_td]}")
print(f"  SEP raw exit TDs:        {[d.strftime('%Y-%m-%d') for d in sep_raw_exit_td]}")

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
    """Run a strategy. exit_fn/entry_fn receive (date, hawk_row, eps_row, state_dict)"""
    equity = 1.0; state = 'IN'; trade_log = []; equity_curve = []; current_trade = None
    state_dict = {'last_exit_date': None}
    for i, row in qqq_df.iterrows():
        date = row['date']; daily_ret = row['daily_ret'] if pd.notna(row['daily_ret']) else 0.0
        hawk = hawk_ff.loc[date] if date in hawk_ff.index else pd.Series({
            'hawk_hp': np.nan, 'hawk_strong_raw': False, 'hawk_strong_pulse': False})
        eps = eps_ff.loc[date] if date in eps_ff.index else pd.Series({
            'eps_mom_26w': np.nan, 'forward_pe': np.nan})
        if state == 'IN':
            equity *= (1 + daily_ret)
            if exit_fn(date, hawk, eps, state_dict):
                state = 'OUT'
                state_dict['last_exit_date'] = date
                current_trade = {'exit_date': date, 'exit_price': row['close'], 'exit_equity': equity}
        elif state == 'OUT':
            if entry_fn(date, hawk, eps, state_dict):
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
# Signal functions (v5 — FROZEN PARAMS)
# ═══════════════════════════════════════════════════════════════════

# --- EXIT ---
def hawk_pulse_exit(date, hawk, eps, sd):
    """FIX 1: Rising-edge pulse. Only fires on False→True transition."""
    return hawk['hawk_strong_pulse']

def hawk_persistent_exit(date, hawk, eps, sd):
    """v4 style: fires every day hawk_strong is True (for comparison)."""
    return hawk['hawk_strong_raw']

def make_sep_canonical_exit():
    """Canonical SEP exit (state-dependent, from strategy_engine)."""
    fired = set()
    def fn(date, hawk, eps, sd):
        if date in sep_canonical_exit_td and date not in fired:
            fired.add(date); return True
        return False
    return fn

# --- RE-ENTRY ---
def hawk_normalize(date, hawk, eps, sd):
    hp = hawk['hawk_hp']; return pd.notna(hp) and hp < 0.5

def eps_entry_neg3(date, hawk, eps, sd):
    m = eps['eps_mom_26w']; return pd.notna(m) and m < -3.0

def make_sep_canonical_entry():
    """Canonical SEP re-entry (state-dependent)."""
    fired = set()
    def fn(date, hawk, eps, sd):
        if date in sep_canonical_enter_td and date not in fired:
            fired.add(date); return True
        return False
    return fn

def make_sep_raw_reentry():
    """FIX 2: Raw SEP reentry — ANY meeting where rate <= prev_rate, state-independent."""
    fired = set()
    def fn(date, hawk, eps, sd):
        if date in sep_raw_reentry_td and date not in fired:
            fired.add(date); return True
        return False
    return fn

def make_entry_or(fn1, fn2):
    def fn(date, hawk, eps, sd): return fn1(date, hawk, eps, sd) or fn2(date, hawk, eps, sd)
    return fn

# ═══════════════════════════════════════════════════════════════════
# PART 1: MAIN COMPARISON
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*120}")
print(f"PART 1: STRATEGY COMPARISON (v5 — pulse exits, raw SEP reentry, frozen params)")
print(f"{'='*120}\n")

configs = [
    ('Buy&Hold',            lambda d,h,e,s: False,         lambda d,h,e,s: True),
    # v5 primary strategies (pulse exit)
    ('Hp->H',               hawk_pulse_exit,               hawk_normalize),
    ('Hp->EPS(-3%)',         hawk_pulse_exit,               eps_entry_neg3),
    ('Hp->SEP(raw)',         hawk_pulse_exit,               make_sep_raw_reentry()),
    ('Hp->SEP(canon)',       hawk_pulse_exit,               make_sep_canonical_entry()),
    ('Hp->(E|H)',            hawk_pulse_exit,               make_entry_or(eps_entry_neg3, hawk_normalize)),
    ('Hp->(S|H)',            hawk_pulse_exit,               make_entry_or(make_sep_raw_reentry(), hawk_normalize)),
    # v4 comparison (persistent exit)
    ('H->EPS(-3%) v4',      hawk_persistent_exit,          eps_entry_neg3),
    ('H->SEP(raw) v4',      hawk_persistent_exit,          make_sep_raw_reentry()),
    # Canonical SEP vs SEP
    ('SEP->SEP',             make_sep_canonical_exit(),     make_sep_canonical_entry()),
]

all_m = []; all_results = {}
for name, exit_fn, entry_fn in configs:
    eq, trades = run_strategy(name, qqq_sample, exit_fn, entry_fn)
    m = metrics(name, eq, qqq_sample, trades)
    all_m.append(m); all_results[name] = (eq, trades)

print(f"{'Strategy':<20} {'CAGR':>7} {'Sharpe':>7} {'MDD':>8} {'Calmar':>7} {'InMkt':>6} {'#Tr':>4} {'$1->':>7} {'AvoidDD':>8} {'MissUp':>8} {'ExBen':>8}")
print("-" * 120)
for m in all_m:
    print(f"{m['name']:<20} {m['cagr']:>+6.1%} {m['sharpe']:>7.2f} {m['mdd']:>+7.1%} {m['calmar']:>7.2f} "
          f"{m['in_mkt']:>5.0%} {m['n_trades']:>4} ${m['final']:>6.2f} "
          f"{m['avoided']:>+7.1%} {m['missed']:>+7.1%} {m['benefit']:>+7.1%}")

# Episode detail
for name in ['Hp->H', 'Hp->EPS(-3%)', 'Hp->SEP(raw)', 'Hp->SEP(canon)', 'Hp->(S|H)',
             'H->EPS(-3%) v4', 'H->SEP(raw) v4', 'SEP->SEP']:
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
        ex_eff = (top - t['exit_price'])/top if top > 0 else 0
        en_eff = (t['entry_price'] - bot)/bot if bot > 0 else 0
        still = ' STILL_OUT' if t.get('still_out') else ''
        print(f"    {t['exit_date'].strftime('%Y-%m-%d')} -> {t['entry_date'].strftime('%Y-%m-%d')} "
              f"({days:>4}d) ${t['exit_price']:>6.0f}->${t['entry_price']:>6.0f} "
              f"B&H={bh:>+6.1%} ExTop={ex_eff:>+5.1%} EnBot={en_eff:>+5.1%}{still}")

# ═══════════════════════════════════════════════════════════════════
# PART 2: v4 vs v5 DIFF (pulse vs persistent)
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*120}")
print(f"PART 2: PULSE vs PERSISTENT EXIT COMPARISON")
print(f"{'='*120}\n")

pairs = [
    ('Hp->EPS(-3%)', 'H->EPS(-3%) v4'),
    ('Hp->SEP(raw)', 'H->SEP(raw) v4'),
]
print(f"{'Pair':<45} {'CAGR_v5':>8} {'CAGR_v4':>8} {'Calmar_v5':>10} {'Calmar_v4':>10} {'#Tr_v5':>7} {'#Tr_v4':>7}")
print("-" * 100)
for v5name, v4name in pairs:
    v5m = next(m for m in all_m if m['name'] == v5name)
    v4m = next(m for m in all_m if m['name'] == v4name)
    print(f"{v5name+' vs '+v4name:<45} {v5m['cagr']:>+7.1%} {v4m['cagr']:>+7.1%} "
          f"{v5m['calmar']:>10.2f} {v4m['calmar']:>10.2f} {v5m['n_trades']:>7} {v4m['n_trades']:>7}")

# ═══════════════════════════════════════════════════════════════════
# PART 3: RAW vs CANONICAL SEP REENTRY
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*120}")
print(f"PART 3: SEP RAW vs CANONICAL REENTRY (after Hawk exit)")
print(f"{'='*120}\n")

pairs2 = [
    ('Hp->SEP(raw)', 'Hp->SEP(canon)'),
]
for v1, v2 in pairs2:
    m1 = next(m for m in all_m if m['name'] == v1)
    m2 = next(m for m in all_m if m['name'] == v2)
    print(f"  {v1:<20}  Calmar={m1['calmar']:.2f}  CAGR={m1['cagr']:+.1%}  #Tr={m1['n_trades']}  $1->${m1['final']:.2f}")
    print(f"  {v2:<20}  Calmar={m2['calmar']:.2f}  CAGR={m2['cagr']:+.1%}  #Tr={m2['n_trades']}  $1->${m2['final']:.2f}")
    print(f"\n  If raw==canonical, the SEP state machine OUT requirement didn't add extra re-entry dates")
    print(f"  for this particular hybrid (Hawk exit already determines when we're OUT).")

# ═══════════════════════════════════════════════════════════════════
# PART 4: 2022 HEAD-TO-HEAD
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*120}")
print(f"PART 4: 2022 BEAR MARKET HEAD-TO-HEAD")
print(f"{'='*120}\n")

qqq_bot_2022 = qqq_sample[(qqq_sample['date'] >= '2022-09-01') & (qqq_sample['date'] <= '2022-11-30')]['close'].min()

print(f"  {'Strategy':<20} {'Exit Date':>12} {'Exit QQQ':>10} {'Entry Date':>12} {'Entry QQQ':>10} {'Days Out':>9} {'Avoided':>8} {'%FromBot':>9}")
print(f"  {'-'*20} {'-'*12} {'-'*10} {'-'*12} {'-'*10} {'-'*9} {'-'*8} {'-'*9}")

for name in ['Hp->EPS(-3%)', 'Hp->H', 'Hp->SEP(raw)', 'Hp->SEP(canon)', 'Hp->(S|H)', 'SEP->SEP']:
    if name not in all_results: continue
    eq, trades = all_results[name]
    for t in trades:
        if t['exit_date'] >= pd.Timestamp('2021-01-01') and t['exit_date'] <= pd.Timestamp('2023-01-01'):
            days = (t['entry_date'] - t['exit_date']).days
            bh = t['entry_price']/t['exit_price']-1
            from_bot = (t['entry_price'] - qqq_bot_2022)/qqq_bot_2022 * 100
            still = '⏳' if t.get('still_out') else ''
            print(f"  {name:<20} {t['exit_date'].strftime('%Y-%m-%d'):>12} ${t['exit_price']:>8.0f} "
                  f"{t['entry_date'].strftime('%Y-%m-%d'):>12} ${t['entry_price']:>8.0f} {days:>8}d "
                  f"{bh:>+7.1%} {from_bot:>+8.1%}% {still}")
            break

print(f"\n  Reference: QQQ Bottom ≈ ${qqq_bot_2022:.0f} (Oct/Nov 2022)")

# ═══════════════════════════════════════════════════════════════════
# PART 5: MDD
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*120}")
print(f"PART 5: MDD INVESTIGATION")
print(f"{'='*120}\n")

for check_name in ['Hp->EPS(-3%)', 'Hp->SEP(raw)', 'SEP->SEP', 'Buy&Hold']:
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

print(f"\n{'='*120}")
print("DONE — All parameters frozen. No sweeps.")
print(f"{'='*120}")
