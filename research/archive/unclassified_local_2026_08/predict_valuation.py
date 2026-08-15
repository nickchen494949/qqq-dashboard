#!/usr/bin/env python3
"""
Get REAL valuation data + re-run prediction with ALL factors.
Sources:
- Shiller CAPE from his website (Excel)
- Buffett Indicator from FRED (market cap / GDP)
- Corporate earnings yield from FRED
- Dividend yield from yfinance
"""
import os, sys, warnings
import numpy as np, pandas as pd
import yfinance as yf
from fredapi import Fred
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.metrics import accuracy_score, balanced_accuracy_score, matthews_corrcoef, r2_score, mean_absolute_error, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, 'market_data', 'ml_cache')
sys.path.insert(0, os.path.join(PROJECT_DIR, 'tools'))
from strategy_engine import get_fred_api_key

fred = Fred(api_key=get_fred_api_key())

def get_fred(sid):
    path = os.path.join(DATA_DIR, f'fred_{sid}.csv')
    if os.path.exists(path):
        s = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
        if len(s) > 20: return s
    s = fred.get_series(sid, observation_start='2000-01-01').dropna()
    s.to_csv(path); return s

def get_yahoo(t):
    path = os.path.join(DATA_DIR, f'yahoo_{t}.csv')
    if os.path.exists(path):
        s = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
        if len(s) > 100: return s
    df = yf.download(t, start='2000-01-01', progress=False, auto_adjust=False)
    adj = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
    if isinstance(adj, pd.DataFrame): adj = adj.iloc[:,0]
    adj.to_csv(path); return adj

# ═══════════════════════════════════
# 1. LOAD ALL DATA
# ═══════════════════════════════════
print("=" * 90)
print("  LOADING ALL DATA — valuation + rates + credit + vol + momentum")
print("=" * 90)

# Prices
qqq = get_yahoo('QQQ')
spy = get_yahoo('SPY')

# FRED macro
vix = get_fred('VIXCLS')
credit = get_fred('BAA10Y')        # Moody's BAA - 10Y spread
nfci = get_fred('NFCI')            # Financial conditions
t10y = get_fred('DGS10')
t2y = get_fred('DGS2')
t10y2y = get_fred('T10Y2Y')

# FRED valuation
corp_profits = get_fred('CP')              # Corporate profits (quarterly)
mkt_cap = get_fred('NCBEILQ027S')          # Corporate equities market value (quarterly)  
gdp = get_fred('GDP')                       # GDP (quarterly)

print("\n  Fetching Shiller CAPE data...")
cape_path = os.path.join(DATA_DIR, 'shiller_cape.csv')
if os.path.exists(cape_path):
    cape_df = pd.read_csv(cape_path, index_col=0, parse_dates=True)
else:
    # Download from Shiller's website
    url = 'http://www.econ.yale.edu/~shiller/data/ie_data.xls'
    try:
        cape_raw = pd.read_excel(url, sheet_name='Data', skiprows=7)
        # Date column is in format like 2020.01
        dates = cape_raw.iloc[:, 0].dropna()
        cape_vals = cape_raw.iloc[:, -1].dropna()  # CAPE is last column
        # Build date index
        date_idx = []
        for d in dates:
            try:
                yr = int(float(d))
                mo = int(round((float(d) - yr) * 100))
                if mo == 0: mo = 1
                if mo > 12: mo = 12
                date_idx.append(pd.Timestamp(yr, mo, 1))
            except:
                continue
        cape_series = pd.Series(cape_vals.values[:len(date_idx)], index=date_idx, name='CAPE')
        cape_df = cape_series.to_frame()
        cape_df.to_csv(cape_path)
        print(f"  CAPE downloaded: {cape_df.index[0]} to {cape_df.index[-1]}")
    except Exception as e:
        print(f"  CAPE download failed: {e}, computing from P/E proxy")
        cape_df = None

# Compute valuation metrics
print("\n  Computing valuation metrics...")

# 1. Buffett Indicator = Market Cap / GDP
buffett = (mkt_cap / gdp).dropna()
buffett.name = 'buffett'
print(f"  Buffett Indicator: {buffett.index[0].strftime('%Y-%m')} to {buffett.index[-1].strftime('%Y-%m')}, {len(buffett)} quarters")

# 2. Earnings yield = Corporate Profits / Market Cap
earnings_yield = (corp_profits / mkt_cap).dropna()
earnings_yield.name = 'earnings_yield'
print(f"  Earnings Yield: {earnings_yield.index[0].strftime('%Y-%m')} to {earnings_yield.index[-1].strftime('%Y-%m')}, {len(earnings_yield)} quarters")

# 3. Equity risk premium = Earnings Yield - 10Y Treasury
t10y_q = t10y.resample('QS').mean() / 100  # quarterly, decimal
erp = earnings_yield.reindex(t10y_q.index, method='ffill') - t10y_q
erp = erp.dropna()
erp.name = 'erp'
print(f"  Equity Risk Premium: {erp.index[0].strftime('%Y-%m')} to {erp.index[-1].strftime('%Y-%m')}, {len(erp)} quarters")

# 4. CAPE (if available)
if cape_df is not None and len(cape_df) > 0:
    cape_s = cape_df.iloc[:, 0].dropna()
    cape_s = cape_s[cape_s.index >= '2000-01-01']
    print(f"  CAPE: {cape_s.index[0].strftime('%Y-%m')} to {cape_s.index[-1].strftime('%Y-%m')}, {len(cape_s)} months")
else:
    cape_s = None

# ═══════════════════════════════════
# 2. BUILD WEEKLY FEATURES
# ═══════════════════════════════════
print("\n  Building weekly features...")

idx = qqq.dropna().index
idx = idx[idx >= '2005-01-01']
qqq = qqq.reindex(idx); spy = spy.reindex(idx).ffill()
vix = vix.reindex(idx, method='ffill').ffill()
credit = credit.reindex(idx, method='ffill').ffill()
nfci = nfci.resample('D').ffill().reindex(idx, method='ffill').ffill()
t10y = t10y.reindex(idx, method='ffill').ffill()
t2y = t2y.reindex(idx, method='ffill').ffill()
t10y2y = t10y2y.reindex(idx, method='ffill').ffill()

# Resample quarterly valuation to daily (forward fill)
buffett_d = buffett.resample('D').ffill().reindex(idx, method='ffill').ffill()
ey_d = earnings_yield.resample('D').ffill().reindex(idx, method='ffill').ffill()
erp_d = erp.resample('D').ffill().reindex(idx, method='ffill').ffill()
if cape_s is not None:
    cape_d = cape_s.resample('D').ffill().reindex(idx, method='ffill').ffill()
else:
    cape_d = None

qqq_ret_d = qqq.pct_change()
qqq_w = qqq.resample('W-FRI').last().dropna()
spy_w = spy.resample('W-FRI').last().dropna()
widx = qqq_w.index

feat = pd.DataFrame(index=widx)

# ── Vol ──
rv20 = qqq_ret_d.rolling(20).std() * np.sqrt(252)
rv60 = qqq_ret_d.rolling(60).std() * np.sqrt(252)
feat['rv_20d'] = rv20.resample('W-FRI').last().reindex(widx)
feat['rv_60d'] = rv60.resample('W-FRI').last().reindex(widx)
feat['rv_ratio'] = feat['rv_20d'] / feat['rv_60d'].replace(0, np.nan)

# ── VIX ──
vix_w = vix.resample('W-FRI').last().reindex(widx)
feat['vix'] = vix_w
feat['vix_z'] = (vix_w - vix_w.rolling(52).mean()) / vix_w.rolling(52).std()
feat['vix_chg4w'] = vix_w - vix_w.shift(4)

# ── Credit ──
cr_w = credit.resample('W-FRI').last().reindex(widx)
feat['credit'] = cr_w
feat['credit_z'] = (cr_w - cr_w.rolling(52).mean()) / cr_w.rolling(52).std()
feat['credit_chg4w'] = cr_w - cr_w.shift(4)

# ── Rates ──
t10_w = t10y.resample('W-FRI').last().reindex(widx)
feat['t10y'] = t10_w
feat['curve'] = t10y2y.resample('W-FRI').last().reindex(widx)
feat['rate_chg4w'] = t10_w - t10_w.shift(4)

# ── NFCI ──
nfci_w = nfci.resample('W-FRI').last().reindex(widx)
feat['nfci'] = nfci_w
feat['nfci_chg4w'] = nfci_w - nfci_w.shift(4)

# ── Momentum ──
feat['mom_4w'] = qqq_w.pct_change(4)
feat['mom_13w'] = qqq_w.pct_change(13)
feat['mom_52w'] = qqq_w.pct_change(52)

sma200_w = qqq.rolling(200).mean().resample('W-FRI').last().reindex(widx)
feat['vs_sma200'] = qqq_w / sma200_w - 1
feat['qqq_vs_spy'] = qqq_w.pct_change(13) - spy_w.pct_change(13).reindex(widx)

# ── VALUATION (THE REAL STUFF) ──
feat['buffett'] = buffett_d.resample('W-FRI').last().reindex(widx)
feat['buffett_z'] = (feat['buffett'] - feat['buffett'].rolling(52).mean()) / feat['buffett'].rolling(52).std()
feat['earnings_yield'] = ey_d.resample('W-FRI').last().reindex(widx)
feat['erp'] = erp_d.resample('W-FRI').last().reindex(widx)
if cape_d is not None:
    feat['cape'] = cape_d.resample('W-FRI').last().reindex(widx)
    feat['cape_z'] = (feat['cape'] - feat['cape'].rolling(52).mean()) / feat['cape'].rolling(52).std()

# Price vs 4-year MA (rough valuation)
feat['price_vs_trend'] = qqq_w / qqq_w.rolling(208).mean() - 1

feat = feat.dropna()
print(f"  Features: {len(feat)} weeks, {feat.shape[1]} features")
print(f"  Range: {feat.index[0].strftime('%Y-%m')} to {feat.index[-1].strftime('%Y-%m')}")
print(f"  Features: {list(feat.columns)}")

# ═══════════════════════════════════
# 3. TARGETS
# ═══════════════════════════════════
fwd_ret = qqq_w.shift(-4) / qqq_w - 1
fwd_rv = pd.Series(dtype=float, index=widx)
fwd_mdd = pd.Series(dtype=float, index=widx)
for dt in widx:
    fut = qqq.loc[qqq.index > dt].head(22)
    if len(fut) < 10: continue
    fr = fut.pct_change().dropna()
    if len(fr) >= 5: fwd_rv[dt] = fr.std() * np.sqrt(252)
    pk = fut.cummax()
    fwd_mdd[dt] = (fut / pk - 1).min()

fwd_ret = fwd_ret.reindex(feat.index)
fwd_rv = fwd_rv.reindex(feat.index)
fwd_mdd = fwd_mdd.reindex(feat.index)

valid = fwd_ret.notna() & fwd_rv.notna() & fwd_mdd.notna()
feat = feat.loc[valid]; fwd_ret = fwd_ret.loc[valid]
fwd_rv = fwd_rv.loc[valid]; fwd_mdd = fwd_mdd.loc[valid]
fwd_dir = (fwd_ret > 0).astype(int)
fwd_hostile = (fwd_mdd < -0.05).astype(int)

print(f"\n  Final: {len(feat)} weeks | Up: {fwd_dir.mean():.1%} | Hostile: {fwd_hostile.mean():.1%}")

# ═══════════════════════════════════
# 4. WALK-FORWARD
# ═══════════════════════════════════
X = feat.values
fnames = list(feat.columns)
MIN_TRAIN = 3*52; STEP = 26; EMBARGO = 5

def wf(y, clf=True):
    res = []
    te = MIN_TRAIN
    while te + EMBARGO + STEP <= len(X):
        tr = list(range(te)); ts = te+EMBARGO; ti = list(range(ts, min(ts+STEP, len(X))))
        sc = StandardScaler(); Xtr = sc.fit_transform(X[tr]); Xte = sc.transform(X[ti])
        if clf:
            m = GradientBoostingClassifier(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=42)
        else:
            m = GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=42)
        m.fit(Xtr, y[tr]); p = m.predict(Xte)
        res.append({'actual':y[ti], 'pred':p, 'dates':feat.index[ti], 'fi':dict(zip(fnames, m.feature_importances_))})
        te += STEP
    return res

print(f"\n{'='*90}")
print(f"  WALK-FORWARD OOS — WITH REAL VALUATION DATA")
print(f"  {len(feat)} weeks, {feat.shape[1]} features including valuation")
print(f"{'='*90}")

# Direction
print(f"\n{'━'*90}")
print(f"  TARGET 1: DIRECTION")
print(f"{'━'*90}")
r1 = wf(fwd_dir.values, clf=True)
if r1:
    a1=np.concatenate([r['actual'] for r in r1]); p1=np.concatenate([r['pred'] for r in r1])
    bl1=a1.mean(); acc1=accuracy_score(a1,p1); mcc1=matthews_corrcoef(a1,p1)
    bacc1=balanced_accuracy_score(a1,p1)
    print(f"  Baseline: {bl1:.1%} | Acc: {acc1:.1%} | BalAcc: {bacc1:.1%} | MCC: {mcc1:+.3f}")
    print(f"  Edge: {(acc1-bl1)*100:+.1f}pp | {'✅' if acc1>bl1+0.03 else '❌'}")
    fi1 = {f: np.mean([r['fi'].get(f,0) for r in r1]) for f in fnames}
    top = sorted(fi1, key=fi1.get, reverse=True)[:7]
    print(f"  Top: {', '.join(f'{f}({fi1[f]:.2f})' for f in top)}")
else:
    print("  No folds!"); acc1=0; bl1=1; mcc1=0

# Volatility
print(f"\n{'━'*90}")
print(f"  TARGET 2: FORWARD VOL")
print(f"{'━'*90}")
r2 = wf(fwd_rv.values, clf=False)
if r2:
    a2=np.concatenate([r['actual'] for r in r2]); p2=np.concatenate([r['pred'] for r in r2])
    r2_ml=r2_score(a2,p2); corr2=np.corrcoef(a2,p2)[0,1]
    # naive
    naive = []; te=MIN_TRAIN
    while te+EMBARGO+STEP<=len(X):
        ts=te+EMBARGO; ti=list(range(ts,min(ts+STEP,len(X))))
        naive.extend(feat['rv_20d'].values[ti]); te+=STEP
    naive=np.array(naive[:len(a2)]); r2_n=r2_score(a2,naive); corr_n=np.corrcoef(a2,naive)[0,1]
    print(f"  Naive: R²={r2_n:.3f} Corr={corr_n:.3f} | ML: R²={r2_ml:.3f} Corr={corr2:.3f}")
    print(f"  {'✅' if r2_ml>0.1 else '❌'} Improvement: {r2_ml-r2_n:+.3f}")
    fi2 = {f: np.mean([r['fi'].get(f,0) for r in r2]) for f in fnames}
    top = sorted(fi2, key=fi2.get, reverse=True)[:7]
    print(f"  Top: {', '.join(f'{f}({fi2[f]:.2f})' for f in top)}")
else:
    print("  No folds!"); r2_ml=0; r2_n=0

# Hostile
print(f"\n{'━'*90}")
print(f"  TARGET 3: HOSTILE (DD>5%)")
print(f"{'━'*90}")
r3 = wf(fwd_hostile.values, clf=True)
if r3:
    a3=np.concatenate([r['actual'] for r in r3]); p3=np.concatenate([r['pred'] for r in r3])
    bl3=1-a3.mean(); acc3=accuracy_score(a3,p3); mcc3=matthews_corrcoef(a3,p3)
    bacc3=balanced_accuracy_score(a3,p3)
    prec3=precision_score(a3,p3,zero_division=0); rec3=recall_score(a3,p3,zero_division=0)
    print(f"  Hostile: {a3.mean():.1%} | Base: {bl3:.1%} | Acc: {acc3:.1%} | BalAcc: {bacc3:.1%}")
    print(f"  MCC: {mcc3:+.3f} | Prec: {prec3:.1%} | Recall: {rec3:.1%}")
    print(f"  {'✅' if mcc3>0.15 else '❌'}")
    fi3 = {f: np.mean([r['fi'].get(f,0) for r in r3]) for f in fnames}
    top = sorted(fi3, key=fi3.get, reverse=True)[:7]
    print(f"  Top: {', '.join(f'{f}({fi3[f]:.2f})' for f in top)}")
else:
    print("  No folds!"); mcc3=0; acc3=0; bl3=1; prec3=0; rec3=0

# ═══════════════════════════════════
# 5. STRATEGY PNL
# ═══════════════════════════════════
if r1 and r2 and r3:
    print(f"\n{'━'*90}")
    print(f"  STRATEGY BACKTEST")
    print(f"{'━'*90}")
    preds = {}
    for lb, res in [('dir',r1),('vol',r2),('hostile',r3)]:
        dates = np.concatenate([r['dates'] for r in res])
        vals = np.concatenate([r['pred'] for r in res])
        preds[lb] = pd.Series(vals, index=dates).sort_index()
    pdf = pd.DataFrame(preds)
    dr = qqq.pct_change().dropna()
    pd2 = pdf.reindex(dr.index, method='ffill').dropna()
    d = dr.loc[pd2.index].values

    def st(r,n):
        eq=np.cumprod(1+r); ny=len(r)/252
        cagr=(eq[-1]**(1/ny)-1)*100 if eq[-1]>0 else -99
        mdd=(eq/np.maximum.accumulate(eq)-1).min()*100
        sh=np.mean(r)/np.std(r)*np.sqrt(252) if np.std(r)>0 else 0
        dn=r[r<0]; ds=np.sqrt(np.mean(dn**2)) if len(dn)>0 else 1e-10
        so=np.mean(r)/ds*np.sqrt(252)
        return f"  {n:<35} {cagr:>+6.1f}% {mdd:>6.1f}% {sh:>6.2f} {so:>7.2f}"

    l1=np.where(pd2['hostile']==1,1,3)
    l2=np.clip(0.20/pd2['vol'].clip(0.05,1).values,0.5,3)
    l3=np.where(pd2['hostile']==1,1,l2)

    print(f"\n  {'Strategy':<35} {'CAGR':>7} {'MDD':>7} {'Sharpe':>6} {'Sortino':>7}")
    print(f"  {'─'*35} {'─'*7} {'─'*7} {'─'*6} {'─'*7}")
    print(st(l1*d, 'Hostile→1x, else→3x'))
    print(st(l2*d, 'Vol-scaled'))
    print(st(l3*d, 'Combined'))
    print(st(3*d, 'Buy & Hold 3x'))
    print(st(d, 'Buy & Hold 1x'))

# FINAL
print(f"\n{'='*90}")
print(f"  FINAL ANSWER — WITH REAL VALUATION DATA")
print(f"{'='*90}")
print(f"""
  Features used ({feat.shape[1]}):
    Vol:       rv_20d, rv_60d, rv_ratio
    VIX:       vix, vix_z, vix_chg4w
    Credit:    BAA-10Y spread, z-score, 4w change
    Rates:     10Y, curve, rate change
    NFCI:      level, 4w change
    Momentum:  4w, 13w, 52w, vs SMA200, QQQ/SPY
    VALUATION: Buffett indicator, earnings yield, equity risk premium, 
               {'CAPE, CAPE z-score, ' if 'cape' in fnames else ''}price vs trend
""")
