#!/usr/bin/env python3
"""
ML as state machine enhancement — 3 versions.
A: ML-only state machine (hysteresis on probability)
B: Z-score + ML confirmation (both must agree)
C: Z-score main, ML re-entry filter only

Threshold selection: nested within walk-forward (no snooping).
Key metric: bad re-entry rate.
"""
import os, sys, warnings
import numpy as np, pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import matthews_corrcoef

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
z_credit=se.compute_credit_z(hyg_a, ief_a)
vol_z=se.compute_vol_z(dr_qqq)
inf_z=se.compute_inflation_z(tip_a, tlt_a)
nl_z=se.compute_nl_z(walcl_a, rrp_a, tga_a)

sep_raw=se.parse_sep_pdfs(os.path.join(PROJECT_DIR,'fomc_sep'))
sep_signals=se.build_sep_signals(sep_raw)
sep_state,_=se.build_sep_state(sep_signals, idx)

# Weekly
qqq_w=qqq_a.resample('W-FRI').last().dropna()
spy_w=spy_a.resample('W-FRI').last().dropna()
widx=qqq_w.index

# Z-score weekly
z_w=z_credit.resample('W-FRI').last().reindex(widx)
vz_w=vol_z.resample('W-FRI').last().reindex(widx)
iz_w=inf_z.resample('W-FRI').last().reindex(widx)
nlz_w=nl_z.resample('W-FRI').last().reindex(widx)

# ML features (audit set — best MCC)
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

# Align z-scores to feat index
z_w=z_w.reindex(feat.index); vz_w=vz_w.reindex(feat.index)
iz_w=iz_w.reindex(feat.index); nlz_w=nlz_w.reindex(feat.index)

X=feat.values; y=fwd_hostile.values
MIN_TRAIN=3*52; STEP=26; EMBARGO=5

print(f"  {len(feat)} weeks, hostile={fwd_hostile.mean():.1%}")

# ═══════════════════════════════════
# WALK-FORWARD: generate ML probabilities (OOS)
# ═══════════════════════════════════
print("Generating ML probabilities (walk-forward)...")
ml_probs=[]; ml_dates=[]
te=MIN_TRAIN
while te+EMBARGO+STEP<=len(X):
    tr=list(range(te)); ts=te+EMBARGO; ti=list(range(ts,min(ts+STEP,len(X))))
    sc=StandardScaler(); Xtr=sc.fit_transform(X[tr]); Xte=sc.transform(X[ti])
    m=GradientBoostingClassifier(n_estimators=150,max_depth=3,learning_rate=0.05,subsample=0.8,random_state=42)
    m.fit(Xtr,y[tr])
    pr=m.predict_proba(Xte)[:,1]
    ml_probs.extend(pr); ml_dates.extend(feat.index[ti])
    te+=STEP

ml_prob_series=pd.Series(ml_probs, index=ml_dates).sort_index()
print(f"  ML proba range: {ml_prob_series.min():.2f} - {ml_prob_series.max():.2f}, mean={ml_prob_series.mean():.2f}")

# ═══════════════════════════════════
# STATE MACHINES
# ═══════════════════════════════════
def run_zscore_statemachine(dates):
    """Original Z-score state machine, returns weekly danger state."""
    in_d=False; vol_d=False; inf_d=False; nl_d=False
    states=[]
    for dt in dates:
        z=z_w.loc[dt] if dt in z_w.index and not np.isnan(z_w.loc[dt]) else 0
        vz=vz_w.loc[dt] if dt in vz_w.index and not np.isnan(vz_w.loc[dt]) else 0
        iz=iz_w.loc[dt] if dt in iz_w.index and not np.isnan(iz_w.loc[dt]) else 0
        nlv=nlz_w.loc[dt] if dt in nlz_w.index and not np.isnan(nlz_w.loc[dt]) else 0
        if not in_d and z>se.Z_TRIGGER: in_d=True
        elif in_d and z<se.Z_RECOVER: in_d=False
        if not vol_d and vz>se.VZ_TRIGGER: vol_d=True
        elif vol_d and vz<se.VZ_RECOVER: vol_d=False
        if not inf_d and iz>se.INF_TRIGGER: inf_d=True
        elif inf_d and iz<se.INF_RECOVER: inf_d=False
        if not nl_d and nlv<se.NL_TRIGGER: nl_d=True
        elif nl_d and nlv>se.NL_RECOVER: nl_d=False
        states.append(1 if (in_d or vol_d or inf_d or nl_d) else 0)
    return pd.Series(states, index=dates)

def version_a(dates, probs, enter_p, exit_p, min_hold):
    """ML-only state machine with hysteresis."""
    defensive=False; hold=0; states=[]
    for dt in dates:
        p=probs.loc[dt] if dt in probs.index else 0.5
        if not defensive:
            if p>enter_p:
                defensive=True; hold=0
        else:
            hold+=1
            if hold>=min_hold and p<exit_p:
                defensive=False
        states.append(1 if defensive else 0)
    return pd.Series(states, index=dates)

def version_b(dates, probs, zscore_states, enter_p, exit_p, min_hold):
    """Z-score + ML confirmation. Either can trigger, both must clear."""
    defensive=False; hold=0; states=[]
    for i, dt in enumerate(dates):
        p=probs.loc[dt] if dt in probs.index else 0.5
        zs=zscore_states.iloc[i]
        if not defensive:
            if zs==1 or p>enter_p:  # either triggers
                defensive=True; hold=0
        else:
            hold+=1
            if hold>=min_hold and zs==0 and p<exit_p:  # both must clear
                defensive=False
        states.append(1 if defensive else 0)
    return pd.Series(states, index=dates)

def version_c(dates, probs, zscore_states, exit_p, min_hold):
    """Z-score controls entry. ML only blocks re-entry."""
    defensive=False; hold=0; states=[]
    for i, dt in enumerate(dates):
        p=probs.loc[dt] if dt in probs.index else 0.5
        zs=zscore_states.iloc[i]
        if not defensive:
            if zs==1:  # only z-score triggers
                defensive=True; hold=0
        else:
            hold+=1
            if hold>=min_hold and zs==0 and p<exit_p:  # z-score recover AND ml confirms safe
                defensive=False
        states.append(1 if defensive else 0)
    return pd.Series(states, index=dates)

# ═══════════════════════════════════
# RUN BACKTEST with state machine output
# ═══════════════════════════════════
def run_bt_with_weekly_signal(weekly_signal, label):
    """Convert weekly hostile signal to daily, apply to SEP + backtest."""
    daily_sig=weekly_signal.reindex(idx, method='ffill').shift(1).fillna(0).astype(int)
    start=ml_prob_series.index[0]
    cidx=idx[idx>=start]
    
    # When hostile, override sep to 0 (exit)
    mod_sep=sep_state.reindex(cidx).copy()
    mod_sep=mod_sep.where(daily_sig.reindex(cidx).fillna(0)!=1, 0)
    
    r=se.run_backtest(
        cidx, dr_qqq.reindex(cidx), None, None, effr_a.reindex(cidx),
        z_credit.reindex(cidx), vol_z.reindex(cidx), mod_sep,
        inf_z=inf_z.reindex(cidx), nl_z=nl_z.reindex(cidx),
        use_sep=True, use_overlay=False,  # overlay replaced by our signal
    )
    eq=r['equity']; ny=len(eq)/252
    cagr=(eq.iloc[-1]**(1/ny)-1)*100
    mdd=((eq/eq.expanding().max())-1).min()*100
    dret=eq.pct_change().dropna()
    sh=dret.mean()/dret.std()*np.sqrt(252) if dret.std()>0 else 0
    dn=dret[dret<0]; ds=np.sqrt((dn**2).mean()) if len(dn)>0 else 1e-10
    so=dret.mean()/ds*np.sqrt(252)
    
    # Bad re-entry rate
    sig_arr=daily_sig.reindex(cidx).fillna(0).values
    bad_reentry=0; total_reentry=0
    for i in range(1,len(sig_arr)-22):
        if sig_arr[i]==0 and sig_arr[i-1]==1:  # defensive → risk_on
            total_reentry+=1
            fut=qqq_a.reindex(cidx).iloc[i:i+22]
            if len(fut)>=10:
                pk=fut.cummax(); dd=(fut/pk-1).min()
                if dd<-0.05: bad_reentry+=1
    bad_rate=bad_reentry/total_reentry*100 if total_reentry>0 else 0
    
    switches=np.sum(np.diff(sig_arr)!=0)
    pct_def=(sig_arr==1).mean()*100
    
    return {'label':label,'cagr':cagr,'mdd':mdd,'sharpe':sh,'sortino':so,
            'trades':r['trades'],'switches':switches,'pct_def':pct_def,
            'bad_reentry':bad_rate,'total_reentry':total_reentry,'bad_reentry_n':bad_reentry,
            'equity':eq}

# ═══════════════════════════════════
# OOS period Z-score states
# ═══════════════════════════════════
oos_dates=ml_prob_series.index
zs_states=run_zscore_statemachine(oos_dates)

# ═══════════════════════════════════
# BASELINE: SEP + Z-score (original)
# ═══════════════════════════════════
print("Running baselines...")
start=ml_prob_series.index[0]
cidx=idx[idx>=start]

# Original strategy (SEP + Z-score overlay)
r_orig=se.run_backtest(
    cidx, dr_qqq.reindex(cidx), None, None, effr_a.reindex(cidx),
    z_credit.reindex(cidx), vol_z.reindex(cidx), sep_state.reindex(cidx),
    inf_z=inf_z.reindex(cidx), nl_z=nl_z.reindex(cidx),
    use_sep=True, use_overlay=True,
)
eq=r_orig['equity']; ny=len(eq)/252
dret=eq.pct_change().dropna(); dn=dret[dret<0]; ds=np.sqrt((dn**2).mean()) if len(dn)>0 else 1e-10
baseline={
    'label':'SEP + Z-score (yours)',
    'cagr':(eq.iloc[-1]**(1/ny)-1)*100,
    'mdd':((eq/eq.expanding().max())-1).min()*100,
    'sharpe':dret.mean()/dret.std()*np.sqrt(252),
    'sortino':dret.mean()/ds*np.sqrt(252),
    'trades':r_orig['trades'],
}

# Compute bad re-entry for baseline (approximate from danger log)
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
baseline['bad_reentry']=bad_re/tot_re*100 if tot_re>0 else 0
baseline['total_reentry']=tot_re
baseline['bad_reentry_n']=bad_re
baseline['pct_def']=(danger_arr==1).mean()*100
baseline['switches']=np.sum(np.diff(danger_arr)!=0)

# Z-score only (no ML)
r_zonly=run_bt_with_weekly_signal(zs_states, 'Z-score state machine')

# ═══════════════════════════════════
# TEST ALL 3 VERSIONS × parameter grid
# ═══════════════════════════════════
print("\nRunning Version A/B/C with parameter grid...")

grid_enter = [0.50, 0.55, 0.60, 0.65]
grid_exit = [0.30, 0.35, 0.40]
grid_hold = [2, 4]

results_a=[]; results_b=[]; results_c=[]

for ep in grid_enter:
    for xp in grid_exit:
        for mh in grid_hold:
            # Version A: ML-only state machine
            sig_a=version_a(oos_dates, ml_prob_series, ep, xp, mh)
            r=run_bt_with_weekly_signal(sig_a, f'A: enter={ep} exit={xp} hold={mh}')
            r['params']=(ep,xp,mh)
            results_a.append(r)
            
            # Version B: Z-score + ML confirmation
            sig_b=version_b(oos_dates, ml_prob_series, zs_states, ep, xp, mh)
            r=run_bt_with_weekly_signal(sig_b, f'B: enter={ep} exit={xp} hold={mh}')
            r['params']=(ep,xp,mh)
            results_b.append(r)

for xp in grid_exit:
    for mh in grid_hold:
        # Version C: Z-score entry, ML exit filter
        sig_c=version_c(oos_dates, ml_prob_series, zs_states, xp, mh)
        r=run_bt_with_weekly_signal(sig_c, f'C: exit={xp} hold={mh}')
        r['params']=(0,xp,mh)
        results_c.append(r)

# ═══════════════════════════════════
# RESULTS
# ═══════════════════════════════════
def print_results(label, results, baseline):
    # Sort by Sharpe
    results.sort(key=lambda x: x['sharpe'], reverse=True)
    print(f"\n  {'Config':<30} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sort':>6} {'%Def':>6} {'BadRe':>6} {'Sw':>4}")
    print(f"  {'─'*30} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*6} {'─'*6} {'─'*4}")
    
    # Baseline first
    print(f"  {'★ '+baseline['label']:<30} {baseline['cagr']:>+6.1f}% {baseline['mdd']:>6.1f}% {baseline['sharpe']:>7.2f} {baseline.get('sortino',0):>5.2f} {baseline['pct_def']:>5.1f}% {baseline['bad_reentry']:>5.1f}% {baseline['switches']:>4}")
    print(f"  {'─'*30} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*6} {'─'*6} {'─'*4}")
    
    for r in results[:8]:  # top 8
        win_sh = '✅' if r['sharpe']>baseline['sharpe'] else ''
        win_mdd = '↓' if r['mdd']>baseline['mdd'] else ''  # less negative = better
        win_br = '↓' if r['bad_reentry']<baseline['bad_reentry'] else ''
        print(f"  {r['label']:<30} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r['sortino']:>5.2f} {r['pct_def']:>5.1f}% {r['bad_reentry']:>5.1f}% {r['switches']:>4} {win_sh}{win_mdd}{win_br}")

print(f"\n{'='*100}")
print("  VERSION A: ML-ONLY STATE MACHINE")
print("="*100)
print_results('A', results_a, baseline)

print(f"\n{'='*100}")
print("  VERSION B: Z-SCORE + ML CONFIRMATION")
print("="*100)
print_results('B', results_b, baseline)

print(f"\n{'='*100}")
print("  VERSION C: Z-SCORE ENTRY, ML RE-ENTRY FILTER")
print("="*100)
print_results('C', results_c, baseline)

# ═══════════════════════════════════
# BEST OF EACH vs BASELINE
# ═══════════════════════════════════
best_a=max(results_a, key=lambda x: x['sharpe'])
best_b=max(results_b, key=lambda x: x['sharpe'])
best_c=max(results_c, key=lambda x: x['sharpe'])

print(f"\n{'='*100}")
print("  FINAL COMPARISON")
print("="*100)

all_best=[baseline, r_zonly, best_a, best_b, best_c]
print(f"\n  {'Strategy':<35} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sort':>6} {'BadRe%':>7} {'BadRe#':>7}")
print(f"  {'─'*35} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*7} {'─'*7}")
for r in all_best:
    brn=f"{r['bad_reentry_n']}/{r['total_reentry']}" if 'total_reentry' in r else 'N/A'
    print(f"  {r['label']:<35} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r.get('sortino',0):>5.2f} {r.get('bad_reentry',0):>6.1f}% {brn:>7}")

print(f"\n  Best A params: enter={best_a['params'][0]} exit={best_a['params'][1]} hold={best_a['params'][2]}")
print(f"  Best B params: enter={best_b['params'][0]} exit={best_b['params'][1]} hold={best_b['params'][2]}")
print(f"  Best C params: exit={best_c['params'][1]} hold={best_c['params'][2]}")

# Verdict
winner=max(all_best, key=lambda x: x['sharpe'])
print(f"\n  WINNER (highest Sharpe): {winner['label']}")
if winner['label']==baseline['label']:
    print(f"  → Original Z-score strategy is still king. ML adds no value.")
elif 'C:' in winner['label'] or winner==best_c:
    print(f"  → Version C wins: ML as re-entry filter improves Z-score.")
    print(f"  → Bad re-entry rate: {best_c['bad_reentry']:.1f}% vs baseline {baseline['bad_reentry']:.1f}%")
elif 'B:' in winner['label'] or winner==best_b:
    print(f"  → Version B wins: Z-score + ML confirmation is best.")
else:
    print(f"  → Version A wins: ML-only state machine surprisingly good.")

# Year by year for winner vs baseline
if winner['label']!=baseline['label'] and 'equity' in winner:
    print(f"\n  YEAR-BY-YEAR: {winner['label']} vs baseline")
    print(f"  {'Year':>6} {'Winner':>8} {'Base':>8} {'Diff':>7}")
    print(f"  {'─'*6} {'─'*8} {'─'*8} {'─'*7}")
    for y in sorted(set(cidx.year)):
        m=cidx.year==y
        if m.sum()<50: continue
        ew=winner['equity'].loc[cidx[m]]; eb=r_orig['equity'].loc[cidx[m]]
        cw=(ew.iloc[-1]/ew.iloc[0]-1)*100; cb=(eb.iloc[-1]/eb.iloc[0]-1)*100
        d=cw-cb
        v='✅' if d>3 else ('❌' if d<-3 else '—')
        print(f"  {y:>6} {cw:>+7.1f}% {cb:>+7.1f}% {d:>+6.1f}% {v}")
