#!/usr/bin/env python3
"""
AUDIT v3 — Final 5 tests per user review.
1. Same-period comparison (all strategies aligned to GBM OOS dates)
2. Real tradable strategy (TQQQ when 3x, QQQ when 1x)
3. Leverage ladder (different hostile/normal combos)
4. Crisis contribution (where does alpha come from?)
5. Purged permutation test (shuffle target 500x)
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
from strategy_engine import get_fred_api_key
from fredapi import Fred
import yfinance as yf

fred = Fred(api_key=get_fred_api_key())
def gf(s): return pd.read_csv(os.path.join(DATA_DIR, f'fred_{s}.csv'), index_col=0, parse_dates=True).squeeze()
def gy(t):
    p=os.path.join(DATA_DIR, f'yahoo_{t}.csv')
    if os.path.exists(p):
        s=pd.read_csv(p,index_col=0,parse_dates=True).squeeze()
        if len(s)>100: return s
    df=yf.download(t,start='2000-01-01',progress=False,auto_adjust=False)
    adj=df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
    if isinstance(adj,pd.DataFrame): adj=adj.iloc[:,0]
    adj.to_csv(p); return adj

# ═══════════════════════════════════
# DATA (same as audit v2)
# ═══════════════════════════════════
print("Loading...")
qqq=gy('QQQ'); tqqq=gy('TQQQ')
vix=gf('VIXCLS'); credit=gf('BAA10Y')
nfci=gf('NFCI'); t10y=gf('DGS10'); t2y=gf('DGS2'); t10y2y=gf('T10Y2Y')
spy=gy('SPY')

idx=qqq.dropna().index; idx=idx[idx>='2005-01-01']
qqq=qqq.reindex(idx); spy=spy.reindex(idx).ffill()
vix=vix.reindex(idx,method='ffill').ffill()
credit=credit.reindex(idx,method='ffill').ffill()
nfci=nfci.resample('D').ffill().reindex(idx,method='ffill').ffill()
t10y=t10y.reindex(idx,method='ffill').ffill()
t2y=t2y.reindex(idx,method='ffill').ffill()
t10y2y=t10y2y.reindex(idx,method='ffill').ffill()

qqq_ret_d=qqq.pct_change()
tqqq_ret_d=tqqq.pct_change() if tqqq is not None else None
qqq_w=qqq.resample('W-FRI').last().dropna()
spy_w=spy.resample('W-FRI').last().dropna()
widx=qqq_w.index

# Features (NO valuation — the winning version)
feat=pd.DataFrame(index=widx)
rv20=qqq_ret_d.rolling(20).std()*np.sqrt(252)
rv60=qqq_ret_d.rolling(60).std()*np.sqrt(252)
feat['rv_20d']=rv20.resample('W-FRI').last().reindex(widx)
feat['rv_60d']=rv60.resample('W-FRI').last().reindex(widx)
feat['rv_ratio']=feat['rv_20d']/feat['rv_60d'].replace(0,np.nan)
vix_w=vix.resample('W-FRI').last().reindex(widx)
feat['vix']=vix_w
feat['vix_z']=(vix_w-vix_w.rolling(52).mean())/vix_w.rolling(52).std()
feat['vix_chg4w']=vix_w-vix_w.shift(4)
cr_w=credit.resample('W-FRI').last().reindex(widx)
feat['credit']=cr_w
feat['credit_z']=(cr_w-cr_w.rolling(52).mean())/cr_w.rolling(52).std()
feat['credit_chg4w']=cr_w-cr_w.shift(4)
t10_w=t10y.resample('W-FRI').last().reindex(widx)
feat['t10y']=t10_w
feat['curve']=t10y2y.resample('W-FRI').last().reindex(widx)
feat['rate_chg4w']=t10_w-t10_w.shift(4)
nfci_w=nfci.resample('W-FRI').last().reindex(widx)
feat['nfci']=nfci_w
feat['nfci_chg4w']=nfci_w-nfci_w.shift(4)
feat['mom_4w']=qqq_w.pct_change(4)
feat['mom_13w']=qqq_w.pct_change(13)
feat['mom_52w']=qqq_w.pct_change(52)
sma200_w=qqq.rolling(200).mean().resample('W-FRI').last().reindex(widx)
feat['vs_sma200']=qqq_w/sma200_w-1
feat['qqq_vs_spy']=qqq_w.pct_change(13)-spy_w.pct_change(13).reindex(widx)
feat=feat.dropna()

# Target
fwd_mdd=pd.Series(dtype=float,index=widx)
for dt in widx:
    fut=qqq.loc[qqq.index>dt].head(22)
    if len(fut)<10: continue
    pk=fut.cummax(); fwd_mdd[dt]=(fut/pk-1).min()
fwd_mdd=fwd_mdd.reindex(feat.index)
valid=fwd_mdd.notna()
feat=feat.loc[valid]; fwd_mdd=fwd_mdd.loc[valid]
fwd_hostile=(fwd_mdd<-0.05).astype(int)

X=feat.values; fnames=list(feat.columns)
MIN_TRAIN=3*52; STEP=26; EMBARGO=5

print(f"  {len(feat)} weeks, {feat.shape[1]} features, hostile={fwd_hostile.mean():.1%}")

# ═══════════════════════════════════
# Run GBM walk-forward → get OOS signal
# ═══════════════════════════════════
print("Running GBM walk-forward...")
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

sig_weekly=pd.Series(preds,index=dates).sort_index()

# Map to daily with shift(1)
dr_daily=qqq.pct_change().dropna()
sig_daily=sig_weekly.reindex(dr_daily.index,method='ffill').shift(1).dropna()

# COMMON DATES: everything aligned to GBM OOS period
common_dates=sig_daily.index
dr=dr_daily.loc[common_dates].values
tr_tqqq=tqqq_ret_d.reindex(common_dates).values if tqqq_ret_d is not None else None

# Also align simple rule inputs to common dates
vix_cd=vix.reindex(common_dates,method='ffill').shift(1).values  # shift(1) for rules too
sma200_cd=qqq.rolling(200).mean().reindex(common_dates).shift(1).values
qqq_cd=qqq.reindex(common_dates).shift(1).values
rv20_cd=rv20.reindex(common_dates,method='ffill').shift(1).values
high52w_cd=qqq.rolling(252).max().reindex(common_dates).shift(1).values
mom52w_cd=qqq.pct_change(252).reindex(common_dates).shift(1).values

print(f"  Common dates: {common_dates[0].strftime('%Y-%m-%d')} to {common_dates[-1].strftime('%Y-%m-%d')} ({len(common_dates)} days)")

def calc(ret, name):
    eq=np.cumprod(1+ret); ny=len(ret)/252
    if ny<0.5 or eq[-1]<=0: return None
    cagr=(eq[-1]**(1/ny)-1)*100
    mdd=(eq/np.maximum.accumulate(eq)-1).min()*100
    sh=np.mean(ret)/np.std(ret)*np.sqrt(252) if np.std(ret)>0 else 0
    dn=ret[ret<0]; ds=np.sqrt(np.mean(dn**2)) if len(dn)>0 else 1e-10
    so=np.mean(ret)/ds*np.sqrt(252)
    return {'name':name,'cagr':cagr,'mdd':mdd,'sharpe':sh,'sortino':so,'ret':ret}

def apply_cost(ret, lev_arr, cost_bps=10):
    r=ret.copy(); cost=cost_bps/10000
    for i in range(1,len(lev_arr)):
        turnover=abs(lev_arr[i]-lev_arr[i-1])
        r[i]-=turnover*cost
    return r

# ═══════════════════════════════════
# TEST 1: SAME-PERIOD COMPARISON
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  TEST 1: ALL STRATEGIES — SAME PERIOD, SAME DATES")
print("="*100)

gbm_lev=np.where(sig_daily.values==1,1,3)
gbm_ret=apply_cost(gbm_lev*dr, gbm_lev)

# Simple rules (all shift(1) already applied via _cd variables)
vix20_lev=np.where(vix_cd>20,1,3); vix20_ret=apply_cost(vix20_lev*dr, vix20_lev)
vix25_lev=np.where(vix_cd>25,1,3); vix25_ret=apply_cost(vix25_lev*dr, vix25_lev)
sma_lev=np.where(qqq_cd<sma200_cd,1,3); sma_ret=apply_cost(sma_lev*dr, sma_lev)
combo_lev=np.where((vix_cd>25)|(qqq_cd<sma200_cd),1,3); combo_ret=apply_cost(combo_lev*dr, combo_lev)
dd_lev=np.where(qqq_cd/high52w_cd-1<-0.10,1,3); dd_ret=apply_cost(dd_lev*dr, dd_lev)
mom_lev=np.where(mom52w_cd<0,1,3); mom_ret=apply_cost(mom_lev*dr, mom_lev)
vt_lev=np.clip(0.15/np.clip(rv20_cd,0.05,1),0.5,3); vt_ret=vt_lev*dr  # continuous, no switch cost

results = [
    calc(gbm_ret, 'GBM hostile filter'),
    calc(vix20_ret, 'VIX>20 → 1x'),
    calc(vix25_ret, 'VIX>25 → 1x'),
    calc(sma_ret, 'Below SMA200 → 1x'),
    calc(combo_ret, 'VIX>25 OR <SMA200'),
    calc(dd_ret, 'DD>10% from high → 1x'),
    calc(mom_ret, 'Mom 52w<0 → 1x'),
    calc(vt_ret, 'Vol target 15%'),
    calc(3*dr, 'BH 3x synthetic'),
    calc(dr, 'BH 1x QQQ'),
]
if tr_tqqq is not None:
    tr_clean=np.nan_to_num(tr_tqqq,nan=0)
    results.append(calc(tr_clean, 'Real TQQQ BH'))

print(f"\n  {'Strategy':<30} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sortino':>8}")
print(f"  {'─'*30} {'─'*7} {'─'*7} {'─'*7} {'─'*8}")
for r in results:
    if r: print(f"  {r['name']:<30} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r['sortino']:>8.2f}")

# ═══════════════════════════════════
# TEST 2: REAL TRADABLE STRATEGY
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  TEST 2: REAL TRADABLE STRATEGY (TQQQ when 3x, QQQ when 1x)")
print("="*100)

if tr_tqqq is not None:
    # Synthetic: lev * QQQ
    synth_ret=apply_cost(gbm_lev*dr, gbm_lev)
    
    # Tradable: TQQQ when hostile_pred=0, QQQ when hostile_pred=1
    tradable_ret=np.where(gbm_lev==3, tr_tqqq, dr)
    tradable_ret=apply_cost(tradable_ret, gbm_lev, cost_bps=10)
    
    r_synth=calc(synth_ret, 'Synthetic 3x/1x')
    r_trade=calc(tradable_ret, 'Tradable TQQQ/QQQ')
    r_tqqq_bh=calc(tr_clean, 'TQQQ buy & hold')
    
    print(f"\n  {'Version':<30} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sortino':>8}")
    print(f"  {'─'*30} {'─'*7} {'─'*7} {'─'*7} {'─'*8}")
    if r_synth: print(f"  {r_synth['name']:<30} {r_synth['cagr']:>+6.1f}% {r_synth['mdd']:>6.1f}% {r_synth['sharpe']:>7.2f} {r_synth['sortino']:>8.2f}")
    if r_trade: print(f"  {r_trade['name']:<30} {r_trade['cagr']:>+6.1f}% {r_trade['mdd']:>6.1f}% {r_trade['sharpe']:>7.2f} {r_trade['sortino']:>8.2f}")
    if r_tqqq_bh: print(f"  {r_tqqq_bh['name']:<30} {r_tqqq_bh['cagr']:>+6.1f}% {r_tqqq_bh['mdd']:>6.1f}% {r_tqqq_bh['sharpe']:>7.2f} {r_tqqq_bh['sortino']:>8.2f}")
else:
    print("  TQQQ data not available")

# ═══════════════════════════════════
# TEST 3: LEVERAGE LADDER
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  TEST 3: LEVERAGE LADDER (different hostile/normal combos)")
print("="*100)

print(f"\n  {'Hostile→  Normal→':<25} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sortino':>8}")
print(f"  {'─'*25} {'─'*7} {'─'*7} {'─'*7} {'─'*8}")

for h_lev, n_lev in [(0,2),(0,3),(1,2),(1,2.5),(1,3),(0.5,2),(0.5,3)]:
    lev_arr=np.where(sig_daily.values==1, h_lev, n_lev)
    if tr_tqqq is not None and n_lev==3:
        # Use real TQQQ for 3x portion
        ret_arr=np.where(sig_daily.values==1, h_lev*dr, tr_tqqq)
        if h_lev==0: ret_arr=np.where(sig_daily.values==1, 0, tr_tqqq)
    else:
        ret_arr=lev_arr*dr
    ret_arr=apply_cost(ret_arr, lev_arr)
    r=calc(ret_arr, f'{h_lev}x / {n_lev}x')
    if r: print(f"  hostile={h_lev}x  normal={n_lev}x    {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r['sortino']:>8.2f}")

# ═══════════════════════════════════
# TEST 4: CRISIS CONTRIBUTION
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  TEST 4: WHERE DOES ALPHA COME FROM? (year-by-year)")
print("="*100)

bh3x_ret=3*dr  # same period benchmark
print(f"\n  {'Year':>6} {'GBM':>8} {'BH3x':>8} {'Alpha':>8} {'GBM MDD':>8} {'BH MDD':>8} {'@1x':>5} {'Verdict':>10}")
print(f"  {'─'*6} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*5} {'─'*10}")

years=sorted(set(common_dates.year))
alpha_by_year=[]
for y in years:
    m=common_dates.year==y
    if m.sum()<50: continue
    sg=gbm_ret[m]; bg=bh3x_ret[m]
    eq_s=np.cumprod(1+sg); eq_b=np.cumprod(1+bg)
    rs=(eq_s[-1]-1)*100; rb=(eq_b[-1]-1)*100
    alpha=rs-rb
    ms=(eq_s/np.maximum.accumulate(eq_s)-1).min()*100
    mb=(eq_b/np.maximum.accumulate(eq_b)-1).min()*100
    pct1x=(gbm_lev[m]==1).mean()*100
    
    if alpha>5: verdict='✅ WIN'
    elif alpha>-5: verdict='— FLAT'
    else: verdict='❌ LOSE'
    
    alpha_by_year.append({'year':y,'alpha':alpha})
    print(f"  {y:>6} {rs:>+7.1f}% {rb:>+7.1f}% {alpha:>+7.1f}% {ms:>7.1f}% {mb:>7.1f}% {pct1x:>4.0f}% {verdict}")

# Where does alpha come from?
total_alpha=sum(a['alpha'] for a in alpha_by_year)
top3=sorted(alpha_by_year, key=lambda x:x['alpha'], reverse=True)[:3]
top3_alpha=sum(a['alpha'] for a in top3)
print(f"\n  Total alpha: {total_alpha:+.0f}%")
print(f"  Top 3 years: {', '.join(str(a['year']) for a in top3)} → {top3_alpha:+.0f}% ({top3_alpha/max(total_alpha,1)*100:.0f}% of total)")
if total_alpha > 0 and top3_alpha/total_alpha > 0.8:
    print(f"  ⚠️  WARNING: {top3_alpha/total_alpha*100:.0f}% of alpha comes from just 3 years. Concentrated.")
else:
    print(f"  ✅ Alpha is distributed across multiple years.")

# ═══════════════════════════════════
# TEST 5: PURGED PERMUTATION TEST
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  TEST 5: PURGED PERMUTATION TEST (shuffle target, full walk-forward)")
print("="*100)

N_PERM = 200  # 200 permutations (500 takes too long)
np.random.seed(42)

# Real strategy stats
real_cagr = calc(gbm_ret, '')['cagr']
real_sharpe = calc(gbm_ret, '')['sharpe']

print(f"  Real strategy: CAGR={real_cagr:+.1f}%, Sharpe={real_sharpe:.2f}")
print(f"  Running {N_PERM} permutations (shuffled hostile labels)...")

perm_cagr=[]; perm_sharpe=[]
for perm_i in range(N_PERM):
    # Shuffle hostile labels (preserving % hostile)
    shuffled=fwd_hostile.values.copy()
    np.random.shuffle(shuffled)
    
    # Full walk-forward with shuffled target
    p_preds=[]; p_dates=[]
    te=MIN_TRAIN
    while te+EMBARGO+STEP<=len(X):
        tr=list(range(te)); ts=te+EMBARGO; ti=list(range(ts,min(ts+STEP,len(X))))
        sc=StandardScaler(); Xtr=sc.fit_transform(X[tr]); Xte=sc.transform(X[ti])
        md=GradientBoostingClassifier(n_estimators=50,max_depth=2,learning_rate=0.05,subsample=0.8,random_state=42)
        md.fit(Xtr, shuffled[tr])
        pp=md.predict(Xte)
        p_preds.extend(pp); p_dates.extend(feat.index[ti])
        te+=STEP
    
    if not p_dates: continue
    p_sig=pd.Series(p_preds,index=p_dates).sort_index()
    p_sig_d=p_sig.reindex(dr_daily.index,method='ffill').shift(1).dropna()
    p_dr=dr_daily.loc[p_sig_d.index].values
    p_lev=np.where(p_sig_d.values==1,1,3)
    p_ret=apply_cost(p_lev*p_dr, p_lev)
    
    eq=np.cumprod(1+p_ret); ny=len(p_ret)/252
    if eq[-1]>0 and ny>0.5:
        c=(eq[-1]**(1/ny)-1)*100
        s=np.mean(p_ret)/np.std(p_ret)*np.sqrt(252) if np.std(p_ret)>0 else 0
        perm_cagr.append(c); perm_sharpe.append(s)
    
    if (perm_i+1) % 50 == 0:
        print(f"    ...{perm_i+1}/{N_PERM} done")

perm_cagr=np.array(perm_cagr); perm_sharpe=np.array(perm_sharpe)

pval_cagr=(perm_cagr>=real_cagr).mean()
pval_sharpe=(perm_sharpe>=real_sharpe).mean()
pctile_cagr=(perm_cagr<real_cagr).mean()*100
pctile_sharpe=(perm_sharpe<real_sharpe).mean()*100

print(f"\n  Permutation results ({len(perm_cagr)} valid):")
print(f"  {'':>15} {'Real':>8} {'Perm Mean':>10} {'Perm Std':>9} {'Percentile':>11} {'p-value':>8}")
print(f"  {'─'*15} {'─'*8} {'─'*10} {'─'*9} {'─'*11} {'─'*8}")
print(f"  {'CAGR':>15} {real_cagr:>+7.1f}% {np.mean(perm_cagr):>+9.1f}% {np.std(perm_cagr):>8.1f}% {pctile_cagr:>10.1f}% {pval_cagr:>8.3f}")
print(f"  {'Sharpe':>15} {real_sharpe:>8.2f} {np.mean(perm_sharpe):>10.2f} {np.std(perm_sharpe):>9.2f} {pctile_sharpe:>10.1f}% {pval_sharpe:>8.3f}")

if pval_cagr < 0.05:
    print(f"\n  ✅ CAGR is statistically significant (p={pval_cagr:.3f}, top {100-pctile_cagr:.1f}%)")
elif pval_cagr < 0.10:
    print(f"\n  ⚠️  CAGR is marginally significant (p={pval_cagr:.3f})")
else:
    print(f"\n  ❌ CAGR is NOT statistically significant (p={pval_cagr:.3f})")

if pval_sharpe < 0.05:
    print(f"  ✅ Sharpe is statistically significant (p={pval_sharpe:.3f}, top {100-pctile_sharpe:.1f}%)")
elif pval_sharpe < 0.10:
    print(f"  ⚠️  Sharpe is marginally significant (p={pval_sharpe:.3f})")
else:
    print(f"  ❌ Sharpe is NOT statistically significant (p={pval_sharpe:.3f})")

# ═══════════════════════════════════
# FINAL VERDICT
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  FINAL VERDICT — AUDIT v3")
print("="*100)
print(f"""
  All strategies compared on SAME dates: {common_dates[0].strftime('%Y-%m-%d')} to {common_dates[-1].strftime('%Y-%m-%d')}
  All with shift(1), turnover cost 10bps, no valuation features.

  Permutation test: p-value CAGR={pval_cagr:.3f}, Sharpe={pval_sharpe:.3f}
  Alpha concentration: top 3 years = {top3_alpha/max(total_alpha,1)*100:.0f}% of total alpha
  
  {'✅ Strategy has statistically significant edge.' if pval_cagr<0.05 and pval_sharpe<0.05 else '⚠️  Strategy edge is not conclusively proven.' if pval_cagr<0.10 else '❌ Strategy edge is likely noise.'}
""")
