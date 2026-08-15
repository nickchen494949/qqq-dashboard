#!/usr/bin/env python3
"""
Strategy Comparison v3 — SEP vs EPS Showdown + Threshold Sensitivity
=====================================================================
Adds SEP exit/entry signals from STRATEGY.md:
  SEP Exit:  PCE up-revised AND Rate up-revised AND PCE > 2%
  SEP Entry: PCE down-revised OR Rate down-revised (expectations reset)

Plus EPS re-entry threshold sweep: -1%, -2%, -3%, -4%, -5%

All strategies on QQQ, uniform 2017-05 → 2026-08 sample.
"""

import urllib.request, csv, json, os
import pandas as pd, numpy as np
from datetime import timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
KW_CSV = os.path.join(SCRIPT_DIR, 'static_data', 'kw_feds200533_snapshot.csv')
LSEG_CSV = os.path.join(SCRIPT_DIR, 'lseg_backtest_results_v3.csv')
SEP_REV_JSON = os.path.join(PROJ_DIR, 'data', 'valuation', 'sep_revisions.json')
SEP_HIST_JSON = os.path.join(PROJ_DIR, 'data', 'valuation', 'SEP_HISTORY.json')

print("Loading data...", flush=True)

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

lseg = pd.read_csv(LSEG_CSV)
lseg['date'] = pd.to_datetime(lseg['date'])
lseg = lseg.sort_values('date').reset_index(drop=True)

with open(SEP_REV_JSON) as f: sep_rev_data = json.load(f)
sep_revs = sep_rev_data if isinstance(sep_rev_data, list) else sep_rev_data.get('values', [])
sep_df = pd.DataFrame(sep_revs)
sep_df['date'] = pd.to_datetime(sep_df['date'])
sep_df = sep_df.sort_values('date').reset_index(drop=True)
print(f"  SEP revisions: {len(sep_df)} meetings, {sep_df['date'].min().date()} -> {sep_df['date'].max().date()}")

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

print("Building signals...", flush=True)

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

# SEP signal from STRATEGY.md:
#   Exit: PCE up-revised AND Rate up-revised (both > 0)
#   Entry: PCE down-revised OR Rate down-revised (either < 0)
sep_ff = pd.DataFrame(index=qqq['date'])
sep_ff['sep_hawkish'] = False
sep_ff['sep_dovish'] = False

sep_events = []
for _, rev in sep_df.iterrows():
    meeting_date = rev['date']
    pce_rev = rev['pce_rev']
    rate_rev = rev['rate_rev']
    is_hawkish = (pce_rev > 0) and (rate_rev > 0)
    is_dovish = (pce_rev < 0) or (rate_rev < 0)
    trade_date = next_td(meeting_date + timedelta(days=1), qqq_dates)
    if trade_date is None: continue
    sep_events.append({
        'meeting_date': meeting_date, 'trade_date': trade_date,
        'pce_rev': pce_rev, 'rate_rev': rate_rev,
        'is_hawkish': is_hawkish, 'is_dovish': is_dovish,
    })

last_sep_hawkish = False; last_sep_dovish = False; sep_event_idx = 0
for date in qqq['date']:
    while sep_event_idx < len(sep_events) and sep_events[sep_event_idx]['trade_date'] <= date:
        ev = sep_events[sep_event_idx]
        last_sep_hawkish = ev['is_hawkish']
        last_sep_dovish = ev['is_dovish']
        sep_event_idx += 1
    sep_ff.loc[date, 'sep_hawkish'] = last_sep_hawkish
    sep_ff.loc[date, 'sep_dovish'] = last_sep_dovish

hawkish_meetings = [e for e in sep_events if e['is_hawkish']]
dovish_meetings = [e for e in sep_events if e['is_dovish']]
print(f"  SEP hawkish meetings: {len(hawkish_meetings)}")
for e in hawkish_meetings:
    print(f"    {e['meeting_date'].strftime('%Y-%m-%d')} PCE={e['pce_rev']:+.1f} Rate={e['rate_rev']:+.1f}")
print(f"  SEP dovish meetings: {len(dovish_meetings)}")
for e in dovish_meetings[-10:]:
    print(f"    {e['meeting_date'].strftime('%Y-%m-%d')} PCE={e['pce_rev']:+.1f} Rate={e['rate_rev']:+.1f}")

first_eps = eps_ff[eps_ff['eps_mom_26w'].notna()].index.min()
SAMPLE_START = max(first_eps, pd.Timestamp('2017-01-01'))
SAMPLE_END = qqq['date'].max()
mask = (qqq['date'] >= SAMPLE_START) & (qqq['date'] <= SAMPLE_END)
qqq_sample = qqq[mask].copy().reset_index(drop=True)
print(f"\n  Common sample: {SAMPLE_START.date()} -> {SAMPLE_END.date()}, {len(qqq_sample)} days")

# ═══════════════════════════════════════════════════════════════════
# STRATEGY ENGINE
# ═══════════════════════════════════════════════════════════════════

class CooldownExit:
    def __init__(self, check_fn, cooldown_days=60):
        self.check_fn = check_fn; self.cooldown = cooldown_days
        self.last_exit = pd.Timestamp('1900-01-01')
    def __call__(self, date, hawk, eps, sep):
        if self.check_fn(date, hawk, eps, sep) and (date - self.last_exit).days >= self.cooldown:
            self.last_exit = date; return True
        return False
    def reset(self):
        self.last_exit = pd.Timestamp('1900-01-01')

def run_strategy(name, qqq_df, exit_fn, entry_fn):
    equity = 1.0; state = 'IN'; trade_log = []; equity_curve = []; current_trade = None
    if hasattr(exit_fn, 'reset'): exit_fn.reset()
    for i, row in qqq_df.iterrows():
        date = row['date']; daily_ret = row['daily_ret'] if pd.notna(row['daily_ret']) else 0.0
        hawk = hawk_ff.loc[date] if date in hawk_ff.index else pd.Series({'hawk_hp': np.nan, 'hawk_strong': False})
        eps = eps_ff.loc[date] if date in eps_ff.index else pd.Series({'eps_mom_26w': np.nan, 'forward_pe': np.nan, 'eps_danger': False})
        sep = sep_ff.loc[date] if date in sep_ff.index else pd.Series({'sep_hawkish': False, 'sep_dovish': False})
        if state == 'IN':
            equity *= (1 + daily_ret)
            if exit_fn(date, hawk, eps, sep):
                state = 'OUT'
                current_trade = {'exit_date': date, 'exit_price': row['close'], 'exit_equity': equity}
        elif state == 'OUT':
            if entry_fn(date, hawk, eps, sep):
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

# Signal functions
def _hawk_exit(d, h, e, s): return h['hawk_strong']
def entry_hawk_norm(d, h, e, s):
    hp = h['hawk_hp']; return pd.notna(hp) and hp < 0.5
def _eps_exit(d, h, e, s): return e['eps_danger']
def make_eps_entry(threshold):
    def fn(d, h, e, s):
        m = e['eps_mom_26w']; return pd.notna(m) and m < threshold
    return fn
def _sep_exit(d, h, e, s): return s['sep_hawkish']
def entry_sep_dovish(d, h, e, s): return s['sep_dovish']
def make_entry_or(fn1, fn2):
    def fn(d, h, e, s): return fn1(d, h, e, s) or fn2(d, h, e, s)
    return fn

# ═══════════════════════════════════════════════════════════════════
# PART 1: MAIN COMPARISON
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*115}")
print(f"PART 1: STRATEGY COMPARISON (H vs SEP vs EPS)")
print(f"{'='*115}\n")

configs = [
    ('Buy&Hold',     CooldownExit(lambda d,h,e,s: False),        lambda d,h,e,s: True),
    ('H->H',         CooldownExit(_hawk_exit, 60),                entry_hawk_norm),
    ('H->EPS(-3%)',  CooldownExit(_hawk_exit, 60),                make_eps_entry(-3.0)),
    ('H->SEP',       CooldownExit(_hawk_exit, 60),                entry_sep_dovish),
    ('H->(E|H)',     CooldownExit(_hawk_exit, 60),                make_entry_or(make_eps_entry(-3.0), entry_hawk_norm)),
    ('H->(S|H)',     CooldownExit(_hawk_exit, 60),                make_entry_or(entry_sep_dovish, entry_hawk_norm)),
    ('SEP->SEP',     CooldownExit(_sep_exit, 60),                 entry_sep_dovish),
    ('SEP->EPS(-3%)',CooldownExit(_sep_exit, 60),                 make_eps_entry(-3.0)),
    ('SEP->H',       CooldownExit(_sep_exit, 60),                 entry_hawk_norm),
    ('EPS->H',       CooldownExit(_eps_exit, 180),                entry_hawk_norm),
    ('EPS->SEP',     CooldownExit(_eps_exit, 180),                entry_sep_dovish),
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
for name in ['H->H', 'H->EPS(-3%)', 'H->SEP', 'H->(S|H)', 'SEP->SEP', 'SEP->EPS(-3%)']:
    if name not in all_results: continue
    eq, trades = all_results[name]
    sig_trades = [t for t in trades if (t['entry_date']-t['exit_date']).days > 5]
    if not sig_trades:
        noise = [t for t in trades if (t['entry_date']-t['exit_date']).days <= 5]
        print(f"\n  {name}: {len(trades)} trades, {len(noise)} noise (<5d), 0 significant")
        continue
    print(f"\n  {name} -- {len(sig_trades)} significant trade(s) (of {len(trades)} total):")
    for t in sig_trades:
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
    exit_fn = CooldownExit(_hawk_exit, 60)
    entry_fn = make_eps_entry(thr)
    eq, trades = run_strategy(name, qqq_sample, exit_fn, entry_fn)
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
# PART 3: SEP TIMELINE
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*115}")
print(f"PART 3: SEP EVENT TIMELINE (in sample)")
print(f"{'='*115}\n")

for e in sep_events:
    if e['meeting_date'] < SAMPLE_START: continue
    qqq_row = qqq_sample[qqq_sample['date'] >= e['trade_date']].head(1)
    price = f"${qqq_row['close'].values[0]:.0f}" if len(qqq_row) > 0 else "N/A"
    signal = "HAWK" if e['is_hawkish'] else ("DOVE" if e['is_dovish'] else "NEUT")
    print(f"  {e['meeting_date'].strftime('%Y-%m-%d')} PCE={e['pce_rev']:+.1f} Rate={e['rate_rev']:+.1f} -> {signal:>4}  QQQ={price}")

# ═══════════════════════════════════════════════════════════════════
# PART 4: MDD INVESTIGATION
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*115}")
print(f"PART 4: MDD INVESTIGATION")
print(f"{'='*115}\n")

for check_name in ['H->EPS(-3%)', 'Buy&Hold']:
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
