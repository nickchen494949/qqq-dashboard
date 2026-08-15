#!/usr/bin/env python3
"""
Pure PREDICTION comparison: ML vs Z-score.
Not trading performance — just: who predicts hostile regime better?
"""
import os, sys, warnings
import numpy as np, pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (matthews_corrcoef, precision_score, recall_score,
                             f1_score, confusion_matrix, accuracy_score)

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

dr_qqq=qqq_a.pct_change()

# Z-score signals
z_credit=se.compute_credit_z(hyg_a, ief_a)
vol_z=se.compute_vol_z(dr_qqq)
inf_z=se.compute_inflation_z(tip_a, tlt_a)
nl_z=se.compute_nl_z(walcl_a, rrp_a, tga_a)

# Weekly
qqq_w=qqq_a.resample('W-FRI').last().dropna()
spy_w=spy_a.resample('W-FRI').last().dropna()
widx=qqq_w.index

# ═══════════════════════════════════
# Z-SCORE "PREDICTION" — convert to weekly hostile prediction
# ═══════════════════════════════════
# Simulate the Z-score state machine to get danger states
z_w = z_credit.resample('W-FRI').last().reindex(widx)
vz_w = vol_z.resample('W-FRI').last().reindex(widx)
iz_w = inf_z.resample('W-FRI').last().reindex(widx)
nlz_w = nl_z.resample('W-FRI').last().reindex(widx)

# Run state machine (same logic as strategy_engine)
in_danger = False; vol_danger = False; inf_danger = False; nl_danger = False
zscore_pred = []
for i, dt in enumerate(widx):
    z = z_w.iloc[i] if not np.isnan(z_w.iloc[i]) else 0
    vz = vz_w.iloc[i] if not np.isnan(vz_w.iloc[i]) else 0
    iz = iz_w.iloc[i] if not np.isnan(iz_w.iloc[i]) else 0
    nlv = nlz_w.iloc[i] if not np.isnan(nlz_w.iloc[i]) else 0
    
    if not in_danger and z > se.Z_TRIGGER: in_danger = True
    elif in_danger and z < se.Z_RECOVER: in_danger = False
    
    if not vol_danger and vz > se.VZ_TRIGGER: vol_danger = True
    elif vol_danger and vz < se.VZ_RECOVER: vol_danger = False
    
    if not inf_danger and iz > se.INF_TRIGGER: inf_danger = True
    elif inf_danger and iz < se.INF_RECOVER: inf_danger = False
    
    if not nl_danger and nlv < se.NL_TRIGGER: nl_danger = True
    elif nl_danger and nlv > se.NL_RECOVER: nl_danger = False
    
    any_danger = in_danger or vol_danger or inf_danger or nl_danger
    zscore_pred.append(1 if any_danger else 0)

zscore_pred = pd.Series(zscore_pred, index=widx)

# Also make simple threshold versions (no state machine)
zscore_simple = ((z_w > se.Z_TRIGGER) | (vz_w > se.VZ_TRIGGER) | 
                 (iz_w > se.INF_TRIGGER) | (nlz_w < se.NL_TRIGGER)).astype(int)

# ═══════════════════════════════════
# ML FEATURES (3 sets)
# ═══════════════════════════════════
feat_yours = pd.DataFrame(index=widx)
feat_yours['credit_z'] = z_w
feat_yours['vol_z'] = vz_w
feat_yours['inf_z'] = iz_w
feat_yours['nl_z'] = nlz_w

feat_audit = pd.DataFrame(index=widx)
rv20=dr_qqq.rolling(20).std()*np.sqrt(252)
rv60=dr_qqq.rolling(60).std()*np.sqrt(252)
feat_audit['rv_20d']=rv20.resample('W-FRI').last().reindex(widx)
feat_audit['rv_60d']=rv60.resample('W-FRI').last().reindex(widx)
feat_audit['rv_ratio']=feat_audit['rv_20d']/feat_audit['rv_60d'].replace(0,np.nan)
vix_w=vix_a.resample('W-FRI').last().reindex(widx)
feat_audit['vix']=vix_w
feat_audit['vix_z']=(vix_w-vix_w.rolling(52).mean())/vix_w.rolling(52).std()
feat_audit['vix_chg4w']=vix_w-vix_w.shift(4)
cr_w=credit_a.resample('W-FRI').last().reindex(widx)
feat_audit['baa_spread']=cr_w
feat_audit['baa_chg4w']=cr_w-cr_w.shift(4)
t10_w=t10y_a.resample('W-FRI').last().reindex(widx)
feat_audit['t10y']=t10_w
feat_audit['curve']=t10y2y_a.resample('W-FRI').last().reindex(widx)
nfci_w=nfci_a.resample('W-FRI').last().reindex(widx)
feat_audit['nfci']=nfci_w
feat_audit['nfci_chg4w']=nfci_w-nfci_w.shift(4)
feat_audit['mom_4w']=qqq_w.pct_change(4)
feat_audit['mom_13w']=qqq_w.pct_change(13)
feat_audit['mom_52w']=qqq_w.pct_change(52)
sma200_w=qqq_a.rolling(200).mean().resample('W-FRI').last().reindex(widx)
feat_audit['vs_sma200']=qqq_w/sma200_w-1

feat_combined = pd.concat([feat_yours, feat_audit], axis=1)

# Target
fwd_mdd=pd.Series(dtype=float,index=widx)
for dt in widx:
    fut=qqq_a.loc[qqq_a.index>dt].head(22)
    if len(fut)<10: continue
    pk=fut.cummax(); fwd_mdd[dt]=(fut/pk-1).min()

# Also forward returns for analysis
fwd_ret_1w = qqq_w.shift(-1)/qqq_w - 1
fwd_ret_4w = qqq_w.shift(-4)/qqq_w - 1

# Align everything
all_feats = [feat_yours, feat_audit, feat_combined]
for f in all_feats: f.dropna(inplace=True)
common = feat_yours.index.intersection(feat_audit.index).intersection(feat_combined.index)
common = common[fwd_mdd.reindex(common).notna()]

feat_yours=feat_yours.reindex(common); feat_audit=feat_audit.reindex(common)
feat_combined=feat_combined.reindex(common)
fwd_mdd=fwd_mdd.reindex(common)
fwd_hostile=(fwd_mdd<-0.05).astype(int)
fwd_ret_1w=fwd_ret_1w.reindex(common)
fwd_ret_4w=fwd_ret_4w.reindex(common)
zscore_pred=zscore_pred.reindex(common).fillna(0).astype(int)
zscore_simple=zscore_simple.reindex(common).fillna(0).astype(int)

print(f"  {len(common)} weeks, hostile={fwd_hostile.mean():.1%}")

# ═══════════════════════════════════
# ML WALK-FORWARD PREDICTIONS
# ═══════════════════════════════════
MIN_TRAIN=3*52; STEP=26; EMBARGO=5

def run_wf_pred(feat_df):
    X=feat_df.values; y=fwd_hostile.values
    preds=[]; probs=[]; dates=[]; acts=[]
    te=MIN_TRAIN
    while te+EMBARGO+STEP<=len(X):
        tr=list(range(te)); ts=te+EMBARGO; ti=list(range(ts,min(ts+STEP,len(X))))
        sc=StandardScaler(); Xtr=sc.fit_transform(X[tr]); Xte=sc.transform(X[ti])
        m=GradientBoostingClassifier(n_estimators=150,max_depth=3,learning_rate=0.05,subsample=0.8,random_state=42)
        m.fit(Xtr,y[tr])
        p=m.predict(Xte); pr=m.predict_proba(Xte)[:,1]
        preds.extend(p); probs.extend(pr); dates.extend(common[ti]); acts.extend(y[ti])
        te+=STEP
    return np.array(preds), np.array(probs), np.array(acts), dates

print("Running ML walk-forward predictions...")
ml_yours_p, ml_yours_pr, acts_y, dates_y = run_wf_pred(feat_yours)
ml_audit_p, ml_audit_pr, acts_a, dates_a = run_wf_pred(feat_audit)
ml_combo_p, ml_combo_pr, acts_c, dates_c = run_wf_pred(feat_combined)

# Align Z-score predictions to same OOS period
oos_start = dates_y[0]
oos_mask = common >= oos_start
zs_oos = zscore_pred.loc[common[oos_mask]].values
zs_simple_oos = zscore_simple.loc[common[oos_mask]].values
act_oos = fwd_hostile.loc[common[oos_mask]].values
fwd_ret_1w_oos = fwd_ret_1w.loc[common[oos_mask]].values
fwd_ret_4w_oos = fwd_ret_4w.loc[common[oos_mask]].values

# ═══════════════════════════════════
# PREDICTION METRICS
# ═══════════════════════════════════
def pred_report(name, pred, actual, fwd1w=None, fwd4w=None, fwd_mdd_vals=None):
    mcc = matthews_corrcoef(actual, pred) if len(set(pred))>1 else 0
    prec = precision_score(actual, pred, zero_division=0)
    rec = recall_score(actual, pred, zero_division=0)
    f1 = f1_score(actual, pred, zero_division=0)
    acc = accuracy_score(actual, pred)
    cm = confusion_matrix(actual, pred)
    
    # TN, FP, FN, TP
    tn, fp, fn, tp = cm.ravel() if cm.shape == (2,2) else (0,0,0,0)
    fpr = fp/(fp+tn) if (fp+tn)>0 else 0  # false positive rate
    fnr = fn/(fn+tp) if (fn+tp)>0 else 0  # false negative rate (missed hostile)
    
    # When predicting hostile, what actually happens?
    hostile_mask = pred == 1
    safe_mask = pred == 0
    
    r = {'name':name, 'mcc':mcc, 'prec':prec, 'rec':rec, 'f1':f1, 'acc':acc,
         'tp':tp, 'fp':fp, 'tn':tn, 'fn':fn, 'fpr':fpr, 'fnr':fnr,
         'pct_hostile': hostile_mask.mean()*100}
    
    if fwd1w is not None:
        r['avg_ret_when_hostile_1w'] = fwd1w[hostile_mask].mean()*100 if hostile_mask.sum()>0 else 0
        r['avg_ret_when_safe_1w'] = fwd1w[safe_mask].mean()*100 if safe_mask.sum()>0 else 0
        r['avg_ret_when_hostile_4w'] = fwd4w[hostile_mask].mean()*100 if hostile_mask.sum()>0 else 0
        r['avg_ret_when_safe_4w'] = fwd4w[safe_mask].mean()*100 if safe_mask.sum()>0 else 0
        if fwd_mdd_vals is not None:
            r['avg_mdd_when_hostile'] = fwd_mdd_vals[hostile_mask].mean()*100 if hostile_mask.sum()>0 else 0
            r['avg_mdd_when_safe'] = fwd_mdd_vals[safe_mask].mean()*100 if safe_mask.sum()>0 else 0
        else:
            r['avg_mdd_when_hostile'] = 0
            r['avg_mdd_when_safe'] = 0
    
    return r

print(f"\n{'='*100}")
print("  PURE PREDICTION: WHO DETECTS HOSTILE REGIME BETTER?")
print("="*100)

fwd_mdd_oos = fwd_mdd.loc[common[oos_mask]].values

reports = [
    pred_report('Z-score state machine', zs_oos, act_oos, fwd_ret_1w_oos, fwd_ret_4w_oos, fwd_mdd_oos),
    pred_report('Z-score simple thresh', zs_simple_oos, act_oos, fwd_ret_1w_oos, fwd_ret_4w_oos, fwd_mdd_oos),
    pred_report('ML(your indicators)', ml_yours_p, acts_y,
                fwd_ret_1w.reindex(dates_y).values, fwd_ret_4w.reindex(dates_y).values,
                fwd_mdd.reindex(dates_y).values),
    pred_report('ML(audit indicators)', ml_audit_p, acts_a,
                fwd_ret_1w.reindex(dates_a).values, fwd_ret_4w.reindex(dates_a).values,
                fwd_mdd.reindex(dates_a).values),
    pred_report('ML(combined)', ml_combo_p, acts_c,
                fwd_ret_1w.reindex(dates_c).values, fwd_ret_4w.reindex(dates_c).values,
                fwd_mdd.reindex(dates_c).values),
]

# Classification metrics
print(f"\n  A. CLASSIFICATION ACCURACY")
print(f"  {'Predictor':<25} {'MCC':>6} {'Prec':>6} {'Recall':>7} {'F1':>6} {'Acc':>6} {'%Hostile':>9}")
print(f"  {'─'*25} {'─'*6} {'─'*6} {'─'*7} {'─'*6} {'─'*6} {'─'*9}")
for r in reports:
    print(f"  {r['name']:<25} {r['mcc']:>+5.3f} {r['prec']:>5.1%} {r['rec']:>6.1%} {r['f1']:>5.1%} {r['acc']:>5.1%} {r['pct_hostile']:>8.1f}%")

# Confusion matrix detail
print(f"\n  B. CONFUSION MATRIX")
print(f"  {'Predictor':<25} {'TP':>5} {'FP':>5} {'TN':>5} {'FN':>5} {'FPR':>6} {'FNR':>6}")
print(f"  {'─'*25} {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*6} {'─'*6}")
for r in reports:
    print(f"  {r['name']:<25} {r['tp']:>5} {r['fp']:>5} {r['tn']:>5} {r['fn']:>5} {r['fpr']:>5.1%} {r['fnr']:>5.1%}")

# Economic value of predictions
print(f"\n  C. ECONOMIC VALUE OF PREDICTIONS")
print(f"  {'Predictor':<25} {'Avg 1w ret':>11} {'Avg 4w ret':>11} {'Avg MDD':>8}  ← when predicted HOSTILE")
print(f"  {'─'*25} {'─'*11} {'─'*11} {'─'*8}")
for r in reports:
    if 'avg_ret_when_hostile_1w' in r:
        print(f"  {r['name']:<25} {r['avg_ret_when_hostile_1w']:>+10.2f}% {r['avg_ret_when_hostile_4w']:>+10.2f}% {r['avg_mdd_when_hostile']:>7.1f}%")

print(f"\n  {'Predictor':<25} {'Avg 1w ret':>11} {'Avg 4w ret':>11} {'Avg MDD':>8}  ← when predicted SAFE")
print(f"  {'─'*25} {'─'*11} {'─'*11} {'─'*8}")
for r in reports:
    if 'avg_ret_when_safe_1w' in r:
        print(f"  {r['name']:<25} {r['avg_ret_when_safe_1w']:>+10.2f}% {r['avg_ret_when_safe_4w']:>+10.2f}% {r['avg_mdd_when_safe']:>7.1f}%")

# Separation power
print(f"\n  D. SEPARATION POWER (difference between safe and hostile predictions)")
print(f"  {'Predictor':<25} {'Δ 1w ret':>9} {'Δ 4w ret':>9} {'Δ MDD':>7}")
print(f"  {'─'*25} {'─'*9} {'─'*9} {'─'*7}")
for r in reports:
    if 'avg_ret_when_safe_1w' in r:
        d1 = r['avg_ret_when_safe_1w'] - r['avg_ret_when_hostile_1w']
        d4 = r['avg_ret_when_safe_4w'] - r['avg_ret_when_hostile_4w']
        dm = r['avg_mdd_when_safe'] - r['avg_mdd_when_hostile']
        print(f"  {r['name']:<25} {d1:>+8.2f}% {d4:>+8.2f}% {dm:>+6.1f}%")

# ═══════════════════════════════════
# FINAL DIAGNOSIS
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  DIAGNOSIS")
print("="*100)

zs = reports[0]  # Z-score state machine
ml_best = max(reports[2:], key=lambda x: x['mcc'])

print(f"\n  Z-score state machine:  MCC={zs['mcc']:+.3f}  Recall={zs['rec']:.1%}  FPR={zs['fpr']:.1%}")
print(f"  Best ML:                MCC={ml_best['mcc']:+.3f}  Recall={ml_best['rec']:.1%}  FPR={ml_best['fpr']:.1%}  ({ml_best['name']})")

if ml_best['mcc'] > zs['mcc'] + 0.02:
    print(f"\n  → ML predicts hostile regime BETTER than Z-score.")
    print(f"    But Z-score TRADES better because of state machine / hysteresis.")
    print(f"    Opportunity: feed ML predictions INTO the state machine instead of raw z-scores.")
elif zs['mcc'] > ml_best['mcc'] + 0.02:
    print(f"\n  → Z-score PREDICTS better AND trades better.")
    print(f"    ML is worse at both. Your indicators + rules are simply superior.")
else:
    print(f"\n  → Prediction quality is SIMILAR.")
    print(f"    Z-score wins on trading because of the state machine execution logic.")

# Check if the problem is false positives or false negatives
if zs['fnr'] < ml_best['fnr']:
    print(f"    Z-score catches more crashes (FNR {zs['fnr']:.1%} vs {ml_best['fnr']:.1%})")
if zs['fpr'] < ml_best['fpr']:
    print(f"    Z-score has fewer false alarms (FPR {zs['fpr']:.1%} vs {ml_best['fpr']:.1%})")
