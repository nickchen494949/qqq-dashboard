"""
2D Joint Grid using the ACTUAL audit_backtest.py engine.
Strategy: import all data/signals from audit, then sweep Credit×Vol leverage.
"""
import os, sys, re
import numpy as np
import pandas as pd
import yfinance as yf
import pypdf
from fredapi import Fred

# === COPY EXACT CONFIG FROM audit_backtest.py ===
FRED_API_KEY = 'f64f7d1a98a7dd021a155ce2b9703fdb'
PROJECT_DIR  = '/Users/happygolucky/Desktop/QQQ_Risk_Strategy'
DATA_DIR     = os.path.join(PROJECT_DIR, 'market_data')
SEP_DIR      = os.path.join(PROJECT_DIR, 'fomc_sep')
START_DATE   = '2012-01-25'
Z_TRIGGER    = 1.2; Z_RECOVER = 0.2
VZ_TRIGGER   = 1.0; VZ_RECOVER = -0.5
Z_WINDOW     = 252
EXPENSE_RATIO = 0.0086; TC_BPS = 25

fred = Fred(api_key=FRED_API_KEY)
print("Loading data (exact audit engine)...", flush=True)

# === EXACT DATA LOADING FROM audit_backtest.py ===
def fetch_yahoo_ohlc(ticker):
    df = yf.download(ticker, start='2005-01-01', progress=False, auto_adjust=False)
    close_raw = df['Close']
    adj_close = df['Adj Close'] if 'Adj Close' in df.columns else close_raw
    open_raw = df['Open']
    if isinstance(close_raw, pd.DataFrame): close_raw = close_raw.iloc[:, 0]
    if isinstance(adj_close, pd.DataFrame): adj_close = adj_close.iloc[:, 0]
    if isinstance(open_raw, pd.DataFrame): open_raw = open_raw.iloc[:, 0]
    adj_factor = adj_close / close_raw
    adj_open = open_raw * adj_factor
    return adj_close, adj_open

effr_raw = fred.get_series('DFF', observation_start='2005-01-01').dropna()
qqq_raw, qqq_open_raw = fetch_yahoo_ohlc('QQQ')
hyg_raw = yf.download('HYG', start='2005-01-01', progress=False, auto_adjust=False)
ief_raw = yf.download('IEF', start='2005-01-01', progress=False, auto_adjust=False)
for name in ['hyg_raw', 'ief_raw']:
    d = eval(name)
    c = d['Close'] if 'Close' in d.columns else d['Adj Close']
    if isinstance(c, pd.DataFrame): c = c.iloc[:, 0]
    exec(f"{name} = c")

idx = qqq_raw.index[qqq_raw.index >= pd.Timestamp(START_DATE)]
qqq_d = qqq_raw.reindex(idx)
qqq_open = qqq_open_raw.reindex(idx)
effr = effr_raw.reindex(idx).ffill() / 100 / 252
hyg_d = hyg_raw.reindex(idx).ffill()
ief_d = ief_raw.reindex(idx).ffill()

dr_qqq = qqq_d.pct_change()
dr_qqq_gap = qqq_open / qqq_d.shift(1) - 1
dr_qqq_intra = qqq_d / qqq_open - 1

# Z-scores
hyg_ief = hyg_d / ief_d
z_series = -(hyg_ief - hyg_ief.rolling(Z_WINDOW).mean()) / hyg_ief.rolling(Z_WINDOW).std()
rvol_20 = dr_qqq.rolling(20).std() * np.sqrt(252)
vol_z = (rvol_20 - rvol_20.rolling(252).mean()) / rvol_20.rolling(252).std()

# === EXACT SEP PARSING FROM audit_backtest.py (lines 158-306) ===
sep_pdfs = sorted([f for f in os.listdir(SEP_DIR) if f.endswith('.pdf')])
sep_raw = []
for fn in sep_pdfs:
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', fn)
    if not m: continue
    meeting_year = int(m.group(1)); meeting_month = int(m.group(2))
    try:
        reader = pypdf.PdfReader(os.path.join(SEP_DIR, fn))
        text = ''.join(pg.extract_text()+'\n' for pg in reader.pages[:3])
    except: continue
    cp_all, fr_all = [], []
    lines = text.split('\n')
    for li, line in enumerate(lines):
        if not cp_all and re.search(r'Core\s*PCE\s*in[f\uFB02]', line, re.IGNORECASE) and \
           not re.search(r'projection|september|june|march|december|january|november', line, re.IGNORECASE):
            cp_all = [float(x) for x in re.findall(r'(\d+\.\d+)', line)]
        if not fr_all and re.search(r'Federal\s*funds\s*rate', line, re.IGNORECASE) and \
           not re.search(r'projection|september|june|march|december|january|november', line, re.IGNORECASE):
            fr_all = [float(x) for x in re.findall(r'(\d+\.\d+)', line)]
            if not fr_all:
                for offset in range(1, 4):
                    if li + offset < len(lines):
                        nxt = lines[li + offset].strip()
                        if re.search(r'projection', nxt, re.IGNORECASE): continue
                        fr_all = [float(x) for x in re.findall(r'(\d+\.\d+)', nxt)]
                        if fr_all: break
    pce_by_year = {meeting_year + j: v for j, v in enumerate(cp_all[:4])}
    rate_by_year = {meeting_year + j: v for j, v in enumerate(fr_all[:4])}
    target_year = meeting_year if meeting_month < 9 else meeting_year + 1
    sep_raw.append({
        'date': f'{m.group(1)}-{m.group(2)}-{m.group(3)}',
        'meeting_year': meeting_year, 'meeting_month': meeting_month,
        'target_year': target_year,
        'pce': pce_by_year.get(target_year),
        'rate': rate_by_year.get(target_year),
        'pce_by_year': pce_by_year, 'rate_by_year': rate_by_year,
    })

# Hardcoded early rates
_ffr_by_target = {
    ('2012-01-25', 2012): 0.13, ('2012-04-25', 2012): 0.13, ('2012-06-20', 2012): 0.13,
    ('2012-09-13', 2013): 0.13, ('2012-12-12', 2013): 0.13,
    ('2013-03-20', 2013): 0.13, ('2013-06-19', 2013): 0.13,
    ('2013-09-18', 2014): 0.13, ('2013-12-18', 2014): 0.13,
    ('2014-03-19', 2014): 0.13, ('2014-06-18', 2014): 0.13,
    ('2014-09-17', 2015): 1.38, ('2014-12-17', 2015): 0.63,
    ('2015-03-18', 2015): 0.63, ('2015-06-17', 2015): 0.63,
    ('2015-09-17', 2016): 0.38, ('2015-12-16', 2016): 1.4,
    ('2018-12-19', 2019): 2.9,
}
for row in sep_raw:
    ty = row['target_year']
    key = (row['date'], ty)
    if row['rate'] is None and key in _ffr_by_target:
        row['rate'] = _ffr_by_target[key]
        row['rate_by_year'][ty] = _ffr_by_target[key]

# Generate SEP signals (EXACT same-target-year logic)
sep_signals = []
sep_in = True
for i in range(1, len(sep_raw)):
    c, p = sep_raw[i], sep_raw[i-1]
    ty = c['target_year']
    c_pce = c['pce_by_year'].get(ty); c_rate = c['rate_by_year'].get(ty)
    p_pce = p['pce_by_year'].get(ty); p_rate = p['rate_by_year'].get(ty)
    if c_pce is None: continue
    has_both = all(pd.notna(x) for x in [c_pce, c_rate, p_pce, p_rate])
    rate_up = c_rate > p_rate if has_both else False
    pce_above2 = c_pce > 2.0
    pce_up = c_pce > p_pce if has_both else False
    is_exit = rate_up and pce_above2 and pce_up if has_both else False
    reenter = (c_rate <= p_rate) if has_both else False
    signal = ''
    if sep_in and is_exit: signal = 'EXIT'; sep_in = False
    elif not sep_in and reenter: signal = 'ENTER'; sep_in = True
    sep_signals.append({'date': c['date'], 'signal': signal})

sep_signal_dates = {}
for r in sep_signals:
    if not r['signal']: continue
    raw_date = pd.Timestamp(r['date'])
    candidates = idx[idx >= raw_date]
    if len(candidates) == 0: continue
    mapped = candidates[0]
    sep_signal_dates[mapped] = r['signal']

sep_state = pd.Series(1, index=idx)
s = 1
for d in idx:
    if d in sep_signal_dates:
        s = 1 if sep_signal_dates[d] == 'ENTER' else 0
    sep_state[d] = s

days_out = (sep_state == 0).sum()
print(f"Data: {len(idx)} days, SEP out: {days_out} days")

# === EXACT BACKTEST ENGINE FROM audit_backtest.py (lines 313-414) ===
def run_backtest(credit_lev, vz_lev):
    eq = 1.0; lev = 3.0; prev_lev = 3.0
    pending = None; eql = []
    in_trade = False; trade_entry_eq = 1.0
    in_danger = False; vol_danger = False; trades = 0
    switch_today = False

    for i in range(len(idx)):
        d = idx[i]
        si = sep_state.loc[d]

        switch_today = False
        prev_lev_for_gap = lev
        if pending is not None:
            if pending != lev: switch_today = True
            lev = pending; pending = None

        is_profitable = (eq > trade_entry_eq) if in_trade else False
        z = z_series.loc[d] if d in z_series.index else np.nan

        tgt = 3
        if si == 0:
            tgt = 0; in_danger = False; vol_danger = False
        else:
            if not np.isnan(z):
                if not in_danger and z > Z_TRIGGER: in_danger = True
                elif in_danger and z < Z_RECOVER: in_danger = False
            vz = vol_z.iloc[i] if i < len(vol_z) else np.nan
            if not np.isnan(vz):
                if not vol_danger and vz > VZ_TRIGGER: vol_danger = True
                elif vol_danger and vz < VZ_RECOVER: vol_danger = False
            if in_danger:
                tgt = credit_lev if is_profitable else lev  # NSL
            elif vol_danger:
                tgt = vz_lev if is_profitable else lev  # NSL
            else:
                tgt = 3

        if tgt != lev: pending = tgt
        if lev > 0 and not in_trade: in_trade = True; trade_entry_eq = eq
        elif lev == 0 and in_trade: in_trade = False
        if lev != prev_lev: trades += 1

        if i > 0:
            r_total = dr_qqq.iloc[i]
            if np.isnan(r_total): r_total = 0.0
            if switch_today:
                rg = dr_qqq_gap.iloc[i]; ri = dr_qqq_intra.iloc[i]
                if np.isnan(rg): rg = 0.0
                if np.isnan(ri): ri = 0.0
                r_applied = (1 + prev_lev_for_gap * rg) * (1 + lev * ri) - 1
            else:
                r_applied = lev * r_total
            borrow = max(0, lev - 1) * effr.iloc[i] if lev > 1 else 0
            fee = EXPENSE_RATIO / 252 * min(lev / 3, 1) if lev > 1 else 0
            cy = effr.iloc[i] if lev == 0 else 0
            tc = abs(lev - prev_lev) * (TC_BPS / 10000)
            eq *= (1 + r_applied - borrow - fee + cy - tc)
            eq = max(eq, 0.001)

        prev_lev = lev; eql.append(eq)

    es = pd.Series(eql, index=idx)
    ny = len(es) / 252
    cagr = es.iloc[-1] ** (1/ny) - 1
    mdd = ((es / es.expanding().max()) - 1).min()
    daily_ret = es.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252) if daily_ret.std() > 0 else 0
    return round(cagr*100,1), round(mdd*100,1), round(sharpe,2), trades

# === 2D GRID SWEEP ===
credit_levels = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
vol_levels    = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]

print(f"\nSweeping {len(credit_levels)}×{len(vol_levels)} = {len(credit_levels)*len(vol_levels)} combos...", flush=True)

results = {}
for cl in credit_levels:
    for vl in vol_levels:
        cagr, mdd, sharpe, trades = run_backtest(cl, vl)
        results[(cl,vl)] = {'cagr':cagr, 'mdd':mdd, 'sharpe':sharpe, 'trades':trades}

# === PRINT ===
print("\n" + "="*80)
print("2D JOINT GRID — EXACT AUDIT ENGINE (SEP+NSL+Next-Open+Costs)")
print("="*80)

for metric, key, fmt in [("SHARPE", 'sharpe', '.2f'), ("CAGR", 'cagr', '.1f'), ("MDD", 'mdd', '.1f')]:
    print(f"\n── {metric} ──")
    print(f"{'':>12}", end='')
    for vl in vol_levels: print(f"  Vol={vl:.1f}x", end='')
    print()
    print("-"*(12+10*len(vol_levels)))
    for cl in credit_levels:
        print(f"Cred={cl:.1f}x |", end='')
        for vl in vol_levels:
            v = results[(cl,vl)][key]
            m = " ◄" if cl==1.0 and vl==2.0 else "  "
            if key == 'cagr' or key == 'mdd':
                print(f" {v:>5{fmt}}%{m}", end='')
            else:
                print(f"  {v:>5{fmt}}{m}", end='')
        print()

best = max(r['sharpe'] for r in results.values())
print(f"\n── PLATEAU (Sharpe within 0.05 of best {best:.2f}) ──")
plateau = [(cl,vl,results[(cl,vl)]) for cl in credit_levels for vl in vol_levels 
           if results[(cl,vl)]['sharpe'] >= best - 0.05]
plateau.sort(key=lambda x: -x[2]['sharpe'])
print(f"{'Credit':>8} {'Vol':>8} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'Trades':>8}")
print("-"*56)
for cl,vl,r in plateau:
    m = " ◄ CURRENT" if cl==1.0 and vl==2.0 else ""
    print(f"{cl:>7.1f}x {vl:>7.1f}x {r['sharpe']:>8.2f} {r['cagr']:>7.1f}% {r['mdd']:>7.1f}% {r['trades']:>8}{m}")

print(f"\nPlateau: {len(plateau)}/{len(results)} ({len(plateau)/len(results)*100:.0f}%)")
if plateau:
    print(f"Credit range: {min(p[0] for p in plateau):.1f}x – {max(p[0] for p in plateau):.1f}x")
    print(f"Vol range:    {min(p[1] for p in plateau):.1f}x – {max(p[1] for p in plateau):.1f}x")

cur = results.get((1.0, 2.0), {})
on = cur.get('sharpe',0) >= best - 0.05
print(f"\nCurrent (Cred=1.0x, Vol=2.0x): Sharpe={cur.get('sharpe','?')}, on plateau: {'✅ YES' if on else '❌ NO'}")
