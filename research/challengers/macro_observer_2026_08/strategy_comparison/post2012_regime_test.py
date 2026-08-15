#!/usr/bin/env python3
"""
Post-2012 Regime Test
=====================
Comparing Pure SEP vs V6 vs V5 vs Buy & Hold 
In the modern Fed Forward Guidance / Dot Plot Era (2012-2026).

Because LSEG Forward EPS only starts in 2016, we use the Trailing EPS Proxy 
(SP500_EPS.json, interpolated) to cover the 2012-2016 period consistently.
"""

import sys, os, csv, json
import pandas as pd, numpy as np
from datetime import timedelta
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

STATIC_DIR = os.path.join(SCRIPT_DIR, 'static_data')
KW_CSV = os.path.join(STATIC_DIR, 'kw_feds200533_snapshot.csv')
DFF_JSON = os.path.join(STATIC_DIR, 'DFF.json')
QQQ_JSON = os.path.join(STATIC_DIR, 'QQQ.json')
EPS_JSON = os.path.join(PROJ_DIR, 'data', 'valuation', 'SP500_EPS.json')
SEP_DIR = os.path.join(PROJ_DIR, 'data', 'fomc_sep')

# STEP 0: Canonical SEP signals
sys.path.insert(0, SCRIPT_DIR)
from strategy_engine import parse_sep_pdfs, build_sep_signals

sep_raw = parse_sep_pdfs(SEP_DIR)
sep_signals = build_sep_signals(sep_raw)

sep_exit_dates = []
sep_enter_dates = []
for r in sep_signals:
    if r['signal'] == 'EXIT': sep_exit_dates.append(pd.Timestamp(r['date']))
    elif r['signal'] == 'ENTER': sep_enter_dates.append(pd.Timestamp(r['date']))

# STEP 1: Load Data
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

with open(DFF_JSON) as f: dff_data = json.load(f)
dff_raw = dff_data.get('values', dff_data) if isinstance(dff_data, dict) else dff_data
dff = pd.DataFrame(dff_raw, columns=['date', 'value'])
dff['date'] = pd.to_datetime(dff['date']); dff['dff'] = pd.to_numeric(dff['value'], errors='coerce')
dff = dff[['date', 'dff']].dropna()

merged = pd.merge(kw[['date','exp_short_1y']], dff[['date','dff']], on='date', how='inner')
merged = merged.sort_values('date').reset_index(drop=True)
merged['hawkish_path'] = merged['exp_short_1y'] - merged['dff']
merged['delta_exp_4w'] = merged['exp_short_1y'] - merged['exp_short_1y'].shift(20)
merged['is_strong_hawk'] = (merged['hawkish_path'] > 0.5) & (merged['delta_exp_4w'] > 0.25)

# EPS Trailing Proxy (45 day delay to prevent lookahead)
with open(EPS_JSON) as f:
    eps_raw = json.load(f)
eps_df = pd.DataFrame(eps_raw.get('values', []), columns=['date', 'eps'])
eps_df['date'] = pd.to_datetime(eps_df['date'])
eps_df['eps'] = pd.to_numeric(eps_df['eps'], errors='coerce')
eps_df = eps_df.sort_values('date').dropna().reset_index(drop=True)
eps_df['pub_date'] = eps_df['date'] + timedelta(days=45)

eps_daily = pd.DataFrame({'date': pd.date_range(eps_df['pub_date'].min(), eps_df['pub_date'].max())})
eps_daily = pd.merge_asof(eps_daily, eps_df[['pub_date', 'eps']].rename(columns={'pub_date': 'date'}), on='date', direction='backward')
eps_daily['eps_mom_26w'] = eps_daily['eps'].pct_change(periods=182) * 100

with open(QQQ_JSON) as f: yd = json.load(f)
vals = yd.get('values', yd) if isinstance(yd, dict) else yd
qqq = pd.DataFrame(vals, columns=['date', 'close'])
qqq['date'] = pd.to_datetime(qqq['date']); qqq['close'] = pd.to_numeric(qqq['close'], errors='coerce')
qqq = qqq.dropna().sort_values('date').reset_index(drop=True)
qqq['daily_ret'] = qqq['close'].pct_change()
qqq_dates = pd.DatetimeIndex(qqq['date'].values)

def next_td(date, trading_dates):
    mask = trading_dates >= date
    return trading_dates[mask][0] if mask.any() else None

# STEP 2: Build Signals
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
        hawk_signal_series[td] = {'obs_date': row['date'], 'hp': row['hawkish_path'], 'is_strong': row['is_strong_hawk']}

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

eps_ff = pd.DataFrame(index=qqq['date'])
eps_ff['eps_mom_26w'] = np.nan
for _, row in eps_daily.dropna(subset=['eps_mom_26w']).iterrows():
    trade_date = next_td(row['date'], qqq_dates)
    if trade_date is not None:
        eps_ff.loc[trade_date, 'eps_mom_26w'] = row['eps_mom_26w']
eps_ff['eps_mom_26w'] = eps_ff['eps_mom_26w'].ffill()

sep_canonical_exit_td = [next_td(d + timedelta(days=1), qqq_dates) for d in sep_exit_dates]
sep_canonical_exit_td = [d for d in sep_canonical_exit_td if d is not None]
sep_canonical_enter_td = [next_td(d + timedelta(days=1), qqq_dates) for d in sep_enter_dates]
sep_canonical_enter_td = [d for d in sep_canonical_enter_td if d is not None]

# STEP 3: Strategy Engine
# START MODERN ERA: 2012-01-01
SAMPLE_START = pd.Timestamp('2012-01-01')
SAMPLE_END = qqq['date'].max()
mask = (qqq['date'] >= SAMPLE_START) & (qqq['date'] <= SAMPLE_END)
qqq_sample = qqq[mask].copy().reset_index(drop=True)

EPS_THRESHOLD = -3.0

def run_strategy(name, qqq_df, exit_fn, entry_fn):
    equity = 1.0; state = 'IN'; trade_log = []; equity_curve = []; current_trade = None
    ctx = {'exit_date': None, 'eps_at_exit': None, 'eps_was_above_since_exit': False}
    for i, row in qqq_df.iterrows():
        date = row['date']; daily_ret = row['daily_ret'] if pd.notna(row['daily_ret']) else 0.0
        hawk = hawk_ff.loc[date] if date in hawk_ff.index else pd.Series({'hawk_hp': np.nan, 'hawk_strong_pulse': False})
        eps_mom = eps_ff.loc[date, 'eps_mom_26w'] if date in eps_ff.index else np.nan
        
        if state == 'IN':
            equity *= (1 + daily_ret)
            if exit_fn(date, hawk, eps_mom, ctx):
                state = 'OUT'
                ctx['exit_date'] = date
                ctx['eps_at_exit'] = eps_mom
                if pd.notna(eps_mom) and eps_mom > EPS_THRESHOLD:
                    ctx['eps_was_above_since_exit'] = True
                else:
                    ctx['eps_was_above_since_exit'] = False
                current_trade = {'exit_date': date, 'exit_price': row['close'], 'exit_equity': equity, 'eps_at_exit': eps_mom}
        elif state == 'OUT':
            if pd.notna(eps_mom) and eps_mom > EPS_THRESHOLD:
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
    cagr = (eq[-1]/eq[0])**(1/years) - 1
    dr = np.diff(eq)/eq[:-1]
    sharpe = np.mean(dr)/np.std(dr)*np.sqrt(252) if np.std(dr)>0 else 0
    peak = np.maximum.accumulate(eq); dd = (eq-peak)/peak; mdd = dd.min()
    calmar = cagr/abs(mdd) if mdd != 0 else np.inf
    in_mkt = (eq_curve['state']=='IN').mean()
    return {'name': name, 'cagr': cagr, 'sharpe': sharpe, 'mdd': mdd, 'calmar': calmar, 'in_mkt': in_mkt, 'n_trades': len(trade_log), 'final': eq[-1]}

# SIGNAL FUNCTIONS
def hawk_pulse_exit(date, hawk, eps_mom, ctx): return hawk['hawk_strong_pulse']
def make_sep_canonical_exit():
    fired = set()
    def fn(date, hawk, eps, sd):
        if date in sep_canonical_exit_td and date not in fired:
            fired.add(date); return True
        return False
    return fn

def make_sep_canonical_entry():
    fired = set()
    def fn(date, hawk, eps, sd):
        if date in sep_canonical_enter_td and date not in fired:
            fired.add(date); return True
        return False
    return fn

def entry_v5(date, hawk, eps_mom, ctx):
    if pd.notna(eps_mom) and eps_mom <= EPS_THRESHOLD:
        ctx['entry_reason'] = 'EPS_NEW'
        return True
    return False

def entry_v6(date, hawk, eps_mom, ctx):
    eps_at_exit = ctx.get('eps_at_exit')
    is_late_arrival = pd.notna(eps_at_exit) and eps_at_exit <= EPS_THRESHOLD
    
    if is_late_arrival:
        if pd.notna(eps_mom) and eps_mom > EPS_THRESHOLD:
            ctx['entry_reason'] = 'EPS_RECOVERY'
            return True
    else:
        if not ctx.get('eps_was_above_since_exit', False):
            pass 
        else:
            if pd.notna(eps_mom) and eps_mom <= EPS_THRESHOLD:
                ctx['entry_reason'] = 'EPS_NEW'
                return True
        hp = hawk['hawk_hp']
        if pd.notna(hp) and hp < 0.5:
            ctx['entry_reason'] = 'HAWK_NORMALIZE'
            return True
    return False

configs = [
    ('Buy&Hold',       lambda d,h,e,c: False,     lambda d,h,e,c: True),
    ('V6 (Cond)',      hawk_pulse_exit,           entry_v6),
    ('V5 (Pure EPS)',  hawk_pulse_exit,           entry_v5),
    ('Pure SEP',       make_sep_canonical_exit(), make_sep_canonical_entry()),
]

print("================================================================================")
print("MODERN FED REGIME BACKTEST (2012-2026)")
print("================================================================================")
print(f"{'Strategy':<20} {'CAGR':>7} {'Sharpe':>7} {'MDD':>8} {'Calmar':>7} {'InMkt':>6} {'#Tr':>4} {'$1->':>7}")
print("-" * 80)
all_results = {}
m_list = []
for name, exit_fn, entry_fn in configs:
    eq, trades = run_strategy(name, qqq_sample, exit_fn, entry_fn)
    m = metrics(name, eq, qqq_sample, trades)
    print(f"{m['name']:<20} {m['cagr']:>+6.1%} {m['sharpe']:>7.2f} {m['mdd']:>+7.1%} {m['calmar']:>7.2f} "
          f"{m['in_mkt']:>5.0%} {m['n_trades']:>4} ${m['final']:>6.2f}")
    m_list.append(m)
    all_results[name] = trades

print("\n================================================================================")
print("TRADE LOG BY CYCLE")
print("================================================================================\n")

for name, trades in all_results.items():
    if name == 'Buy&Hold': continue
    print(f"[{name}] Trades:")
    for t in trades:
        avoided = t['entry_price'] / t['exit_price'] - 1
        days_out = (t['entry_date'] - t['exit_date']).days
        print(f"  {t['exit_date'].strftime('%Y-%m-%d')} -> {t['entry_date'].strftime('%Y-%m-%d')} ({days_out:3d}d)  Avoided: {avoided:>6.1%}")
    print()

