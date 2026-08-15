#!/usr/bin/env python3
"""
Nested threshold selection for Version A (ML state machine).
Each walk-forward fold selects its own (enter, exit, hold) params
using ONLY training data. No global OOS snooping.
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
# LOAD (same as before)
# ═══════════════════════════════════
print("Loading...")
qqq=gy('QQQ'); spy=gy('SPY')
hyg=gy('HYG'); ief=gy('IEF'); tip=gy('TIP'); tlt=gy('TLT')
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
z_credit=se.compute_credit_z(hyg_a, ief_a)
vol_z=se.compute_vol_z(dr_qqq)
inf_z=se.compute_inflation_z(tip_a, tlt_a)
nl_z=se.compute_nl_z(walcl_a, rrp_a, tga_a)

sep_raw=se.parse_sep_pdfs(os.path.join(PROJECT_DIR,'fomc_sep'))
sep_signals=se.build_sep_signals(sep_raw)
sep_state,_=se.build_sep_state(sep_signals, idx)

qqq_w=qqq_a.resample('W-FRI').last().dropna()
spy_w=spy_a.resample('W-FRI').last().dropna()
widx=qqq_w.index

# Features (audit set)
feat=pd.DataFrame(index=widx)
rv20=dr_qqq.rolling(20).std()*np.sqrt(252)
rv60=dr_qqq.rolling(60).std()*np.sqrt(252)
feat['rv_20d']=rv20.resample('W-FRI').last().reindex(widx)
feat['rv_60d']=rv60.resample('W-FRI').last().reindex(widx)
feat['rv_ratio']=feat['rv_20d']/feat['rv_60d'].replace(0,np.nan)
vix_w=vix_a.resample('W-FRI').last().reindex(widx)
feat['vix']=vix_w
feat['vix_z']=(vix_w-vix_w.rolling(52).mean())/vix_w.rolling(52).std()
feat['vix_chg4w']=vix_w-vix_w.shift(4)
cr_w=credit_a.resample('W-FRI').last().reindex(widx)
feat['baa_spread']=cr_w
feat['baa_chg4w']=cr_w-cr_w.shift(4)
t10_w=t10y_a.resample('W-FRI').last().reindex(widx)
feat['t10y']=t10_w
feat['curve']=t10y2y_a.resample('W-FRI').last().reindex(widx)
nfci_w=nfci_a.resample('W-FRI').last().reindex(widx)
feat['nfci']=nfci_w
feat['nfci_chg4w']=nfci_w-nfci_w.shift(4)
feat['mom_4w']=qqq_w.pct_change(4)
feat['mom_13w']=qqq_w.pct_change(13)
feat['mom_52w']=qqq_w.pct_change(52)
sma200_w=qqq_a.rolling(200).mean().resample('W-FRI').last().reindex(widx)
feat['vs_sma200']=qqq_w/sma200_w-1
feat=feat.dropna()

# Target
fwd_mdd=pd.Series(dtype=float,index=widx)
for dt in widx:
    fut=qqq_a.loc[qqq_a.index>dt].head(22)
    if len(fut)<10: continue
    pk=fut.cummax(); fwd_mdd[dt]=(fut/pk-1).min()
fwd_mdd=fwd_mdd.reindex(feat.index)
valid=fwd_mdd.notna()
feat=feat.loc[valid]; fwd_mdd=fwd_mdd.loc[valid]
fwd_hostile=(fwd_mdd<-0.05).astype(int)

X=feat.values; y=fwd_hostile.values
MIN_TRAIN=3*52; STEP=26; EMBARGO=5; VAL_SIZE=52  # 1 year validation

print(f"  {len(feat)} weeks, hostile={fwd_hostile.mean():.1%}")

# ═══════════════════════════════════
# State machine simulator for validation
# ═══════════════════════════════════
def sim_statemachine(probs, qqq_weekly, enter_p, exit_p, min_hold):
    """Simulate ML state machine on weekly data. Return Sharpe."""
    defensive=False; hold=0
    rets=[]
    for i in range(1, len(probs)):
        p = probs[i-1]  # signal from previous week (shift 1)
        if not defensive:
            if p > enter_p:
                defensive=True; hold=0
        else:
            hold+=1
            if hold>=min_hold and p<exit_p:
                defensive=False
        
        wk_ret = qqq_weekly.iloc[i]/qqq_weekly.iloc[i-1]-1
        lev = 1 if defensive else 3
        rets.append(lev * wk_ret)
    
    rets=np.array(rets)
    if len(rets)<10 or np.std(rets)==0: return -999
    return np.mean(rets)/np.std(rets)*np.sqrt(52)  # weekly Sharpe

# ═══════════════════════════════════
# NESTED WALK-FORWARD
# ═══════════════════════════════════
grid_enter = [0.50, 0.55, 0.60, 0.65]
grid_exit = [0.30, 0.35, 0.40]
grid_hold = [2, 4]

print(f"\nNested walk-forward: train → validate params → test")
print(f"  Grid: {len(grid_enter)}×{len(grid_exit)}×{len(grid_hold)} = {len(grid_enter)*len(grid_exit)*len(grid_hold)} combos per fold")

# Also run fixed-param version for comparison
fixed_probs=[]; fixed_dates=[]
nested_signals=[]; nested_dates=[]; nested_params_log=[]

te=MIN_TRAIN
fold=0
while te+EMBARGO+STEP<=len(X):
    fold+=1
    # Split: train | validation | embargo | test
    val_start = max(0, te-VAL_SIZE)
    tr_idx = list(range(val_start))  # pure train (before validation)
    val_idx = list(range(val_start, te))  # validation
    ts = te+EMBARGO
    test_idx = list(range(ts, min(ts+STEP, len(X))))
    
    if len(tr_idx) < 52 or len(val_idx) < 26:
        # Not enough data for nested split, use all training
        tr_idx = list(range(te))
        val_idx = tr_idx[-VAL_SIZE:]  # last year of training as pseudo-val
    
    # Train model on FULL training set (train+val) for predictions
    full_tr = list(range(te))
    sc=StandardScaler(); Xtr=sc.fit_transform(X[full_tr]); Xte=sc.transform(X[test_idx])
    m=GradientBoostingClassifier(n_estimators=150,max_depth=3,learning_rate=0.05,subsample=0.8,random_state=42)
    m.fit(Xtr, y[full_tr])
    test_probs = m.predict_proba(Xte)[:,1]
    
    # For fixed-param comparison
    fixed_probs.extend(test_probs)
    fixed_dates.extend(feat.index[test_idx])
    
    # Train model on TRAIN ONLY for validation param selection
    sc2=StandardScaler(); Xtr2=sc2.fit_transform(X[tr_idx])
    Xval=sc2.transform(X[val_idx])
    m2=GradientBoostingClassifier(n_estimators=150,max_depth=3,learning_rate=0.05,subsample=0.8,random_state=42)
    m2.fit(Xtr2, y[tr_idx])
    val_probs = m2.predict_proba(Xval)[:,1]
    
    # Select best params on VALIDATION set
    val_qqq = qqq_w.reindex(feat.index[val_idx])
    best_sh=-999; best_params=(0.6, 0.35, 4)
    for ep in grid_enter:
        for xp in grid_exit:
            for mh in grid_hold:
                sh = sim_statemachine(val_probs, val_qqq, ep, xp, mh)
                if sh > best_sh:
                    best_sh=sh; best_params=(ep,xp,mh)
    
    # Apply SELECTED params to test fold
    ep, xp, mh = best_params
    nested_params_log.append({'fold':fold, 'enter':ep, 'exit':xp, 'hold':mh, 'val_sharpe':best_sh})
    
    # Generate test signals using nested-selected params
    # Need to carry state from previous folds
    nested_dates.extend(feat.index[test_idx])
    # Store probs + params for later state machine run
    for ti_idx, prob_val in zip(test_idx, test_probs):
        nested_signals.append({'date':feat.index[ti_idx], 'prob':prob_val,
                               'enter':ep, 'exit':xp, 'hold':mh})
    
    print(f"    Fold {fold}: val_sharpe={best_sh:.2f} → params=({ep},{xp},{mh})")
    te+=STEP

# ═══════════════════════════════════
# Run state machines: nested vs fixed vs baseline
# ═══════════════════════════════════
print(f"\nRunning final strategies...")

# NESTED: state machine with fold-specific params
def run_nested_statemachine(signals):
    """Run state machine where params change per fold."""
    defensive=False; hold=0
    states=[]
    for s in signals:
        p=s['prob']; ep=s['enter']; xp=s['exit']; mh=s['hold']
        if not defensive:
            if p>ep:
                defensive=True; hold=0
        else:
            hold+=1
            if hold>=mh and p<xp:
                defensive=False
        states.append(1 if defensive else 0)
    return pd.Series(states, index=[s['date'] for s in signals])

nested_weekly = run_nested_statemachine(nested_signals)

# FIXED: best global params (enter=0.65, exit=0.3, hold=4) — the "snooped" version
fixed_prob_s = pd.Series(fixed_probs, index=fixed_dates).sort_index()
def run_fixed_statemachine(probs, enter_p, exit_p, min_hold):
    defensive=False; hold=0; states=[]
    for dt in probs.index:
        p=probs.loc[dt]
        if not defensive:
            if p>enter_p:
                defensive=True; hold=0
        else:
            hold+=1
            if hold>=min_hold and p<exit_p:
                defensive=False
        states.append(1 if defensive else 0)
    return pd.Series(states, index=probs.index)

fixed_weekly = run_fixed_statemachine(fixed_prob_s, 0.65, 0.3, 4)

# Convert to daily and run backtest
def run_bt(weekly_signal, label):
    daily_sig=weekly_signal.reindex(idx, method='ffill').shift(1).fillna(0).astype(int)
    start=weekly_signal.index[0]
    cidx=idx[idx>=start]
    
    mod_sep=sep_state.reindex(cidx).copy()
    mod_sep=mod_sep.where(daily_sig.reindex(cidx).fillna(0)!=1, 0)
    
    r=se.run_backtest(
        cidx, dr_qqq.reindex(cidx), None, None, effr_a.reindex(cidx),
        z_credit.reindex(cidx), vol_z.reindex(cidx), mod_sep,
        inf_z=inf_z.reindex(cidx), nl_z=nl_z.reindex(cidx),
        use_sep=True, use_overlay=False,
    )
    eq=r['equity']; ny=len(eq)/252
    cagr=(eq.iloc[-1]**(1/ny)-1)*100
    mdd=((eq/eq.expanding().max())-1).min()*100
    dret=eq.pct_change().dropna()
    sh=dret.mean()/dret.std()*np.sqrt(252) if dret.std()>0 else 0
    dn=dret[dret<0]; ds=np.sqrt((dn**2).mean()) if len(dn)>0 else 1e-10
    so=dret.mean()/ds*np.sqrt(252)
    
    sig_arr=daily_sig.reindex(cidx).fillna(0).values
    bad_re=0; tot_re=0
    for i in range(1,len(sig_arr)-22):
        if sig_arr[i]==0 and sig_arr[i-1]==1:
            tot_re+=1
            fut=qqq_a.reindex(cidx).iloc[i:i+22]
            if len(fut)>=10:
                pk=fut.cummax(); dd=(fut/pk-1).min()
                if dd<-0.05: bad_re+=1
    bad_rate=bad_re/tot_re*100 if tot_re>0 else 0
    switches=np.sum(np.diff(sig_arr)!=0)
    pct_def=(sig_arr==1).mean()*100
    
    return {'label':label,'cagr':cagr,'mdd':mdd,'sharpe':sh,'sortino':so,
            'trades':r['trades'],'switches':switches,'pct_def':pct_def,
            'bad_reentry':bad_rate,'total_reentry':tot_re,'bad_reentry_n':bad_re,
            'equity':eq}

r_nested = run_bt(nested_weekly, 'A nested (no snooping)')
r_fixed = run_bt(fixed_weekly, 'A fixed=0.65/0.3/4 (snooped)')

# Baseline: original strategy
start=nested_weekly.index[0]
cidx=idx[idx>=start]
r_orig=se.run_backtest(
    cidx, dr_qqq.reindex(cidx), None, None, effr_a.reindex(cidx),
    z_credit.reindex(cidx), vol_z.reindex(cidx), sep_state.reindex(cidx),
    inf_z=inf_z.reindex(cidx), nl_z=nl_z.reindex(cidx),
    use_sep=True, use_overlay=True,
)
eq=r_orig['equity']; ny=len(eq)/252
dret=eq.pct_change().dropna(); dn=dret[dret<0]; ds=np.sqrt((dn**2).mean()) if len(dn)>0 else 1e-10

danger_arr=np.array(r_orig['danger']).astype(int)|np.array(r_orig['vol_danger']).astype(int)
if r_orig.get('inf_danger'): danger_arr=danger_arr|np.array(r_orig['inf_danger']).astype(int)
if r_orig.get('nl_danger'): danger_arr=danger_arr|np.array(r_orig['nl_danger']).astype(int)
bad_re=0; tot_re=0
for i in range(1,len(danger_arr)-22):
    if danger_arr[i]==0 and danger_arr[i-1]==1:
        tot_re+=1
        fut=qqq_a.reindex(cidx).iloc[i:i+22]
        if len(fut)>=10:
            pk=fut.cummax(); dd=(fut/pk-1).min()
            if dd<-0.05: bad_re+=1

baseline={
    'label':'★ SEP + Z-score (yours)',
    'cagr':(eq.iloc[-1]**(1/ny)-1)*100,
    'mdd':((eq/eq.expanding().max())-1).min()*100,
    'sharpe':dret.mean()/dret.std()*np.sqrt(252),
    'sortino':dret.mean()/ds*np.sqrt(252),
    'bad_reentry':bad_re/tot_re*100 if tot_re>0 else 0,
    'total_reentry':tot_re, 'bad_reentry_n':bad_re,
    'equity':eq,
}

# ═══════════════════════════════════
# RESULTS
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  NESTED vs SNOOPED vs YOUR STRATEGY")
print("="*100)

print(f"\n  Fold params selected by nested validation:")
for p in nested_params_log:
    print(f"    Fold {p['fold']:>2}: enter={p['enter']} exit={p['exit']} hold={p['hold']} (val_sharpe={p['val_sharpe']:.2f})")

all_r = [baseline, r_fixed, r_nested]
print(f"\n  {'Strategy':<35} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sort':>6} {'BadRe%':>7} {'BadRe#':>7}")
print(f"  {'─'*35} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*7} {'─'*7}")
for r in all_r:
    brn=f"{r['bad_reentry_n']}/{r['total_reentry']}"
    print(f"  {r['label']:<35} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r.get('sortino',0):>5.2f} {r['bad_reentry']:>6.1f}% {brn:>7}")

# Snooping gap
gap_cagr = r_fixed['cagr'] - r_nested['cagr']
gap_sharpe = r_fixed['sharpe'] - r_nested['sharpe']
print(f"\n  Snooping gap (fixed - nested):")
print(f"    CAGR:   {gap_cagr:+.1f}%")
print(f"    Sharpe: {gap_sharpe:+.2f}")

if gap_cagr > 5:
    print(f"    ⚠️  Fixed params benefited {gap_cagr:.1f}% CAGR from snooping.")
else:
    print(f"    ✅ Snooping gap is small ({gap_cagr:.1f}%). Fixed params are robust.")

# vs baseline
print(f"\n  VERDICT:")
if r_nested['sharpe'] > baseline['sharpe']:
    print(f"    ✅ Nested ML ({r_nested['sharpe']:.2f}) beats your Z-score ({baseline['sharpe']:.2f}) even without snooping!")
    print(f"    CAGR: {r_nested['cagr']:+.1f}% vs {baseline['cagr']:+.1f}%")
    print(f"    MDD: {r_nested['mdd']:.1f}% vs {baseline['mdd']:.1f}%")
elif r_nested['cagr'] > baseline['cagr'] + 5 and r_nested['mdd'] >= baseline['mdd'] - 5:
    print(f"    ⚠️  Nested ML has higher CAGR ({r_nested['cagr']:+.1f}% vs {baseline['cagr']:+.1f}%) with similar MDD.")
    print(f"    But lower Sharpe ({r_nested['sharpe']:.2f} vs {baseline['sharpe']:.2f}).")
    print(f"    Trade-off: more return, more vol. Depends on your risk preference.")
else:
    print(f"    ❌ Your Z-score strategy still wins after removing snooping.")

# Year by year
print(f"\n  YEAR-BY-YEAR")
print(f"  {'Year':>6} {'Nested':>8} {'Fixed':>8} {'Yours':>8}")
print(f"  {'─'*6} {'─'*8} {'─'*8} {'─'*8}")
for y in sorted(set(cidx.year)):
    m=cidx.year==y
    if m.sum()<50: continue
    en=r_nested['equity'].loc[cidx[m]]
    ef=r_fixed['equity'].loc[cidx[m]]
    eo=r_orig['equity'].loc[cidx[m]]
    cn=(en.iloc[-1]/en.iloc[0]-1)*100
    cf=(ef.iloc[-1]/ef.iloc[0]-1)*100
    co=(eo.iloc[-1]/eo.iloc[0]-1)*100
    print(f"  {y:>6} {cn:>+7.1f}% {cf:>+7.1f}% {co:>+7.1f}%")
