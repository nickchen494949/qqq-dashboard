#!/usr/bin/env python3
"""
Test: GBM hostile filter ON TOP of SEP-only strategy.
Compare: SEP alone vs SEP + GBM vs SEP + Z-score overlay vs full strategy.
"""
import os, sys, warnings
import numpy as np, pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, 'market_data', 'ml_cache')
sys.path.insert(0, os.path.join(PROJECT_DIR, 'tools'))

import strategy_engine as se
import yfinance as yf

def gy(t):
    p=os.path.join(DATA_DIR, f'yahoo_{t}.csv')
    if os.path.exists(p):
        s=pd.read_csv(p,index_col=0,parse_dates=True).squeeze()
        if len(s)>100: return s
    df=yf.download(t,start='2000-01-01',progress=False,auto_adjust=False)
    adj=df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
    if isinstance(adj,pd.DataFrame): adj=adj.iloc[:,0]
    adj.to_csv(p); return adj
def gf(s): return pd.read_csv(os.path.join(DATA_DIR, f'fred_{s}.csv'), index_col=0, parse_dates=True).squeeze()

# ═══════════════════════════════════
# LOAD ALL DATA (same as strategy_engine expects)
# ═══════════════════════════════════
print("Loading data...")
qqq = gy('QQQ')
hyg = gy('HYG'); ief = gy('IEF')
tip = gy('TIP'); tlt = gy('TLT')

from fredapi import Fred
fred = Fred(api_key=se.get_fred_api_key())

# EFFR
effr_path = os.path.join(DATA_DIR, 'fred_EFFR.csv')
if os.path.exists(effr_path):
    effr_raw = pd.read_csv(effr_path, index_col=0, parse_dates=True).squeeze()
else:
    effr_raw = fred.get_series('EFFR', observation_start='2005-01-01')
    effr_raw.to_csv(effr_path)

# Net Liquidity components
walcl_path = os.path.join(DATA_DIR, 'fred_WALCL.csv')
rrp_path = os.path.join(DATA_DIR, 'fred_RRPONTSYD.csv')
tga_path = os.path.join(DATA_DIR, 'fred_WTREGEN.csv')
for sid, path in [('WALCL', walcl_path), ('RRPONTSYD', rrp_path), ('WTREGEN', tga_path)]:
    if not os.path.exists(path):
        s = fred.get_series(sid, observation_start='2005-01-01')
        s.to_csv(path)
walcl = pd.read_csv(walcl_path, index_col=0, parse_dates=True).squeeze()
rrp = pd.read_csv(rrp_path, index_col=0, parse_dates=True).squeeze()
tga = pd.read_csv(tga_path, index_col=0, parse_dates=True).squeeze()

# Align daily
idx = qqq.dropna().index
idx = idx[idx >= '2012-01-01']  # SEP data starts ~2012
qqq_a = qqq.reindex(idx)
hyg_a = hyg.reindex(idx).ffill()
ief_a = ief.reindex(idx).ffill()
tip_a = tip.reindex(idx).ffill() if tip is not None else None
tlt_a = tlt.reindex(idx).ffill() if tlt is not None else None
effr_a = effr_raw.reindex(idx, method='ffill').ffill() / 36500  # daily decimal
walcl_a = walcl.resample('D').ffill().reindex(idx, method='ffill').ffill()
rrp_a = rrp.resample('D').ffill().reindex(idx, method='ffill').ffill()
tga_a = tga.resample('D').ffill().reindex(idx, method='ffill').ffill()

dr_qqq = qqq_a.pct_change()

# Compute signals
z_credit = se.compute_credit_z(hyg_a, ief_a)
vol_z = se.compute_vol_z(dr_qqq)
inf_z = se.compute_inflation_z(tip_a, tlt_a) if tip_a is not None else None
nl_z = se.compute_nl_z(walcl_a, rrp_a, tga_a)

# Parse SEP
sep_dir = os.path.join(PROJECT_DIR, 'fomc_sep')
if os.path.isdir(sep_dir):
    sep_raw = se.parse_sep_pdfs(sep_dir)
    sep_signals = se.build_sep_signals(sep_raw)
    sep_state, _ = se.build_sep_state(sep_signals, idx)
    print(f"  SEP signals loaded: {len(sep_signals)} meetings")
    print(f"  SEP OUT days: {(sep_state==0).sum()} ({(sep_state==0).mean()*100:.1f}%)")
else:
    print("  ERROR: sep_pdf directory not found!")
    sys.exit(1)

# No gap/intra split for simplicity (use total daily return)
dr_gap = None; dr_intra = None

print(f"  Index: {idx[0].strftime('%Y-%m-%d')} to {idx[-1].strftime('%Y-%m-%d')} ({len(idx)} days)")

# ═══════════════════════════════════
# BUILD GBM HOSTILE SIGNAL (walk-forward, no valuation)
# ═══════════════════════════════════
print("\nBuilding GBM hostile signal (walk-forward OOS)...")
vix = gf('VIXCLS'); credit_baa = gf('BAA10Y')
nfci = gf('NFCI'); t10y = gf('DGS10'); t10y2y = gf('T10Y2Y')

vix = vix.reindex(idx, method='ffill').ffill()
credit_baa = credit_baa.reindex(idx, method='ffill').ffill()
nfci = nfci.resample('D').ffill().reindex(idx, method='ffill').ffill()
t10y = t10y.reindex(idx, method='ffill').ffill()
t10y2y = t10y2y.reindex(idx, method='ffill').ffill()

qqq_w = qqq_a.resample('W-FRI').last().dropna()
spy = gy('SPY').reindex(idx).ffill()
spy_w = spy.resample('W-FRI').last().dropna()
widx = qqq_w.index

feat = pd.DataFrame(index=widx)
rv20 = dr_qqq.rolling(20).std()*np.sqrt(252)
rv60 = dr_qqq.rolling(60).std()*np.sqrt(252)
feat['rv_20d'] = rv20.resample('W-FRI').last().reindex(widx)
feat['rv_60d'] = rv60.resample('W-FRI').last().reindex(widx)
feat['rv_ratio'] = feat['rv_20d']/feat['rv_60d'].replace(0,np.nan)
vix_w = vix.resample('W-FRI').last().reindex(widx)
feat['vix'] = vix_w
feat['vix_z'] = (vix_w-vix_w.rolling(52).mean())/vix_w.rolling(52).std()
feat['vix_chg4w'] = vix_w-vix_w.shift(4)
cr_w = credit_baa.resample('W-FRI').last().reindex(widx)
feat['credit'] = cr_w
feat['credit_z'] = (cr_w-cr_w.rolling(52).mean())/cr_w.rolling(52).std()
feat['credit_chg4w'] = cr_w-cr_w.shift(4)
t10_w = t10y.resample('W-FRI').last().reindex(widx)
feat['t10y'] = t10_w
feat['curve'] = t10y2y.resample('W-FRI').last().reindex(widx)
feat['rate_chg4w'] = t10_w-t10_w.shift(4)
nfci_w = nfci.resample('W-FRI').last().reindex(widx)
feat['nfci'] = nfci_w
feat['nfci_chg4w'] = nfci_w-nfci_w.shift(4)
feat['mom_4w'] = qqq_w.pct_change(4)
feat['mom_13w'] = qqq_w.pct_change(13)
feat['mom_52w'] = qqq_w.pct_change(52)
sma200_w = qqq_a.rolling(200).mean().resample('W-FRI').last().reindex(widx)
feat['vs_sma200'] = qqq_w/sma200_w-1
feat['qqq_vs_spy'] = qqq_w.pct_change(13)-spy_w.pct_change(13).reindex(widx)
feat = feat.dropna()

# Target
fwd_mdd = pd.Series(dtype=float, index=widx)
for dt in widx:
    fut = qqq_a.loc[qqq_a.index > dt].head(22)
    if len(fut)<10: continue
    pk = fut.cummax(); fwd_mdd[dt] = (fut/pk-1).min()
fwd_mdd = fwd_mdd.reindex(feat.index)
valid = fwd_mdd.notna()
feat = feat.loc[valid]; fwd_mdd = fwd_mdd.loc[valid]
fwd_hostile = (fwd_mdd<-0.05).astype(int)

# Walk-forward
X = feat.values
MIN_TRAIN=3*52; STEP=26; EMBARGO=5
preds=[]; dates=[]
te=MIN_TRAIN
while te+EMBARGO+STEP<=len(X):
    tr=list(range(te)); ts=te+EMBARGO; ti=list(range(ts,min(ts+STEP,len(X))))
    sc=StandardScaler(); Xtr=sc.fit_transform(X[tr]); Xte=sc.transform(X[ti])
    m=GradientBoostingClassifier(n_estimators=150,max_depth=3,learning_rate=0.05,subsample=0.8,random_state=42)
    m.fit(Xtr, fwd_hostile.values[tr])
    p=m.predict(Xte)
    preds.extend(p); dates.extend(feat.index[ti])
    te+=STEP

gbm_weekly = pd.Series(preds, index=dates).sort_index()
gbm_daily = gbm_weekly.reindex(idx, method='ffill').shift(1)  # shift(1)!
gbm_daily = gbm_daily.fillna(0).astype(int)

print(f"  GBM hostile days: {(gbm_daily==1).sum()} ({(gbm_daily==1).mean()*100:.1f}%)")
print(f"  GBM OOS from: {gbm_weekly.index[0].strftime('%Y-%m-%d')}")

# ═══════════════════════════════════
# RUN 4 STRATEGIES
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  RUNNING 4 STRATEGY VARIANTS")
print("="*100)

# Trim to GBM OOS period for fair comparison
gbm_start = gbm_weekly.index[0]
common_idx = idx[idx >= gbm_start]
dr_qqq_c = dr_qqq.reindex(common_idx)
effr_c = effr_a.reindex(common_idx)
z_c = z_credit.reindex(common_idx)
vz_c = vol_z.reindex(common_idx)
iz_c = inf_z.reindex(common_idx) if inf_z is not None else None
nlz_c = nl_z.reindex(common_idx)
sep_c = sep_state.reindex(common_idx)

def run_bt(label, use_sep, use_overlay, gbm_override=False):
    """Run backtest, optionally with GBM hostile override."""
    # If GBM, modify sep_state: when GBM says hostile AND sep says IN → force to 0
    if gbm_override:
        gbm_c = gbm_daily.reindex(common_idx).fillna(0).astype(int)
        # GBM hostile → set sep to 0 (exit market) only when SEP is IN
        modified_sep = sep_c.copy()
        modified_sep = modified_sep.where(gbm_c != 1, 0)  # when gbm hostile, force sep=0
        
        r = se.run_backtest(
            common_idx, dr_qqq_c, None, None, effr_c,
            z_c, vz_c, modified_sep,
            inf_z=iz_c, nl_z=nlz_c,
            use_sep=use_sep, use_overlay=use_overlay,
        )
    else:
        r = se.run_backtest(
            common_idx, dr_qqq_c, None, None, effr_c,
            z_c, vz_c, sep_c,
            inf_z=iz_c, nl_z=nlz_c,
            use_sep=use_sep, use_overlay=use_overlay,
        )
    
    eq = r['equity']
    ny = len(eq)/252
    cagr = (eq.iloc[-1]**(1/ny)-1)*100
    mdd = ((eq/eq.expanding().max())-1).min()*100
    daily_ret = eq.pct_change().dropna()
    sharpe = daily_ret.mean()/daily_ret.std()*np.sqrt(252) if daily_ret.std()>0 else 0
    dn = daily_ret[daily_ret<0]
    ds = np.sqrt((dn**2).mean()) if len(dn)>0 else 1e-10
    sortino = daily_ret.mean()/ds*np.sqrt(252)
    trades = r['trades']
    
    return {'label':label, 'cagr':cagr, 'mdd':mdd, 'sharpe':sharpe, 'sortino':sortino, 'trades':trades, 'equity':eq}

# 1. SEP only (no overlay)
r1 = run_bt('SEP only', use_sep=True, use_overlay=False)

# 2. SEP + GBM hostile (no Z-score overlay)
r2 = run_bt('SEP + GBM hostile', use_sep=True, use_overlay=False, gbm_override=True)

# 3. SEP + Z-score overlay (your current strategy)
r3 = run_bt('SEP + Z-score (current)', use_sep=True, use_overlay=True)

# 4. SEP + Z-score + GBM hostile
r4 = run_bt('SEP + Z-score + GBM', use_sep=True, use_overlay=True, gbm_override=True)

# 5. BH 3x
r5_eq = np.cumprod(1 + 3*dr_qqq_c.fillna(0).values)
r5_eq = pd.Series(r5_eq, index=common_idx)
ny5 = len(r5_eq)/252
r5 = {'label':'BH 3x','cagr':(r5_eq.iloc[-1]**(1/ny5)-1)*100,'mdd':((r5_eq/r5_eq.expanding().max())-1).min()*100,
      'sharpe':r5_eq.pct_change().dropna().mean()/r5_eq.pct_change().dropna().std()*np.sqrt(252),'sortino':0,'trades':0}

print(f"\n  Period: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")
print(f"\n  {'Strategy':<30} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sortino':>8} {'Trades':>7}")
print(f"  {'─'*30} {'─'*7} {'─'*7} {'─'*7} {'─'*8} {'─'*7}")
for r in [r1, r2, r3, r4, r5]:
    so = f"{r['sortino']:>8.2f}" if 'sortino' in r and r['sortino'] else '     N/A'
    print(f"  {r['label']:<30} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {so} {r['trades']:>7}")

# Year by year: SEP only vs SEP+GBM
print(f"\n  YEAR-BY-YEAR: SEP only vs SEP + GBM hostile")
print(f"  {'Year':>6} {'SEP':>8} {'SEP+GBM':>9} {'Diff':>7}")
print(f"  {'─'*6} {'─'*8} {'─'*9} {'─'*7}")
for y in sorted(set(common_idx.year)):
    m = common_idx.year == y
    if m.sum()<50: continue
    e1 = r1['equity'].loc[common_idx[m]]; e2 = r2['equity'].loc[common_idx[m]]
    c1 = (e1.iloc[-1]/e1.iloc[0]-1)*100; c2 = (e2.iloc[-1]/e2.iloc[0]-1)*100
    d = c2-c1
    v = '✅' if d>3 else ('❌' if d<-3 else '—')
    print(f"  {y:>6} {c1:>+7.1f}% {c2:>+8.1f}% {d:>+6.1f}% {v}")

print(f"\n  CONCLUSION:")
if r2['cagr'] > r1['cagr'] and r2['sharpe'] > r1['sharpe']:
    print(f"  ✅ GBM hostile IMPROVES SEP-only: CAGR {r2['cagr']-r1['cagr']:+.1f}%, Sharpe {r2['sharpe']-r1['sharpe']:+.2f}")
elif r2['sharpe'] > r1['sharpe']:
    print(f"  ⚠️  GBM hostile improves Sharpe ({r2['sharpe']-r1['sharpe']:+.2f}) but hurts CAGR ({r2['cagr']-r1['cagr']:+.1f}%)")
else:
    print(f"  ❌ GBM hostile does NOT improve SEP-only")

if r4['sharpe'] > r3['sharpe']:
    print(f"  ✅ Adding GBM to full strategy improves Sharpe: {r4['sharpe']-r3['sharpe']:+.2f}")
else:
    print(f"  ❌ Adding GBM to full strategy does NOT help")
