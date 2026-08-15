#!/usr/bin/env python3
"""
AUDIT v4 — Final permutation test fixes.
Fix 1: Permutation uses SAME model as real (n_estimators=150, max_depth=3)
Fix 2: Circular shift (not random shuffle) to preserve temporal structure
Fix 3: Test both synthetic AND tradable TQQQ/QQQ p-values
Fix 4: Drop TQQQ NaN instead of filling with 0
Fix 5: Log-return alpha concentration
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

# FIX 1: Single model function used everywhere
def make_model():
    return GradientBoostingClassifier(
        n_estimators=150, max_depth=3, learning_rate=0.05,
        subsample=0.8, random_state=42
    )

# ═══════════════════════════════════
# DATA
# ═══════════════════════════════════
print("Loading...")
qqq=gy('QQQ'); tqqq=gy('TQQQ'); spy=gy('SPY')
vix=gf('VIXCLS'); credit=gf('BAA10Y')
nfci=gf('NFCI'); t10y=gf('DGS10'); t2y=gf('DGS2'); t10y2y=gf('T10Y2Y')

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

# Features (NO valuation)
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
# Walk-forward function (used by real + permutation)
# ═══════════════════════════════════
def walk_forward(target_vals):
    """Run full walk-forward. Returns weekly signal series."""
    preds=[]; dates=[]
    te=MIN_TRAIN
    while te+EMBARGO+STEP<=len(X):
        tr=list(range(te)); ts=te+EMBARGO; ti=list(range(ts,min(ts+STEP,len(X))))
        sc=StandardScaler(); Xtr=sc.fit_transform(X[tr]); Xte=sc.transform(X[ti])
        m=make_model()  # FIX 1: same model everywhere
        m.fit(Xtr, target_vals[tr])
        p=m.predict(Xte)
        preds.extend(p); dates.extend(feat.index[ti])
        te+=STEP
    return pd.Series(preds, index=dates).sort_index()

def apply_cost(ret, lev_arr, cost_bps=10):
    r=ret.copy(); cost=cost_bps/10000
    for i in range(1,len(lev_arr)):
        r[i]-=abs(lev_arr[i]-lev_arr[i-1])*cost
    return r

def stats(ret):
    eq=np.cumprod(1+ret); ny=len(ret)/252
    if ny<0.5 or eq[-1]<=0: return None
    cagr=(eq[-1]**(1/ny)-1)*100
    mdd=(eq/np.maximum.accumulate(eq)-1).min()*100
    sh=np.mean(ret)/np.std(ret)*np.sqrt(252) if np.std(ret)>0 else 0
    dn=ret[ret<0]; ds=np.sqrt(np.mean(dn**2)) if len(dn)>0 else 1e-10
    so=np.mean(ret)/ds*np.sqrt(252)
    return {'cagr':cagr,'mdd':mdd,'sharpe':sh,'sortino':so}

# ═══════════════════════════════════
# REAL STRATEGY
# ═══════════════════════════════════
print("Running real GBM...")
sig_real = walk_forward(fwd_hostile.values)
dr_daily=qqq.pct_change().dropna()
sig_d=sig_real.reindex(dr_daily.index,method='ffill').shift(1).dropna()

# FIX 4: Drop NaN from TQQQ instead of filling with 0
tqqq_d=tqqq_ret_d.reindex(sig_d.index) if tqqq_ret_d is not None else None
valid_mask=np.isfinite(dr_daily.loc[sig_d.index].values)
if tqqq_d is not None:
    valid_mask = valid_mask & np.isfinite(tqqq_d.values)

common_dates=sig_d.index[valid_mask]
sig_d=sig_d.loc[common_dates]
dr=dr_daily.loc[common_dates].values
tr_tqqq=tqqq_d.loc[common_dates].values if tqqq_d is not None else None

print(f"  Common dates: {common_dates[0].strftime('%Y-%m-%d')} to {common_dates[-1].strftime('%Y-%m-%d')} ({len(common_dates)} days)")

gbm_lev=np.where(sig_d.values==1,1,3)

# Synthetic
synth_ret=apply_cost(gbm_lev*dr, gbm_lev)
r_synth=stats(synth_ret)

# Tradable (TQQQ when 3x, QQQ when 1x)
if tr_tqqq is not None:
    trade_ret=np.where(gbm_lev==3, tr_tqqq, dr)
    trade_ret=apply_cost(trade_ret, gbm_lev)
    r_trade=stats(trade_ret)
else:
    trade_ret=None; r_trade=None

# Benchmarks
bh3x_ret=3*dr
r_bh3x=stats(bh3x_ret)
r_tqqq_bh=stats(tr_tqqq) if tr_tqqq is not None else None
r_bh1x=stats(dr)

print(f"\n{'='*100}")
print("  REAL STRATEGY RESULTS (same period, all fixes)")
print("="*100)
print(f"\n  {'Strategy':<30} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sortino':>8}")
print(f"  {'─'*30} {'─'*7} {'─'*7} {'─'*7} {'─'*8}")
print(f"  {'GBM synthetic 3x/1x':<30} {r_synth['cagr']:>+6.1f}% {r_synth['mdd']:>6.1f}% {r_synth['sharpe']:>7.2f} {r_synth['sortino']:>8.2f}")
if r_trade: print(f"  {'GBM tradable TQQQ/QQQ':<30} {r_trade['cagr']:>+6.1f}% {r_trade['mdd']:>6.1f}% {r_trade['sharpe']:>7.2f} {r_trade['sortino']:>8.2f}")
print(f"  {'BH 3x synthetic':<30} {r_bh3x['cagr']:>+6.1f}% {r_bh3x['mdd']:>6.1f}% {r_bh3x['sharpe']:>7.2f} {r_bh3x['sortino']:>8.2f}")
if r_tqqq_bh: print(f"  {'Real TQQQ BH':<30} {r_tqqq_bh['cagr']:>+6.1f}% {r_tqqq_bh['mdd']:>6.1f}% {r_tqqq_bh['sharpe']:>7.2f} {r_tqqq_bh['sortino']:>8.2f}")
print(f"  {'BH 1x QQQ':<30} {r_bh1x['cagr']:>+6.1f}% {r_bh1x['mdd']:>6.1f}% {r_bh1x['sharpe']:>7.2f} {r_bh1x['sortino']:>8.2f}")

# ═══════════════════════════════════
# YEAR-BY-YEAR with log alpha (FIX 5)
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  YEAR-BY-YEAR ALPHA (log-return based)")
print("="*100)

log_synth=np.log1p(synth_ret)
log_bh3x=np.log1p(bh3x_ret)
log_alpha_daily=log_synth-log_bh3x

if tr_tqqq is not None:
    log_trade=np.log1p(trade_ret)
    log_tqqq=np.log1p(tr_tqqq)
    log_alpha_trade=log_trade-log_tqqq

print(f"\n  {'Year':>6} {'Synth α':>9} {'Trade α':>9} {'GBM MDD':>8} {'BH MDD':>8} {'@1x':>5}")
print(f"  {'─'*6} {'─'*9} {'─'*9} {'─'*8} {'─'*8} {'─'*5}")

years=sorted(set(common_dates.year))
yearly_log_alpha=[]
for y in years:
    m=common_dates.year==y
    if m.sum()<50: continue
    la_s=log_alpha_daily[m].sum()*100  # log alpha in %
    la_t=log_alpha_trade[m].sum()*100 if tr_tqqq is not None else 0
    
    eq_g=np.cumprod(1+synth_ret[m]); eq_b=np.cumprod(1+bh3x_ret[m])
    mg=(eq_g/np.maximum.accumulate(eq_g)-1).min()*100
    mb=(eq_b/np.maximum.accumulate(eq_b)-1).min()*100
    p1x=(gbm_lev[m]==1).mean()*100
    
    yearly_log_alpha.append(la_s)
    v='✅' if la_s>2 else ('❌' if la_s<-2 else '—')
    print(f"  {y:>6} {la_s:>+8.1f}% {la_t:>+8.1f}% {mg:>7.1f}% {mb:>7.1f}% {p1x:>4.0f}% {v}")

total_log_alpha=sum(yearly_log_alpha)
yla=np.array(yearly_log_alpha)
pos_years=(yla>2).sum(); neg_years=(yla<-2).sum(); flat_years=len(yla)-pos_years-neg_years
top3_idx=np.argsort(yla)[-3:]
top3_sum=yla[top3_idx].sum()

print(f"\n  Total log-alpha: {total_log_alpha:+.1f}%")
print(f"  Win/Flat/Lose years: {pos_years}/{flat_years}/{neg_years}")
if total_log_alpha > 0:
    print(f"  Top 3 years contribute: {top3_sum:+.1f}% ({top3_sum/total_log_alpha*100:.0f}% of total)")
else:
    print(f"  Total alpha is negative. Top 3 contribute: {top3_sum:+.1f}%")

# ═══════════════════════════════════
# BEST LEVERAGE COMBO
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  LEVERAGE LADDER (tradable TQQQ/QQQ version)")
print("="*100)

print(f"\n  {'Hostile→Normal':<20} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sortino':>8}")
print(f"  {'─'*20} {'─'*7} {'─'*7} {'─'*7} {'─'*8}")

for h_lev, n_lev in [(0,2),(0.5,2),(1,2),(1,2.5),(1,3),(0,3),(0.5,3)]:
    lev_arr=np.where(sig_d.values==1, h_lev, n_lev)
    ret_arr=lev_arr*dr
    ret_arr=apply_cost(ret_arr, lev_arr)
    r=stats(ret_arr)
    if r: print(f"  {h_lev}x → {n_lev}x          {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r['sortino']:>8.2f}")

# ═══════════════════════════════════
# PERMUTATION TEST (FIX 1,2,3)
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  PERMUTATION TEST — CIRCULAR SHIFT")
print("  Same model (n_est=150, depth=3). Both synthetic + tradable.")
print("="*100)

N_PERM=200
np.random.seed(42)
n_targets=len(fwd_hostile)

real_synth_cagr=r_synth['cagr']
real_synth_sharpe=r_synth['sharpe']
real_trade_cagr=r_trade['cagr'] if r_trade else None
real_trade_sharpe=r_trade['sharpe'] if r_trade else None

print(f"\n  Real synthetic:  CAGR={real_synth_cagr:+.1f}% Sharpe={real_synth_sharpe:.2f}")
if real_trade_cagr: print(f"  Real tradable:   CAGR={real_trade_cagr:+.1f}% Sharpe={real_trade_sharpe:.2f}")
print(f"  Running {N_PERM} circular-shift permutations...")

perm_synth_cagr=[]; perm_synth_sharpe=[]
perm_trade_cagr=[]; perm_trade_sharpe=[]

for pi in range(N_PERM):
    # FIX 2: circular shift — preserves temporal structure
    shift_k = np.random.randint(26, n_targets-26)  # min 26 weeks shift
    shifted = np.roll(fwd_hostile.values, shift_k)
    
    # Full walk-forward with same model (FIX 1)
    p_sig = walk_forward(shifted)
    p_sig_d = p_sig.reindex(dr_daily.index, method='ffill').shift(1).dropna()
    p_sig_d = p_sig_d.loc[p_sig_d.index.isin(common_dates)]
    if len(p_sig_d) < 100: continue
    
    p_dr = dr_daily.loc[p_sig_d.index].values
    p_lev = np.where(p_sig_d.values==1, 1, 3)
    
    # Synthetic
    p_sr = apply_cost(p_lev * p_dr, p_lev)
    ps = stats(p_sr)
    if ps:
        perm_synth_cagr.append(ps['cagr'])
        perm_synth_sharpe.append(ps['sharpe'])
    
    # Tradable (FIX 3)
    if tr_tqqq is not None:
        p_tqqq = tqqq_ret_d.reindex(p_sig_d.index).values
        if np.all(np.isfinite(p_tqqq)):
            p_tr = np.where(p_lev==3, p_tqqq, p_dr)
            p_tr = apply_cost(p_tr, p_lev)
            pt = stats(p_tr)
            if pt:
                perm_trade_cagr.append(pt['cagr'])
                perm_trade_sharpe.append(pt['sharpe'])
    
    if (pi+1) % 50 == 0:
        print(f"    ...{pi+1}/{N_PERM} done")

perm_synth_cagr=np.array(perm_synth_cagr)
perm_synth_sharpe=np.array(perm_synth_sharpe)
perm_trade_cagr=np.array(perm_trade_cagr)
perm_trade_sharpe=np.array(perm_trade_sharpe)

print(f"\n  Results ({len(perm_synth_cagr)} synthetic, {len(perm_trade_cagr)} tradable permutations):")
print(f"\n  {'Metric':<25} {'Real':>8} {'Perm μ':>8} {'Perm σ':>8} {'%ile':>8} {'p-val':>8}")
print(f"  {'─'*25} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")

def perm_row(name, real_val, perm_arr):
    pv=(perm_arr>=real_val).mean()
    pc=(perm_arr<real_val).mean()*100
    print(f"  {name:<25} {real_val:>+7.1f} {np.mean(perm_arr):>+7.1f} {np.std(perm_arr):>7.1f} {pc:>7.1f}% {pv:>8.3f}")
    return pv

pv1=perm_row('Synthetic CAGR', real_synth_cagr, perm_synth_cagr)
pv2=perm_row('Synthetic Sharpe', real_synth_sharpe, perm_synth_sharpe)
if len(perm_trade_cagr)>10 and real_trade_cagr:
    pv3=perm_row('Tradable CAGR', real_trade_cagr, perm_trade_cagr)
    pv4=perm_row('Tradable Sharpe', real_trade_sharpe, perm_trade_sharpe)
else:
    pv3=pv4=1.0

# ═══════════════════════════════════
# SIMPLE RULE COMPARISON (same period)
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  SIMPLE RULE COMPARISON (same dates)")
print("="*100)

vix_cd=vix.reindex(common_dates,method='ffill').shift(1)
sma200_cd=qqq.rolling(200).mean().reindex(common_dates).shift(1)
qqq_cd=qqq.reindex(common_dates).shift(1)

print(f"\n  {'Rule':<30} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7}")
print(f"  {'─'*30} {'─'*7} {'─'*7} {'─'*7}")

for name, lev_arr in [
    ('VIX>25 → 1x', np.where(vix_cd.values>25,1,3)),
    ('Below SMA200 → 1x', np.where(qqq_cd.values<sma200_cd.values,1,3)),
    ('VIX>25 OR <SMA200', np.where((vix_cd.values>25)|(qqq_cd.values<sma200_cd.values),1,3)),
]:
    sr=apply_cost(lev_arr*dr, lev_arr)
    r=stats(sr)
    if r: print(f"  {name:<30} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f}")

print(f"  {'GBM hostile filter':<30} {r_synth['cagr']:>+6.1f}% {r_synth['mdd']:>6.1f}% {r_synth['sharpe']:>7.2f}")
print(f"  {'BH 3x':<30} {r_bh3x['cagr']:>+6.1f}% {r_bh3x['mdd']:>6.1f}% {r_bh3x['sharpe']:>7.2f}")
if r_tqqq_bh: print(f"  {'TQQQ BH':<30} {r_tqqq_bh['cagr']:>+6.1f}% {r_tqqq_bh['mdd']:>6.1f}% {r_tqqq_bh['sharpe']:>7.2f}")

# ═══════════════════════════════════
# FINAL VERDICT
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  FINAL VERDICT — AUDIT v4")
print("="*100)

sig_count=sum([pv1<0.05, pv2<0.05, pv3<0.05, pv4<0.05])
print(f"""
  Model: GBM (150 trees, depth 3) — no valuation features
  Test:  Walk-forward OOS, shift(1), turnover cost 10bps
  Perm:  {N_PERM} circular shifts, SAME model

  Permutation p-values:
    Synthetic CAGR:   {pv1:.3f} {'✅' if pv1<0.05 else '⚠️' if pv1<0.10 else '❌'}
    Synthetic Sharpe: {pv2:.3f} {'✅' if pv2<0.05 else '⚠️' if pv2<0.10 else '❌'}
    Tradable CAGR:    {pv3:.3f} {'✅' if pv3<0.05 else '⚠️' if pv3<0.10 else '❌'}
    Tradable Sharpe:  {pv4:.3f} {'✅' if pv4<0.05 else '⚠️' if pv4<0.10 else '❌'}

  Alpha distribution: {pos_years} win / {flat_years} flat / {neg_years} lose years
  Total log-alpha: {total_log_alpha:+.1f}%

  {'✅ EDGE CONFIRMED' if sig_count>=3 else '⚠️ PARTIAL EDGE' if sig_count>=2 else '❌ NO EDGE' }
  {sig_count}/4 metrics statistically significant at p<0.05.
""")
