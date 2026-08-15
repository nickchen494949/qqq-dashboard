#!/usr/bin/env python3
"""
Follow-up validation:
B. Remove reversal factor → do other agents still have edge?
C. Reversal signal PnL (not just accuracy)
D. Regime-conditional testing
"""
import os, sys, warnings
import numpy as np, pandas as pd
from numpy.linalg import lstsq

warnings.filterwarnings('ignore')
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, 'tools'))
from strategy_engine import get_fred_api_key
from fredapi import Fred

DATA_DIR = os.path.join(PROJECT_DIR, 'market_data', 'ml_cache')
def lf(sid): return pd.read_csv(os.path.join(DATA_DIR, f'fred_{sid}.csv'), index_col=0, parse_dates=True).squeeze()
def ly(t): return pd.read_csv(os.path.join(DATA_DIR, f'yahoo_{t}.csv'), index_col=0, parse_dates=True).squeeze()

print("Loading...")
qqq = ly('QQQ'); vix = lf('VIXCLS'); hy_oas = lf('BAMLH0A0HYM2')
nfci = lf('NFCI'); t10y = lf('DGS10'); t10y2y = lf('T10Y2Y')

idx = qqq.dropna().index
qqq = qqq.reindex(idx)
vix = vix.reindex(idx, method='ffill').ffill()
hy_oas = hy_oas.reindex(idx, method='ffill').ffill()
nfci = nfci.resample('D').ffill().reindex(idx, method='ffill').ffill()
t10y = t10y.reindex(idx, method='ffill').ffill()
t10y2y = t10y2y.reindex(idx, method='ffill').ffill()

m = idx >= '2007-01-01'
idx=idx[m]; qqq=qqq[m]; vix=vix[m]; hy_oas=hy_oas[m]; nfci=nfci[m]; t10y=t10y[m]; t10y2y=t10y2y[m]
ret = qqq.pct_change()
ret_1d = ret.fillna(0)
ret_5d = qqq.pct_change(5).fillna(0)
ret_20d = qqq.pct_change(20).fillna(0)
mom_12m = qqq.pct_change(252).fillna(0)
sma50 = qqq.rolling(50).mean()
sma200 = qqq.rolling(200).mean()

# Build signals (NO reversal/MM)
signals = pd.DataFrame(index=idx)
signals['passive'] = 1.0
signals.loc[signals.index.day <= 5, 'passive'] = 1.3

qqq_200w = qqq.rolling(252*4).mean()
yield_chg = t10y - t10y.shift(63)
signals['value'] = (-(qqq/qqq_200w - 1) - yield_chg.fillna(0)*0.3).clip(-2,2)

sma_sig = (sma50/sma200 - 1)*10
signals['momentum'] = ((mom_12m*3 + sma_sig.fillna(0))/2).clip(-3,3)

vix_z = (vix-vix.rolling(252).mean())/vix.rolling(252).std().replace(0,1)
hy_z = (hy_oas-hy_oas.rolling(252).mean())/hy_oas.rolling(252).std().replace(0,1)
nfci_z = (nfci-nfci.rolling(252).mean())/nfci.rolling(252).std().replace(0,1)
signals['hedge'] = (-(vix_z.fillna(0)*0.4+hy_z.fillna(0)*0.3+nfci_z.fillna(0)*0.2)+t10y2y.fillna(0)*0.1).clip(-3,3)

vix_inv = 1/(vix/20).clip(0.5,3)
signals['retail'] = (mom_12m*vix_inv.fillna(1)*2).clip(-3,3)
signals.loc[ret_20d < -0.1, 'retail'] = (signals.loc[ret_20d < -0.1, 'retail']-1.5).clip(-3,3)

rv = ret_1d.rolling(20).std()*np.sqrt(252)*100
iv = vix.fillna(20)
vs = iv - rv.fillna(iv)
gex_raw = (-vs.fillna(0)/10 + (20-vix.clip(10,40).fillna(20))/20).clip(-3,3)
signals['gex'] = (gex_raw * -(ret_5d*3)).clip(-3,3)

signals = signals.dropna()
ci = signals.index.intersection(ret.dropna().index)
signals = signals.loc[ci]
returns = ret.loc[ci]
agent_names = list(signals.columns)

print(f"  {len(signals)} days, {len(agent_names)} agents (NO reversal)")

# ═══════════════════════════════════════
# B. OOS TEST WITHOUT REVERSAL
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("  B. AGENTS WITHOUT DAILY REVERSAL — DO THEY HAVE ANY OOS POWER?")
print("=" * 90)

MIN_TRAIN = 5*252
STEP = 252

wf = []
train_end = MIN_TRAIN
while train_end + STEP <= len(signals):
    X_tr = signals.iloc[:train_end].values
    y_tr = returns.iloc[:train_end].values
    X_te = signals.iloc[train_end:train_end+STEP].values
    y_te = returns.iloc[train_end:train_end+STEP].values
    
    mu = X_tr.mean(0); sd = X_tr.std(0); sd[sd==0]=1
    Xn_tr = (X_tr-mu)/sd; Xn_te = (X_te-mu)/sd
    
    A = np.column_stack([np.ones(len(Xn_tr)), Xn_tr])
    b,_,_,_ = lstsq(A, y_tr, rcond=None)
    
    y_pred = np.column_stack([np.ones(len(Xn_te)), Xn_te]) @ b
    ss_res = np.sum((y_te-y_pred)**2)
    ss_tot = np.sum((y_te-y_te.mean())**2)
    r2 = 1-ss_res/ss_tot if ss_tot>0 else 0
    
    d_acc = np.mean((y_pred>0)==(y_te>0))
    corr = np.corrcoef(y_pred, y_te)[0,1] if np.std(y_pred)>0 else 0
    
    ts = signals.index[train_end]
    te = signals.index[min(train_end+STEP-1, len(signals)-1)]
    wf.append({'year':ts.year, 'r2':r2, 'dir':d_acc, 'corr':corr})
    train_end += STEP

baseline_up = (returns > 0).mean()
print(f"\n  Baseline (always up): {baseline_up:.1%}")
print(f"\n  {'Year':>6} {'R²(OOS)':>8} {'Dir%':>6} {'Corr':>7}")
print(f"  {'─'*6} {'─'*8} {'─'*6} {'─'*7}")
for r in wf:
    mark = '✅' if r['r2']>0 else '❌'
    print(f"  {r['year']:>6} {mark}{r['r2']:>6.4f} {r['dir']:>5.1%} {r['corr']:>+6.3f}")

avg_r2 = np.mean([r['r2'] for r in wf])
avg_dir = np.mean([r['dir'] for r in wf])
pos_r2 = sum(r['r2']>0 for r in wf)
print(f"\n  Summary: Avg R²={avg_r2:.4f} | Avg Dir={avg_dir:.1%} | R²>0: {pos_r2}/{len(wf)}")
print(f"  vs Baseline always-up: {baseline_up:.1%}")
print(f"  Edge over blind guess: {(avg_dir-baseline_up)*100:+.1f}pp")

# ═══════════════════════════════════════
# C. REVERSAL SIGNAL PNL
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("  C. DAILY REVERSAL SIGNAL — PNL ANALYSIS")
print("=" * 90)
print("  Rule: if yesterday down → buy (3x). if yesterday up → reduce (1x).")

# Simple reversal strategy on QQQ
yesterday_ret = ret.shift(1).loc[ci]
today_ret = returns

# Strategy: yesterday down → 3x, yesterday up → 1x
lev = np.where(yesterday_ret < 0, 3, 1)
strat_ret = lev * today_ret.values

# Also test inverted: yesterday down → 1x, yesterday up → 3x (momentum)
lev_mom = np.where(yesterday_ret > 0, 3, 1)
strat_mom = lev_mom * today_ret.values

# BH 3x
bh3x = 3 * today_ret.values

# BH 1x
bh1x = today_ret.values

strategies = {
    'Reversal (down→3x, up→1x)': strat_ret,
    'Momentum (up→3x, down→1x)': strat_mom,
    'Buy & Hold 3x': bh3x,
    'Buy & Hold 1x': bh1x,
}

# Remove NaN
valid = ~np.isnan(yesterday_ret.values)

print(f"\n  {'Strategy':<32} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sortino':>8} {'AvgWin':>7} {'AvgLoss':>8} {'W/L':>5} {'Worst':>7}")
print(f"  {'─'*32} {'─'*7} {'─'*7} {'─'*7} {'─'*8} {'─'*7} {'─'*8} {'─'*5} {'─'*7}")

for name, rets in strategies.items():
    r = rets[valid]
    eq = np.cumprod(1 + r)
    ny = len(r)/252
    cagr = (eq[-1]**(1/ny)-1)*100
    rm = np.maximum.accumulate(eq)
    mdd = (eq/rm-1).min()*100
    sh = np.mean(r)/np.std(r)*np.sqrt(252) if np.std(r)>0 else 0
    down = r[r<0]
    ds = np.sqrt(np.mean(down**2)) if len(down)>0 else 1e-10
    so = np.mean(r)/ds*np.sqrt(252)
    wins = r[r>0]; losses = r[r<0]
    avg_w = np.mean(wins)*100 if len(wins)>0 else 0
    avg_l = np.mean(losses)*100 if len(losses)>0 else 0
    wl = len(wins)/len(losses) if len(losses)>0 else 99
    worst = np.min(r)*100
    print(f"  {name:<32} {cagr:>+6.1f}% {mdd:>6.1f}% {sh:>7.2f} {so:>8.2f} {avg_w:>+6.2f}% {avg_l:>+7.2f}% {wl:>4.2f} {worst:>+6.1f}%")

# After cost (assume 5bps round trip per trade)
cost_per_trade = 0.0005
n_trades = np.sum(np.diff(lev[valid]) != 0)
total_cost = n_trades * cost_per_trade
print(f"\n  Reversal trades: {n_trades} switches over {np.sum(valid)} days")
print(f"  Estimated cost: {n_trades} × 5bps = {total_cost*100:.1f}% total drag")

# ═══════════════════════════════════════
# D. REGIME-CONDITIONAL REVERSAL
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("  D. DOES REVERSAL WORK IN ALL REGIMES?")
print("=" * 90)

vix_aligned = vix.reindex(ci).ffill()
sma200_aligned = sma200.reindex(ci).ffill()
hy_aligned = hy_oas.reindex(ci, method='ffill').ffill()

regimes = {
    'VIX < 20 (calm)':        vix_aligned < 20,
    'VIX 20-30 (elevated)':   (vix_aligned >= 20) & (vix_aligned < 30),
    'VIX > 30 (panic)':       vix_aligned >= 30,
    'Above SMA200':           qqq.reindex(ci) > sma200_aligned,
    'Below SMA200':           qqq.reindex(ci) <= sma200_aligned,
    'HY spread < 4 (normal)': hy_aligned < 4,
    'HY spread > 5 (stress)': hy_aligned >= 5,
}

print(f"\n  {'Regime':<28} {'Days':>5} │ {'Rev CAGR':>9} {'BH3x CAGR':>10} {'Rev MDD':>8} {'BH3x MDD':>9} │ {'Rev Win':>8}")
print(f"  {'─'*28} {'─'*5} │ {'─'*9} {'─'*10} {'─'*8} {'─'*9} │ {'─'*8}")

for rname, rmask in regimes.items():
    rmask_v = rmask.values & valid
    if rmask_v.sum() < 50: continue
    
    r_rev = strat_ret[rmask_v]
    r_bh = bh3x[rmask_v]
    
    ny = len(r_rev)/252
    if ny < 0.1: continue
    
    eq_rev = np.cumprod(1+r_rev)
    eq_bh = np.cumprod(1+r_bh)
    
    cagr_rev = (eq_rev[-1]**(1/ny)-1)*100 if eq_rev[-1]>0 else -99
    cagr_bh = (eq_bh[-1]**(1/ny)-1)*100 if eq_bh[-1]>0 else -99
    
    mdd_rev = ((eq_rev/np.maximum.accumulate(eq_rev))-1).min()*100
    mdd_bh = ((eq_bh/np.maximum.accumulate(eq_bh))-1).min()*100
    
    rev_better = '✅' if cagr_rev > cagr_bh else '❌'
    
    print(f"  {rname:<28} {rmask_v.sum():>5} │ {cagr_rev:>+8.1f}% {cagr_bh:>+9.1f}% {mdd_rev:>7.1f}% {mdd_bh:>8.1f}% │ {rev_better:>8}")

# ═══════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("  FINAL SUMMARY")
print("=" * 90)
print(f"""
  B. Without reversal factor:
     → Avg OOS R² = {avg_r2:.4f}
     → Direction edge over blind guess: {(avg_dir-baseline_up)*100:+.1f}pp
     → Other agents alone: {'有一定 edge' if avg_dir > baseline_up + 0.02 else '几乎没有 edge'}

  C. Reversal as trading strategy:
     → High accuracy but check CAGR/MDD vs buy-and-hold above
     → Transaction cost drag from frequent switching

  D. Regime matters:
     → Reversal in calm market vs panic market — see table above
     → If reversal fails in VIX>30 or below SMA200, 
       it confirms: mean reversion only works in non-hostile regimes.
""")
