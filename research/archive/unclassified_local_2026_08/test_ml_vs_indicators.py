#!/usr/bin/env python3
"""
Is it the ML or the indicators?
Test: feed ML the EXACT SAME indicators as Z-score strategy.
If ML + same indicators > Z-score → ML can find better rules
If ML + same indicators < Z-score → the hand-crafted rules are already optimal
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
from fredapi import Fred

fred = Fred(api_key=se.get_fred_api_key())
def gy(t):
    p=os.path.join(DATA_DIR, f'yahoo_{t}.csv')
    if os.path.exists(p):
        s=pd.read_csv(p,index_col=0,parse_dates=True).squeeze()
        if len(s)>100: return s
    df=yf.download(t,start='2000-01-01',progress=False,auto_adjust=False)
    adj=df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
    if isinstance(adj,pd.DataFrame): adj=adj.iloc[:,0]
    adj.to_csv(p); return adj
def gf(s):
    p=os.path.join(DATA_DIR,f'fred_{s}.csv')
    if os.path.exists(p): return pd.read_csv(p,index_col=0,parse_dates=True).squeeze()
    s2=fred.get_series(s,observation_start='2005-01-01'); s2.to_csv(p); return s2

# ═══════════════════════════════════
# LOAD
# ═══════════════════════════════════
print("Loading...")
qqq=gy('QQQ'); hyg=gy('HYG'); ief=gy('IEF')
tip=gy('TIP'); tlt=gy('TLT'); spy=gy('SPY')
vix=gf('VIXCLS'); credit_baa=gf('BAA10Y'); nfci=gf('NFCI')
t10y=gf('DGS10'); t10y2y=gf('T10Y2Y')
walcl=gf('WALCL'); rrp=gf('RRPONTSYD'); tga=gf('WTREGEN')
effr_raw=gf('EFFR')

idx=qqq.dropna().index; idx=idx[idx>='2012-01-01']
qqq_a=qqq.reindex(idx); spy_a=spy.reindex(idx).ffill()
hyg_a=hyg.reindex(idx).ffill(); ief_a=ief.reindex(idx).ffill()
tip_a=tip.reindex(idx).ffill(); tlt_a=tlt.reindex(idx).ffill()
vix_a=vix.reindex(idx,method='ffill').ffill()
credit_a=credit_baa.reindex(idx,method='ffill').ffill()
nfci_a=nfci.resample('D').ffill().reindex(idx,method='ffill').ffill()
t10y_a=t10y.reindex(idx,method='ffill').ffill()
t10y2y_a=t10y2y.reindex(idx,method='ffill').ffill()
walcl_a=walcl.resample('D').ffill().reindex(idx,method='ffill').ffill()
rrp_a=rrp.resample('D').ffill().reindex(idx,method='ffill').ffill()
tga_a=tga.resample('D').ffill().reindex(idx,method='ffill').ffill()
effr_a=effr_raw.reindex(idx,method='ffill').ffill()/36500

dr_qqq=qqq_a.pct_change()

# Compute YOUR z-score signals
z_credit=se.compute_credit_z(hyg_a, ief_a)
vol_z=se.compute_vol_z(dr_qqq)
inf_z=se.compute_inflation_z(tip_a, tlt_a)
nl_z=se.compute_nl_z(walcl_a, rrp_a, tga_a)

# SEP
sep_raw=se.parse_sep_pdfs(os.path.join(PROJECT_DIR,'fomc_sep'))
sep_signals=se.build_sep_signals(sep_raw)
sep_state,_=se.build_sep_state(sep_signals, idx)

# ═══════════════════════════════════
# BUILD 3 FEATURE SETS
# ═══════════════════════════════════
qqq_w=qqq_a.resample('W-FRI').last().dropna()
spy_w=spy_a.resample('W-FRI').last().dropna()
widx=qqq_w.index

# SET A: YOUR exact Z-score indicators (what the strategy uses)
feat_yours=pd.DataFrame(index=widx)
feat_yours['credit_z']=z_credit.resample('W-FRI').last().reindex(widx)
feat_yours['vol_z']=vol_z.resample('W-FRI').last().reindex(widx)
feat_yours['inf_z']=inf_z.resample('W-FRI').last().reindex(widx)
feat_yours['nl_z']=nl_z.resample('W-FRI').last().reindex(widx)

# SET B: YOUR indicators + audit v4 indicators (combined)
feat_combined=feat_yours.copy()
rv20=dr_qqq.rolling(20).std()*np.sqrt(252)
rv60=dr_qqq.rolling(60).std()*np.sqrt(252)
feat_combined['rv_20d']=rv20.resample('W-FRI').last().reindex(widx)
feat_combined['rv_60d']=rv60.resample('W-FRI').last().reindex(widx)
vix_w=vix_a.resample('W-FRI').last().reindex(widx)
feat_combined['vix']=vix_w
feat_combined['vix_chg4w']=vix_w-vix_w.shift(4)
cr_w=credit_a.resample('W-FRI').last().reindex(widx)
feat_combined['baa_spread']=cr_w
feat_combined['baa_chg4w']=cr_w-cr_w.shift(4)
t10_w=t10y_a.resample('W-FRI').last().reindex(widx)
feat_combined['t10y']=t10_w
feat_combined['curve']=t10y2y_a.resample('W-FRI').last().reindex(widx)
nfci_w=nfci_a.resample('W-FRI').last().reindex(widx)
feat_combined['nfci']=nfci_w
feat_combined['nfci_chg4w']=nfci_w-nfci_w.shift(4)
feat_combined['mom_4w']=qqq_w.pct_change(4)
feat_combined['mom_13w']=qqq_w.pct_change(13)
feat_combined['mom_52w']=qqq_w.pct_change(52)
sma200_w=qqq_a.rolling(200).mean().resample('W-FRI').last().reindex(widx)
feat_combined['vs_sma200']=qqq_w/sma200_w-1

# SET C: audit v4 features only (no your z-scores)
feat_audit=feat_combined.drop(columns=['credit_z','vol_z','inf_z','nl_z'])

# Drop NaN
feat_yours=feat_yours.dropna()
feat_combined=feat_combined.dropna()
feat_audit=feat_audit.dropna()

# Use intersection
common_widx=feat_yours.index.intersection(feat_combined.index).intersection(feat_audit.index)
feat_yours=feat_yours.loc[common_widx]
feat_combined=feat_combined.loc[common_widx]
feat_audit=feat_audit.loc[common_widx]

# Target
fwd_mdd=pd.Series(dtype=float,index=widx)
for dt in widx:
    fut=qqq_a.loc[qqq_a.index>dt].head(22)
    if len(fut)<10: continue
    pk=fut.cummax(); fwd_mdd[dt]=(fut/pk-1).min()
fwd_mdd=fwd_mdd.reindex(common_widx)
valid=fwd_mdd.notna()
feat_yours=feat_yours.loc[valid]; feat_combined=feat_combined.loc[valid]; feat_audit=feat_audit.loc[valid]
fwd_mdd=fwd_mdd.loc[valid]
fwd_hostile=(fwd_mdd<-0.05).astype(int)
common_widx=feat_yours.index

print(f"  {len(common_widx)} weeks, hostile={fwd_hostile.mean():.1%}")
print(f"  Set A (your z-scores): {feat_yours.shape[1]} features: {list(feat_yours.columns)}")
print(f"  Set B (combined): {feat_combined.shape[1]} features")
print(f"  Set C (audit only): {feat_audit.shape[1]} features")

# ═══════════════════════════════════
# Walk-forward for each feature set
# ═══════════════════════════════════
MIN_TRAIN=3*52; STEP=26; EMBARGO=5

def run_wf(feat_df, label):
    X=feat_df.values; y=fwd_hostile.values
    preds=[]; dates=[]
    te=MIN_TRAIN
    while te+EMBARGO+STEP<=len(X):
        tr=list(range(te)); ts=te+EMBARGO; ti=list(range(ts,min(ts+STEP,len(X))))
        sc=StandardScaler(); Xtr=sc.fit_transform(X[tr]); Xte=sc.transform(X[ti])
        m=GradientBoostingClassifier(n_estimators=150,max_depth=3,learning_rate=0.05,subsample=0.8,random_state=42)
        m.fit(Xtr,y[tr]); p=m.predict(Xte)
        preds.extend(p); dates.extend(common_widx[ti])
        te+=STEP
    return pd.Series(preds,index=dates).sort_index(), label

def run_strategy_with_signal(gbm_signal, label):
    """Run SEP + signal as overlay."""
    gbm_daily=gbm_signal.reindex(idx,method='ffill').shift(1).fillna(0).astype(int)
    
    # Trim to OOS period
    gbm_start=gbm_signal.index[0]
    cidx=idx[idx>=gbm_start]
    
    modified_sep=sep_state.reindex(cidx).copy()
    modified_sep=modified_sep.where(gbm_daily.reindex(cidx).fillna(0)!=1, 0)
    
    r=se.run_backtest(
        cidx, dr_qqq.reindex(cidx), None, None, effr_a.reindex(cidx),
        z_credit.reindex(cidx), vol_z.reindex(cidx), modified_sep,
        inf_z=inf_z.reindex(cidx), nl_z=nl_z.reindex(cidx),
        use_sep=True, use_overlay=False,  # SEP + GBM only, no Z-score
    )
    
    eq=r['equity']; ny=len(eq)/252
    cagr=(eq.iloc[-1]**(1/ny)-1)*100
    mdd=((eq/eq.expanding().max())-1).min()*100
    dret=eq.pct_change().dropna()
    sh=dret.mean()/dret.std()*np.sqrt(252) if dret.std()>0 else 0
    dn=dret[dret<0]; ds=np.sqrt((dn**2).mean()) if len(dn)>0 else 1e-10
    so=dret.mean()/ds*np.sqrt(252)
    return {'label':label,'cagr':cagr,'mdd':mdd,'sharpe':sh,'sortino':so,'trades':r['trades'],'start':cidx[0]}

# Run all 3 feature sets
print("\nRunning walk-forward for 3 feature sets...")
sig_a, _ = run_wf(feat_yours, 'Your Z-scores')
sig_b, _ = run_wf(feat_combined, 'Combined')
sig_c, _ = run_wf(feat_audit, 'Audit features')

# Run strategies
r_a = run_strategy_with_signal(sig_a, 'SEP + ML(your indicators)')
r_b = run_strategy_with_signal(sig_b, 'SEP + ML(combined)')
r_c = run_strategy_with_signal(sig_c, 'SEP + ML(audit indicators)')

# Also run baselines on same period
start = max(r_a['start'], r_b['start'], r_c['start'])
cidx = idx[idx >= start]

# SEP only
r_sep = se.run_backtest(cidx, dr_qqq.reindex(cidx), None, None, effr_a.reindex(cidx),
    z_credit.reindex(cidx), vol_z.reindex(cidx), sep_state.reindex(cidx),
    inf_z=inf_z.reindex(cidx), nl_z=nl_z.reindex(cidx), use_sep=True, use_overlay=False)
eq=r_sep['equity']; ny=len(eq)/252
r_sep_s={'label':'SEP only','cagr':(eq.iloc[-1]**(1/ny)-1)*100,'mdd':((eq/eq.expanding().max())-1).min()*100,
    'sharpe':eq.pct_change().dropna().mean()/eq.pct_change().dropna().std()*np.sqrt(252),'sortino':0,'trades':r_sep['trades']}

# SEP + Z-score (your current full strategy)
r_full = se.run_backtest(cidx, dr_qqq.reindex(cidx), None, None, effr_a.reindex(cidx),
    z_credit.reindex(cidx), vol_z.reindex(cidx), sep_state.reindex(cidx),
    inf_z=inf_z.reindex(cidx), nl_z=nl_z.reindex(cidx), use_sep=True, use_overlay=True)
eq=r_full['equity']; ny=len(eq)/252
dret=eq.pct_change().dropna(); dn=dret[dret<0]; ds=np.sqrt((dn**2).mean()) if len(dn)>0 else 1e-10
r_full_s={'label':'SEP + Z-score (yours)','cagr':(eq.iloc[-1]**(1/ny)-1)*100,'mdd':((eq/eq.expanding().max())-1).min()*100,
    'sharpe':dret.mean()/dret.std()*np.sqrt(252),'sortino':dret.mean()/ds*np.sqrt(252),'trades':r_full['trades']}

# ═══════════════════════════════════
# RESULTS
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  IS IT THE ML OR THE INDICATORS?")
print("="*100)

print(f"\n  All strategies start from {start.strftime('%Y-%m-%d')}")
print(f"\n  {'Strategy':<35} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sortino':>8} {'Trades':>7}")
print(f"  {'─'*35} {'─'*7} {'─'*7} {'─'*7} {'─'*8} {'─'*7}")
for r in [r_sep_s, r_a, r_b, r_c, r_full_s]:
    so=f"{r['sortino']:>8.2f}" if r.get('sortino') else '     N/A'
    print(f"  {r['label']:<35} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {so} {r['trades']:>7}")

print(f"\n  DIAGNOSIS:")
print(f"  ─────────")

# Compare ML with your indicators vs your hand-crafted rules
ml_yours = r_a
your_rules = r_full_s

if ml_yours['sharpe'] > your_rules['sharpe']:
    print(f"  ML + your indicators ({ml_yours['sharpe']:.2f}) > your Z-score rules ({your_rules['sharpe']:.2f})")
    print(f"  → Problem was the RULES, not the indicators. ML found better thresholds.")
else:
    print(f"  ML + your indicators ({ml_yours['sharpe']:.2f}) < your Z-score rules ({your_rules['sharpe']:.2f})")
    print(f"  → Your hand-crafted rules are BETTER than what ML can learn from same data.")

# Compare ML with different indicator sets
if r_b['sharpe'] > r_a['sharpe'] + 0.05:
    print(f"  ML(combined) ({r_b['sharpe']:.2f}) > ML(your indicators) ({r_a['sharpe']:.2f})")
    print(f"  → Adding more indicators helps ML. Indicator choice matters.")
elif r_a['sharpe'] > r_c['sharpe'] + 0.05:
    print(f"  ML(your indicators) ({r_a['sharpe']:.2f}) > ML(audit indicators) ({r_c['sharpe']:.2f})")
    print(f"  → Your indicators are BETTER than generic macro features.")
else:
    print(f"  ML performance similar across indicator sets ({r_a['sharpe']:.2f} vs {r_b['sharpe']:.2f} vs {r_c['sharpe']:.2f})")
    print(f"  → Indicator choice is not the bottleneck.")

# Final
if your_rules['sharpe'] > max(r_a['sharpe'], r_b['sharpe'], r_c['sharpe']):
    print(f"\n  CONCLUSION: Your Z-score rules beat ALL ML variants.")
    print(f"  → The problem is ML itself, not the indicators.")
    print(f"  → Your hand-crafted state machine (z-trigger/recover hysteresis)")
    print(f"     captures regime transitions better than weekly GBM classification.")
else:
    best_ml = max([r_a, r_b, r_c], key=lambda x: x['sharpe'])
    print(f"\n  CONCLUSION: ML({best_ml['label']}) beat your Z-score rules.")
    print(f"  → Better indicators or ML combination could improve your strategy.")
