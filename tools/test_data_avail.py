#!/usr/bin/env python3
"""Comprehensive data availability test for risk indicators."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy_engine import get_fred_api_key
from fredapi import Fred
import yfinance as yf
import pandas as pd
import numpy as np

fred = Fred(api_key=get_fred_api_key())

# ============================================================
# SECTION 1: VALUATION
# ============================================================
print("=" * 70)
print("SECTION 1: VALUATION")
print("=" * 70)

# 1a. yfinance P/E
for sym in ['QQQ', 'SPY', '^NDX']:
    try:
        t = yf.Ticker(sym)
        info = t.info
        fields = ['trailingPE','forwardPE','priceToBook','trailingEps','forwardEps','pegRatio']
        vals = {f: info.get(f, 'N/A') for f in fields}
        print(f'  {sym} .info: {vals}')
    except Exception as e:
        print(f'  {sym} .info ERROR: {str(e)[:80]}')

# 1b. FRED valuation series
for sid in ['DGS10', 'T10YIE', 'SP500_PE_RATIO_MONTH', 'CAPE']:
    try:
        d = fred.get_series(sid).dropna()
        print(f'  FRED {sid}: len={len(d)}, from={d.index[0].date()}, to={d.index[-1].date()}, last={d.iloc[-1]:.2f}')
    except Exception as e:
        print(f'  FRED {sid}: ERROR - {str(e)[:80]}')

# 1c. Real yield
try:
    dgs10 = fred.get_series('DGS10').dropna()
    t10yie = fred.get_series('T10YIE').dropna()
    ry = (dgs10 - t10yie).dropna()
    print(f'  Real Yield (DGS10-T10YIE): len={len(ry)}, from={ry.index[0].date()}, to={ry.index[-1].date()}, last={ry.iloc[-1]:.2f}%')
except Exception as e:
    print(f'  Real Yield ERROR: {e}')

# ============================================================
# SECTION 2: EARNINGS
# ============================================================
print("\n" + "=" * 70)
print("SECTION 2: EARNINGS")
print("=" * 70)

# 2a. FRED corporate profits
for sid in ['CP', 'CPATAX', 'A053RC1Q027SBEA', 'W398RC1Q027SBEA', 'BOGZ1FA106060005Q']:
    try:
        d = fred.get_series(sid).dropna()
        print(f'  FRED {sid}: len={len(d)}, from={d.index[0].date()}, to={d.index[-1].date()}, last={d.iloc[-1]:.2f}')
    except Exception as e:
        print(f'  FRED {sid}: ERROR - {str(e)[:80]}')

# 2b. yfinance earnings
for sym in ['QQQ', 'SPY', 'SOXX']:
    try:
        t = yf.Ticker(sym)
        for attr in ['earnings', 'quarterly_earnings', 'earnings_history']:
            try:
                val = getattr(t, attr, None)
                if val is not None and hasattr(val, '__len__') and len(val) > 0:
                    print(f'  {sym} .{attr}: {len(val)} rows')
                else:
                    print(f'  {sym} .{attr}: empty/None')
            except Exception as e:
                print(f'  {sym} .{attr}: ERROR - {str(e)[:60]}')
    except Exception as e:
        print(f'  {sym} ERROR: {str(e)[:80]}')

# 2c. SOXX price history
try:
    soxx = yf.download('SOXX', start='2000-01-01', progress=False)
    print(f'  SOXX price: {len(soxx)} rows, from={soxx.index[0].date()}, to={soxx.index[-1].date()}')
except Exception as e:
    print(f'  SOXX price ERROR: {e}')

# ============================================================
# SECTION 3: CONCENTRATION
# ============================================================
print("\n" + "=" * 70)
print("SECTION 3: CONCENTRATION")
print("=" * 70)

# 3a. Equal weight ETFs
for sym in ['QQQE', 'QQEW']:
    try:
        d = yf.download(sym, start='2000-01-01', progress=False)
        if len(d) > 0:
            print(f'  {sym}: {len(d)} rows, from={d.index[0].date()}, to={d.index[-1].date()}')
        else:
            print(f'  {sym}: NO DATA')
    except Exception as e:
        print(f'  {sym} ERROR: {e}')

# 3b. SOXX
try:
    d = yf.download('SOXX', start='2000-01-01', progress=False)
    print(f'  SOXX: {len(d)} rows, from={d.index[0].date()}, to={d.index[-1].date()}')
except Exception as e:
    print(f'  SOXX ERROR: {e}')

# 3c. Mag7 stocks
mag7 = ['NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA']
try:
    mag7_data = yf.download(mag7 + ['QQQ'], start='2000-01-01', progress=False)
    close = mag7_data['Close']
    for sym in mag7 + ['QQQ']:
        col = close[sym].dropna()
        if len(col) > 0:
            print(f'  {sym}: {len(col)} rows, from={col.index[0].date()}, to={col.index[-1].date()}')
        else:
            print(f'  {sym}: NO DATA')
except Exception as e:
    print(f'  Mag7 ERROR: {e}')

# 3d. QQQ/QQEW concentration ratio
try:
    qqq_c = yf.download('QQQ', start='2000-01-01', progress=False)['Close'].squeeze()
    qqew_c = yf.download('QQEW', start='2000-01-01', progress=False)['Close'].squeeze()
    if len(qqew_c) > 0:
        ratio = (qqq_c / qqew_c).dropna()
        print(f'  QQQ/QQEW ratio: {len(ratio)} pts, from={ratio.index[0].date()}, to={ratio.index[-1].date()}, last={ratio.iloc[-1]:.4f}')
except Exception as e:
    print(f'  QQQ/QQEW ratio ERROR: {e}')

# ============================================================
# SECTION 4: LIQUIDITY
# ============================================================
print("\n" + "=" * 70)
print("SECTION 4: LIQUIDITY (FRED)")
print("=" * 70)

liq_series = {
    'RRPONTSYD': 'Overnight Reverse Repo',
    'WTREGEN': 'Treasury General Account',
    'TOTRESNS': 'Total Reserves',
    'WRESBAL': 'Reserve Balances',
    'STLFSI2': 'STL Financial Stress v2',
    'STLFSI4': 'STL Financial Stress v4',
    'NFCI': 'National Financial Conditions',
    'SOFR': 'Secured Overnight Financing Rate',
    'IORB': 'Interest on Reserve Balances',
    'WM2NS': 'M2 Weekly NSA',
    'M2SL': 'M2 Monthly SA',
    'WALCL': 'Fed Total Assets',
    'EFFR': 'Effective Fed Funds Rate',
    'BAMLH0A0HYM2': 'HY OAS Spread',
    'TEDRATE': 'TED Spread',
    'T10Y2Y': '10Y-2Y Spread',
    'T10Y3M': '10Y-3M Spread',
    'VIXCLS': 'VIX',
    'ANFCI': 'Adjusted NFCI',
    'DTWEXBGS': 'Trade Weighted USD',
    'STLFSI3': 'STL Financial Stress v3',
}

for sid, desc in liq_series.items():
    try:
        d = fred.get_series(sid).dropna()
        if len(d) > 0:
            avg_gap = (d.index[-1] - d.index[0]).days / max(len(d)-1, 1)
            freq = 'D' if avg_gap < 3 else 'W' if avg_gap < 10 else 'M' if avg_gap < 60 else 'Q'
            print(f'  OK  {sid:20s} {freq:2s} {len(d):6d}pts {d.index[0].date()} -> {d.index[-1].date()} last={d.iloc[-1]:.2f} | {desc}')
        else:
            print(f'  --  {sid:20s} EMPTY | {desc}')
    except Exception as e:
        print(f'  ERR {sid:20s} {str(e)[:60]} | {desc}')

# ============================================================
# SECTION 5: TQQQ TRACKING
# ============================================================
print("\n" + "=" * 70)
print("SECTION 5: TQQQ TRACKING QUALITY")
print("=" * 70)

tqqq = yf.download('TQQQ', start='2010-01-01', progress=False)
qqq = yf.download('QQQ', start='2010-01-01', progress=False)
print(f'  TQQQ: {len(tqqq)} rows, from={tqqq.index[0].date()}, to={tqqq.index[-1].date()}')
print(f'  QQQ:  {len(qqq)} rows, from={qqq.index[0].date()}, to={qqq.index[-1].date()}')

tqqq_c = tqqq['Close'].squeeze()
qqq_c = qqq['Close'].squeeze()
ci = tqqq_c.index.intersection(qqq_c.index)
tqqq_r = tqqq_c.loc[ci].pct_change().dropna()
qqq_r = qqq_c.loc[ci].pct_change().dropna()
ci2 = tqqq_r.index.intersection(qqq_r.index)
tqqq_r = tqqq_r.loc[ci2]
qqq_r = qqq_r.loc[ci2]
syn3x = 3 * qqq_r
diff = tqqq_r - syn3x

print(f'  Common days: {len(tqqq_r)}, from={ci2[0].date()}, to={ci2[-1].date()}')
print(f'  Tracking diff mean:   {diff.mean()*10000:.2f} bps/day')
print(f'  Tracking diff std:    {diff.std()*10000:.2f} bps/day')
print(f'  Tracking error (ann): {diff.std()*np.sqrt(252)*100:.2f}%')
print(f'  Correlation(TQQQ, 3xQQQ): {tqqq_r.corr(syn3x):.6f}')

slope = np.polyfit(qqq_r, tqqq_r, 1)[0]
print(f'  Regression slope: {slope:.4f} (target=3.0)')

cum_tqqq = (1 + tqqq_r).cumprod().iloc[-1]
cum_3x = (1 + syn3x).cumprod().iloc[-1]
print(f'  Cumulative TQQQ: {cum_tqqq:.4f}x, Synthetic 3x: {cum_3x:.4f}x')
print(f'  Cumulative drift: {(cum_tqqq/cum_3x - 1)*100:.2f}%')

# Year-by-year
print(f'\n  Year  | TQQQ Ret  | 3x QQQ  | Drift   | TE(ann)')
print(f'  ------+-----------+---------+---------+--------')
for yr in range(tqqq_r.index[0].year, tqqq_r.index[-1].year + 1):
    m = tqqq_r.index.year == yr
    if m.sum() < 20: continue
    tr = (1+tqqq_r[m]).cumprod().iloc[-1]-1
    sr = (1+syn3x[m]).cumprod().iloc[-1]-1
    te = diff[m].std()*np.sqrt(252)*100
    print(f'  {yr}  | {tr*100:8.2f}% | {sr*100:6.2f}% | {(tr-sr)*100:6.2f}% | {te:.2f}%')

print("\n\nALL TESTS COMPLETE")
