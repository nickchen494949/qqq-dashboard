#!/usr/bin/env python3
"""Quick: 64 leverage combos with Sortino + Calmar."""
import os, sys, numpy as np, pandas as pd, yfinance as yf
from fredapi import Fred
from strategy_engine import *

FRED_API_KEY = get_fred_api_key()
PROJECT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP_DIR      = os.path.join(PROJECT_DIR, 'fomc_sep')

print("Loading data...")
fred = Fred(api_key=FRED_API_KEY)
def fetch_yahoo_ohlc(t):
    df = yf.download(t, start='2005-01-01', progress=False, auto_adjust=False)
    c = df['Close']; a = df['Adj Close'] if 'Adj Close' in df.columns else c; o = df['Open']
    if isinstance(c, pd.DataFrame): c = c.iloc[:,0]
    if isinstance(a, pd.DataFrame): a = a.iloc[:,0]
    if isinstance(o, pd.DataFrame): o = o.iloc[:,0]
    return a, o * (a/c)
def fetch_yahoo(t): return fetch_yahoo_ohlc(t)[0]

effr_raw = fred.get_series('DFF', observation_start='2005-01-01').dropna()
qqq_raw, qqq_open_raw = fetch_yahoo_ohlc('QQQ')
hyg_raw, ief_raw, tip_raw, tlt_raw = fetch_yahoo('HYG'), fetch_yahoo('IEF'), fetch_yahoo('TIP'), fetch_yahoo('TLT')

idx = qqq_raw.index[qqq_raw.index >= pd.Timestamp('2012-01-25')]
qqq_d = qqq_raw.reindex(idx); qqq_open = qqq_open_raw.reindex(idx)
dr_qqq = qqq_d.pct_change(); effr = effr_raw.reindex(idx).ffill() / 100 / 252
full_idx = qqq_raw.dropna().index
z_series = compute_credit_z(hyg_raw.reindex(full_idx).ffill(), ief_raw.reindex(full_idx).ffill()).reindex(idx)
vol_z = compute_vol_z(qqq_raw.reindex(full_idx).pct_change()).reindex(idx)
inf_z = compute_inflation_z(tip_raw.reindex(full_idx).ffill(), tlt_raw.reindex(full_idx).ffill()).reindex(idx)
sep_raw = parse_sep_pdfs(SEP_DIR)
sep_signals = build_sep_signals(sep_raw)
sep_state, _ = build_sep_state(sep_signals, idx)

N = len(idx)
dr_np = dr_qqq.values.astype(np.float64)
gap_np = (qqq_open / qqq_d.shift(1) - 1).values.astype(np.float64)
intra_np = (qqq_d / qqq_open - 1).values.astype(np.float64)
effr_np = effr.values.astype(np.float64)
z_np = z_series.values.astype(np.float64)
vz_np = vol_z.values.astype(np.float64)
iz_np = inf_z.values.astype(np.float64)
sep_np = sep_state.values.astype(np.float64)
EXP_D = EXPENSE_RATIO / 252
ZT, ZR = Z_TRIGGER, Z_RECOVER
VT, VR = VZ_TRIGGER, VZ_RECOVER
IT, IR = INF_TRIGGER, INF_RECOVER

def run(cr_lev, vz_lev, inf_lev, tc=TC_BPS):
    eq = 1.0; lev = 3.0; prev = 3.0; pending = -1.0
    in_trade = False; tee = 1.0
    in_d = False; vol_d = False; inf_d = False
    trades = 0; eql = np.empty(N)
    for i in range(N):
        si = sep_np[i]; prev_for_gap = lev; sw = False
        if pending >= 0:
            if pending != lev: sw = True
            lev = pending; pending = -1.0
        prof = (eq > tee) if in_trade else False
        z = z_np[i]; tgt = 3.0
        if si == 0:
            tgt = 0.0; in_d = False; vol_d = False; inf_d = False
        else:
            if not np.isnan(z):
                if not in_d and z > ZT: in_d = True
                elif in_d and z < ZR: in_d = False
            iiz = iz_np[i]
            if not np.isnan(iiz):
                if not inf_d and iiz > IT: inf_d = True
                elif inf_d and iiz < IR: inf_d = False
            vz = vz_np[i]
            if not np.isnan(vz):
                if not vol_d and vz > VT: vol_d = True
                elif vol_d and vz < VR: vol_d = False
            if in_d: tgt = cr_lev if prof else lev
            elif inf_d: tgt = inf_lev if prof else lev
            elif vol_d: tgt = vz_lev if prof else lev
            else: tgt = 3.0
        if tgt != lev: pending = tgt
        if lev > 0 and not in_trade: in_trade = True; tee = eq
        elif lev == 0 and in_trade: in_trade = False
        if lev != prev and lev > 0 and prev > 0:
            if lev > prev: tee = (tee * prev + eq * (lev - prev)) / lev
        if lev != prev: trades += 1
        if i > 0:
            r = dr_np[i]
            if np.isnan(r): r = 0.0
            if sw:
                rg = gap_np[i]; ri = intra_np[i]
                if np.isnan(rg): rg = 0.0
                if np.isnan(ri): ri = 0.0
                ra = (1 + prev_for_gap * rg) * (1 + lev * ri) - 1
            else: ra = lev * r
            bor = max(0, lev - 1) * effr_np[i] if lev > 1 else 0
            fee = EXP_D * min(lev / 3, 1) if lev > 1 else 0
            cy = effr_np[i] if lev == 0 else 0
            tc_cost = abs(lev - prev) * (tc / 10000)
            eq *= (1 + ra - bor - fee + cy - tc_cost)
            if eq < 0.001: eq = 0.001
        prev = lev; eql[i] = eq
    return eql, trades

def metrics(eql, start=0, end=None):
    if end is None: end = len(eql)
    sl = eql[start:end]; ny = len(sl) / 252
    sl_n = sl / sl[0]; cagr = sl_n[-1] ** (1/ny) - 1
    rm = np.maximum.accumulate(sl_n); mdd = (sl_n / rm - 1).min()
    rets = np.diff(sl) / sl[:-1]
    sh = (np.mean(rets) / np.std(rets)) * np.sqrt(252) if np.std(rets) > 0 else 0
    down = rets[rets < 0]
    down_std = np.sqrt(np.mean(down**2)) if len(down) > 0 else 1e-10
    sortino = (np.mean(rets) / down_std) * np.sqrt(252)
    calmar = cagr / abs(mdd) if mdd != 0 else 0
    return {'sh': sh, 'so': sortino, 'ca': calmar, 'cagr': cagr, 'mdd': mdd}

IS_END = np.searchsorted(idx, pd.Timestamp('2018-12-31'), side='right')
OOS_END = np.searchsorted(idx, pd.Timestamp('2022-12-31'), side='right')

print(f"Sealed triggers: CrT={ZT} CrR={ZR} VT={VT} VR={VR} IT={IT} IR={IR}")
print(f"Testing 64 leverage combos...\n")

results = []
for cl in [0,1,2,3]:
    for vl in [0,1,2,3]:
        for il in [0,1,2,3]:
            eql, trades = run(cl, vl, il)
            m_f = metrics(eql); m_is = metrics(eql, 0, IS_END)
            m_oos = metrics(eql, IS_END, OOS_END); m_fwd = metrics(eql, OOS_END)
            results.append({'cr': cl, 'vol': vl, 'inf': il, 'tr_yr': trades/(N/252),
                **{f'f_{k}': v for k,v in m_f.items()},
                **{f'is_{k}': v for k,v in m_is.items()},
                **{f'oos_{k}': v for k,v in m_oos.items()},
                **{f'fwd_{k}': v for k,v in m_fwd.items()},
            })

df = pd.DataFrame(results)

# ── Sort by Full Sortino ──
print("=" * 140)
print("  ALL 64 COMBOS — sorted by Full Sortino")
print("=" * 140)
print(f"  {'#':>3} {'Cr':>3} {'Vol':>3} {'Inf':>3} │ {'Sortino':>8} {'Sharpe':>8} {'Calmar':>8} {'CAGR':>8} {'MDD':>8} │ {'IS So':>7} {'OOS So':>7} {'FWD So':>7} │ {'Tr/yr':>5}")
print(f"  {'---':>3} {'---':>3} {'---':>3} {'---':>3} │ {'--------':>8} {'--------':>8} {'--------':>8} {'--------':>8} {'--------':>8} │ {'-------':>7} {'-------':>7} {'-------':>7} │ {'-----':>5}")

df_so = df.sort_values('f_so', ascending=False)
for i, (_, r) in enumerate(df_so.iterrows()):
    marker = " ← SEALED" if r['cr']==1 and r['vol']==2 and r['inf']==1 else ""
    print(f"  {i+1:>3} {int(r.cr):>3}x {int(r.vol):>3}x {int(r.inf):>3}x │ {r.f_so:>8.3f} {r.f_sh:>8.3f} {r.f_ca:>8.3f} {r.f_cagr*100:>+7.1f}% {r.f_mdd*100:>7.1f}% │ {r.is_so:>7.3f} {r.oos_so:>7.3f} {r.fwd_so:>7.3f} │ {r.tr_yr:>5.1f}{marker}")

# ── Summary: Best by each metric ──
print(f"\n{'='*140}")
print(f"  BEST BY EACH METRIC vs SEALED")
print(f"{'='*140}")

sealed = df[(df.cr==1)&(df.vol==2)&(df.inf==1)].iloc[0]

for metric, label in [('f_sh','Sharpe'), ('f_so','Sortino'), ('f_ca','Calmar')]:
    b = df.loc[df[metric].idxmax()]
    print(f"\n  ★ Best Full {label}: Cr={int(b.cr)}x V={int(b.vol)}x I={int(b.inf)}x")
    print(f"    {'':>15} {'Best':>12} {'Sealed':>12} {'Delta':>10}")
    print(f"    {'Sharpe':>15} {b.f_sh:>12.3f} {sealed.f_sh:>12.3f} {b.f_sh-sealed.f_sh:>+10.3f}")
    print(f"    {'Sortino':>15} {b.f_so:>12.3f} {sealed.f_so:>12.3f} {b.f_so-sealed.f_so:>+10.3f}")
    print(f"    {'Calmar':>15} {b.f_ca:>12.3f} {sealed.f_ca:>12.3f} {b.f_ca-sealed.f_ca:>+10.3f}")
    print(f"    {'CAGR':>15} {b.f_cagr*100:>+11.1f}% {sealed.f_cagr*100:>+11.1f}% {(b.f_cagr-sealed.f_cagr)*100:>+9.1f}pp")
    print(f"    {'MDD':>15} {b.f_mdd*100:>11.1f}% {sealed.f_mdd*100:>11.1f}% {(b.f_mdd-sealed.f_mdd)*100:>+9.1f}pp")
    print(f"    {'OOS {label}':>15} {b[f'oos_{metric[2:]}']:>12.3f} {sealed[f'oos_{metric[2:]}']:>12.3f} {b[f'oos_{metric[2:]}']-sealed[f'oos_{metric[2:]}']:>+10.3f}")

# ── Vol uselessness check ──
print(f"\n{'='*140}")
print(f"  VOL LAYER IMPACT: Cr=0x, Inf=0x, varying Vol only")
print(f"{'='*140}")
print(f"  {'Vol':>4} {'Sortino':>8} {'Sharpe':>8} {'Calmar':>8} {'CAGR':>8} {'MDD':>8} {'OOS So':>8}")
print(f"  {'----':>4} {'--------':>8} {'--------':>8} {'--------':>8} {'--------':>8} {'--------':>8} {'--------':>8}")
for vl in [0,1,2,3]:
    r = df[(df.cr==0)&(df.vol==vl)&(df.inf==0)].iloc[0]
    print(f"  {int(r.vol):>3}x {r.f_so:>8.3f} {r.f_sh:>8.3f} {r.f_ca:>8.3f} {r.f_cagr*100:>+7.1f}% {r.f_mdd*100:>7.1f}% {r.oos_so:>8.3f}")

# ── Credit 0x vs 1x comparison ──
print(f"\n{'='*140}")
print(f"  CREDIT 0x vs 1x (fixing Vol=2x, Inf=1x)")
print(f"{'='*140}")
for cl in [0,1]:
    r = df[(df.cr==cl)&(df.vol==2)&(df.inf==1)].iloc[0]
    print(f"  Cr={int(r.cr)}x: Sortino={r.f_so:.3f} Sharpe={r.f_sh:.3f} Calmar={r.f_ca:.3f} CAGR={r.f_cagr*100:+.1f}% MDD={r.f_mdd*100:.1f}% OOS_So={r.oos_so:.3f}")

# ── Inflation 0x vs 1x comparison ──
print(f"\n{'='*140}")
print(f"  INFLATION 0x vs 1x (fixing Cr=1x, Vol=2x)")
print(f"{'='*140}")
for il in [0,1]:
    r = df[(df.cr==1)&(df.vol==2)&(df.inf==il)].iloc[0]
    print(f"  Inf={int(r.inf)}x: Sortino={r.f_so:.3f} Sharpe={r.f_sh:.3f} Calmar={r.f_ca:.3f} CAGR={r.f_cagr*100:+.1f}% MDD={r.f_mdd*100:.1f}% OOS_So={r.oos_so:.3f}")
