#!/usr/bin/env python3
"""
Strategy Comparison v2 — Relaxed EPS thresholds
================================================
Adds:
  H→EPS(-3%):  Hawkish exit → EPS Mom < -3% re-entry
  H→EPS(0%):   Hawkish exit → EPS Mom crosses below 0% re-entry
  EPS→H(cd):   EPS exit with 180-day cooldown (prevent noise trades)
"""

import urllib.request, csv, json, os
import pandas as pd, numpy as np
from datetime import timedelta

DASHBOARD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
KW_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200533.csv"
LSEG_CSV = os.path.join(os.path.dirname(__file__), 'lseg_backtest_results_v3.csv')

# ═══════════════════════════════════════════════════════════════════
# DATA LOADING (same as v1)
# ═══════════════════════════════════════════════════════════════════
print("Loading data...", flush=True)

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
    except: continue
kw = pd.DataFrame(kw_rows); kw['date'] = pd.to_datetime(kw['date'])
kw['exp_short_1y'] = kw['fwd_1y'] - kw['tp_1y']
kw = kw.sort_values('date').reset_index(drop=True)

dff_json = os.path.join(DASHBOARD_DIR, 'data', 'fred', 'DFF.json')
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

lseg = pd.read_csv(LSEG_CSV)
lseg['date'] = pd.to_datetime(lseg['date'])
lseg = lseg.sort_values('date').reset_index(drop=True)

ypath = os.path.join(DASHBOARD_DIR, 'data', 'yahoo', 'QQQ.json')
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

def kw_pub_tuesday(obs_date):
    wd = obs_date.weekday()
    friday = obs_date + timedelta(days=(4 - wd) % 7)
    return friday + timedelta(days=4)

def next_td(date, trading_dates):
    mask = trading_dates >= date
    return trading_dates[mask][0] if mask.any() else None

# Build hawk_ff
hawk_daily = merged[['date','hawkish_path','delta_exp_4w','is_strong_hawk']].copy()
hawk_daily['pub_date'] = hawk_daily['date'].apply(kw_pub_tuesday)
hawk_daily['trade_date'] = hawk_daily['pub_date'].apply(lambda d: next_td(d, qqq_dates))
hawk_daily = hawk_daily.dropna(subset=['trade_date'])

hawk_signal_series = {}
for _, row in hawk_daily.iterrows():
    td = row['trade_date']
    if td not in hawk_signal_series or row['date'] > hawk_signal_series[td]['obs_date']:
        hawk_signal_series[td] = {'obs_date': row['date'], 'hp': row['hawkish_path'],
                                   'delta_exp': row['delta_exp_4w'], 'is_strong': row['is_strong_hawk']}

hawk_ff = pd.DataFrame(index=qqq['date'])
hawk_ff['hawk_hp'] = np.nan; hawk_ff['hawk_strong'] = False
last_hp = np.nan; last_strong = False
for date in qqq['date']:
    if date in hawk_signal_series:
        last_hp = hawk_signal_series[date]['hp']
        last_strong = hawk_signal_series[date]['is_strong']
    hawk_ff.loc[date, 'hawk_hp'] = last_hp
    hawk_ff.loc[date, 'hawk_strong'] = last_strong

# Build eps_ff with multiple thresholds
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

# Detect EPS mom crossing thresholds (from above to below)
eps_ff['prev_mom'] = eps_ff['eps_mom_26w'].shift(1)
eps_ff['cross_neg5'] = (eps_ff['eps_mom_26w'] < -5.0) & (eps_ff['prev_mom'] >= -5.0)
eps_ff['cross_neg3'] = (eps_ff['eps_mom_26w'] < -3.0) & (eps_ff['prev_mom'] >= -3.0)
eps_ff['cross_zero'] = (eps_ff['eps_mom_26w'] < 0.0) & (eps_ff['prev_mom'] >= 0.0)

# Sample
first_eps = eps_ff[eps_ff['eps_mom_26w'].notna()].index.min()
SAMPLE_START = max(first_eps, pd.Timestamp('2017-01-01'))
SAMPLE_END = qqq['date'].max()
mask = (qqq['date'] >= SAMPLE_START) & (qqq['date'] <= SAMPLE_END)
qqq_sample = qqq[mask].copy().reset_index(drop=True)

print(f"Data loaded. Sample: {SAMPLE_START.date()} → {SAMPLE_END.date()}, {len(qqq_sample)} days\n")

# ═══════════════════════════════════════════════════════════════════
# STRATEGY ENGINE
# ═══════════════════════════════════════════════════════════════════

def run_strategy(name, qqq_df, exit_fn, entry_fn):
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

def episode_detail(trade_log, qqq_df, max_show=5):
    for t in trade_log[:max_show]:
        ei = qqq_df[qqq_df['date']==t['exit_date']].index
        ni = qqq_df[qqq_df['date']==t['entry_date']].index
        if len(ei)==0 or len(ni)==0: continue
        seg = qqq_df.iloc[ei[0]:ni[0]+1]
        top = seg['close'].max(); bot = seg['close'].min()
        days = (t['entry_date']-t['exit_date']).days
        bh = t['entry_price']/t['exit_price']-1
        ex_eff = (top-t['exit_price'])/top
        en_eff = (t['entry_price']-bot)/bot
        still = '⏳' if t.get('still_out') else ''
        print(f"    {t['exit_date'].strftime('%Y-%m-%d')} → {t['entry_date'].strftime('%Y-%m-%d')} "
              f"({days:>4}d) ${t['exit_price']:>6.0f}→${t['entry_price']:>6.0f} "
              f"B&H={bh:>+6.1%} ExTop={ex_eff:>+5.1%} EnBot={en_eff:>+5.1%} {still}")

# ═══════════════════════════════════════════════════════════════════
# DEFINE ALL STRATEGIES
# ═══════════════════════════════════════════════════════════════════

strategies = []

# --- Hawkish exit function (with cooldown state) ---
class CooldownExit:
    def __init__(self, name, check_fn, cooldown_days=60):
        self.name = name; self.check_fn = check_fn
        self.cooldown = cooldown_days; self.last_exit = pd.Timestamp('1900-01-01')
    def __call__(self, date, hawk, eps):
        if self.check_fn(date, hawk, eps) and (date - self.last_exit).days >= self.cooldown:
            self.last_exit = date; return True
        return False

# Exit functions
def _hawk_exit_raw(d, h, e): return h['hawk_strong']
def _eps_exit_raw(d, h, e): return e['eps_danger']

# Entry functions
def entry_hawk_norm(d, h, e):
    hp = h['hawk_hp']; return pd.notna(hp) and hp < 0.5

def entry_eps_neg5(d, h, e):
    m = e['eps_mom_26w']; return pd.notna(m) and m < -5.0

def entry_eps_neg3(d, h, e):
    m = e['eps_mom_26w']; return pd.notna(m) and m < -3.0

def entry_eps_zero(d, h, e):
    m = e['eps_mom_26w']; return pd.notna(m) and m < 0.0

def entry_eps_neg3_or_hawk(d, h, e):
    """Combined: re-enter if EPS < -3% OR hawk normalizes"""
    m = e['eps_mom_26w']; hp = h['hawk_hp']
    return (pd.notna(m) and m < -3.0) or (pd.notna(hp) and hp < 0.5)

# ─── Strategy list ───
configs = [
    ('Buy&Hold',     lambda d,h,e: False,                     lambda d,h,e: True),
    ('H→H',          CooldownExit('hawk', _hawk_exit_raw, 60), entry_hawk_norm),
    ('H→EPS(-5%)',   CooldownExit('hawk', _hawk_exit_raw, 60), entry_eps_neg5),
    ('H→EPS(-3%)',   CooldownExit('hawk', _hawk_exit_raw, 60), entry_eps_neg3),
    ('H→EPS(0%)',    CooldownExit('hawk', _hawk_exit_raw, 60), entry_eps_zero),
    ('H→(E∨H)',      CooldownExit('hawk', _hawk_exit_raw, 60), entry_eps_neg3_or_hawk),
    ('EPS→EPS',      CooldownExit('eps',  _eps_exit_raw, 180), entry_eps_neg5),
    ('EPS→H',        CooldownExit('eps',  _eps_exit_raw, 180), entry_hawk_norm),
    ('EPS→(E∨H)',    CooldownExit('eps',  _eps_exit_raw, 180), entry_eps_neg3_or_hawk),
]

# ═══════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════
print(f"{'='*100}")
print(f"STRATEGY COMPARISON v2")
print(f"{'='*100}")
print(f"Sample: {SAMPLE_START.date()} → {SAMPLE_END.date()} ({len(qqq_sample)} days)\n")

all_m = []
all_results = {}
for name, exit_fn, entry_fn in configs:
    eq, trades = run_strategy(name, qqq_sample, exit_fn, entry_fn)
    m = metrics(name, eq, qqq_sample, trades)
    all_m.append(m)
    all_results[name] = (eq, trades)

# Summary table
print(f"{'Strategy':<14} {'CAGR':>7} {'Sharpe':>7} {'MDD':>8} {'Calmar':>7} {'InMkt':>6} {'#Tr':>4} {'$1→':>7} {'AvoidDD':>8} {'MissUp':>8} {'ExBen':>8}")
print("─" * 100)
for m in all_m:
    print(f"{m['name']:<14} {m['cagr']:>+6.1%} {m['sharpe']:>7.2f} {m['mdd']:>+7.1%} {m['calmar']:>7.2f} "
          f"{m['in_mkt']:>5.0%} {m['n_trades']:>4} ${m['final']:>6.2f} "
          f"{m['avoided']:>+7.1%} {m['missed']:>+7.1%} {m['benefit']:>+7.1%}")

# Episode detail for key strategies
for name in ['H→H', 'H→EPS(-3%)', 'H→EPS(0%)', 'H→(E∨H)', 'EPS→H', 'EPS→(E∨H)']:
    if name not in all_results: continue
    eq, trades = all_results[name]
    significant = [t for t in trades if (t['entry_date']-t['exit_date']).days > 5]
    if significant:
        print(f"\n  {name} — significant trades (>{5}d out):")
        episode_detail(significant, qqq_sample, max_show=10)
    else:
        print(f"\n  {name}: {len(trades)} trades, all <5 days (noise)")

# ═══════════════════════════════════════════════════════════════════
# EPS MOMENTUM TIMELINE (diagnostic)
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*100}")
print("EPS MOMENTUM TIMELINE (selected thresholds)")
print("=" * 100)

# When did EPS_Mom_26w cross key thresholds?
for threshold, label in [(-5, '<-5%'), (-3, '<-3%'), (0, '<0%'), (8, '>+8%')]:
    if threshold > 0:
        crosses = eps_ff[(eps_ff['eps_mom_26w'] > threshold) & (eps_ff['prev_mom'] <= threshold)].index
    else:
        crosses = eps_ff[(eps_ff['eps_mom_26w'] < threshold) & (eps_ff['prev_mom'] >= threshold)].index
    crosses = crosses[(crosses >= SAMPLE_START) & (crosses <= SAMPLE_END)]
    print(f"\n  EPS Mom crosses {label}: {len(crosses)} times")
    for d in crosses[:10]:
        mom = eps_ff.loc[d, 'eps_mom_26w']
        qqq_row = qqq_sample[qqq_sample['date'] == d]
        price = f"${qqq_row['close'].values[0]:.0f}" if len(qqq_row) > 0 else "N/A"
        print(f"    {d.strftime('%Y-%m-%d')} mom={mom:+.1f}% QQQ={price}")

print(f"\n{'='*100}")
print("DONE")
print("=" * 100)
