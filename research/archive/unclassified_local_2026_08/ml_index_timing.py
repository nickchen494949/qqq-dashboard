#!/usr/bin/env python3
"""
ML Index Timing: Find the best indicators for predicting QQQ returns.
Uses Random Forest, XGBoost, Lasso with walk-forward validation.
"""
import os, sys, warnings, time as _time
import numpy as np, pandas as pd
import yfinance as yf
from fredapi import Fred
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LassoCV, LogisticRegressionCV, RidgeCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, classification_report
import xgboost as xgb

warnings.filterwarnings('ignore')

# ── Setup ──
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, 'tools'))
from strategy_engine import get_fred_api_key, compute_credit_z, compute_vol_z, compute_inflation_z

FRED_API_KEY = get_fred_api_key()
fred = Fred(api_key=FRED_API_KEY)
DATA_DIR = os.path.join(PROJECT_DIR, 'market_data', 'ml_cache')
os.makedirs(DATA_DIR, exist_ok=True)

# ══════════════════════════════════════════════════
# 1. DATA COLLECTION
# ══════════════════════════════════════════════════
print("=" * 80)
print("  PHASE 1: COLLECTING DATA")
print("=" * 80)

def get_fred(sid, name=None):
    if name is None: name = sid
    path = os.path.join(DATA_DIR, f'fred_{sid}.csv')
    if os.path.exists(path):
        s = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
        age_days = (pd.Timestamp.now() - pd.Timestamp(os.path.getmtime(path), unit='s')).days
        if len(s) > 100 and age_days < 7:
            print(f"  ✓ {name} ({sid}) — cached ({len(s)} rows)")
            return s
    try:
        s = fred.get_series(sid, observation_start='2003-01-01').dropna()
        s.to_csv(path)
        print(f"  ✓ {name} ({sid}) — fetched ({len(s)} rows)")
        return s
    except Exception as e:
        print(f"  ✗ {name} ({sid}) — FAILED: {e}")
        return None

def get_yahoo(ticker):
    path = os.path.join(DATA_DIR, f'yahoo_{ticker}.csv')
    if os.path.exists(path):
        s = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
        age_days = (pd.Timestamp.now() - pd.Timestamp(os.path.getmtime(path), unit='s')).days
        if len(s) > 100 and age_days < 7:
            print(f"  ✓ {ticker} — cached ({len(s)} rows)")
            return s
    df = yf.download(ticker, start='2003-01-01', progress=False, auto_adjust=False)
    adj = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
    if isinstance(adj, pd.DataFrame): adj = adj.iloc[:, 0]
    adj.to_csv(path)
    print(f"  ✓ {ticker} — fetched ({len(adj)} rows)")
    return adj

# ── FRED Macro Data ──
print("\n[FRED Macro Indicators]")
fred_series = {
    'DFF': 'Fed Funds Rate',
    'DGS10': '10Y Treasury',
    'DGS2': '2Y Treasury',
    'T10Y2Y': '10Y-2Y Spread',
    'T10Y3M': '10Y-3M Spread',
    'T10YIE': '10Y Breakeven Inflation',
    'BAMLH0A0HYM2': 'HY OAS Spread',
    'BAMLC0A0CM': 'IG OAS Spread',
    'VIXCLS': 'VIX',
    'M2SL': 'M2 Money Supply',
    'UMCSENT': 'Consumer Sentiment',
    'UNRATE': 'Unemployment Rate',
    'IC4WSA': 'Initial Claims 4wk',
    'CPIAUCSL': 'CPI',
    'PCEPILFE': 'Core PCE',
    'NFCI': 'Financial Conditions',
    'INDPRO': 'Industrial Production',
    # NAPM removed — series no longer exists on FRED
}
fred_data = {}
for sid, name in fred_series.items():
    s = get_fred(sid, name)
    if s is not None:
        fred_data[sid] = s

# ── Yahoo Price Data ──
print("\n[Yahoo Price Data]")
tickers = ['QQQ', 'SPY', 'HYG', 'IEF', 'TIP', 'TLT', 'GLD', 'UUP']
yahoo_data = {}
for t in tickers:
    yahoo_data[t] = get_yahoo(t)

# ══════════════════════════════════════════════════
# 2. FEATURE ENGINEERING (Monthly Frequency)
# ══════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  PHASE 2: FEATURE ENGINEERING")
print("=" * 80)

# Resample everything to month-end
qqq = yahoo_data['QQQ'].resample('ME').last().dropna()

features = pd.DataFrame(index=qqq.index)

# ── Macro/Rates Features ──
def add_fred_feature(name, sid, transform='level'):
    if sid not in fred_data: return
    s = fred_data[sid].resample('ME').last().ffill().reindex(qqq.index, method='ffill')
    if transform == 'level':
        features[name] = s
    elif transform == 'change_3m':
        features[name] = s - s.shift(3)
    elif transform == 'change_12m':
        features[name] = s - s.shift(12)
    elif transform == 'yoy':
        features[name] = s.pct_change(12) * 100

# Rates
add_fred_feature('fed_rate', 'DFF')
add_fred_feature('fed_rate_chg12m', 'DFF', 'change_12m')
add_fred_feature('yield_10y', 'DGS10')
add_fred_feature('yield_10y_chg3m', 'DGS10', 'change_3m')
add_fred_feature('yield_2y', 'DGS2')
add_fred_feature('spread_10y2y', 'T10Y2Y')
add_fred_feature('spread_10y2y_chg3m', 'T10Y2Y', 'change_3m')
add_fred_feature('spread_10y3m', 'T10Y3M')
add_fred_feature('breakeven_inf', 'T10YIE')

# Credit
add_fred_feature('hy_oas', 'BAMLH0A0HYM2')
add_fred_feature('hy_oas_chg3m', 'BAMLH0A0HYM2', 'change_3m')
add_fred_feature('ig_oas', 'BAMLC0A0CM')

# Volatility
add_fred_feature('vix', 'VIXCLS')

# Liquidity
add_fred_feature('m2_yoy', 'M2SL', 'yoy')

# Sentiment
add_fred_feature('consumer_sent', 'UMCSENT')
add_fred_feature('ism_pmi', 'NAPM')

# Employment
add_fred_feature('unemployment', 'UNRATE')
add_fred_feature('claims_4wk', 'IC4WSA')

# Inflation
add_fred_feature('cpi_yoy', 'CPIAUCSL', 'yoy')
add_fred_feature('core_pce_yoy', 'PCEPILFE', 'yoy')

# Financial conditions
add_fred_feature('nfci', 'NFCI')

# Industrial production
add_fred_feature('indpro_yoy', 'INDPRO', 'yoy')

# ── Price/Technical Features ──
features['qqq_ret_1m'] = qqq.pct_change(1) * 100
features['qqq_ret_3m'] = qqq.pct_change(3) * 100
features['qqq_ret_6m'] = qqq.pct_change(6) * 100
features['qqq_ret_12m'] = qqq.pct_change(12) * 100

# SMA signals
qqq_daily = yahoo_data['QQQ']
sma200 = qqq_daily.rolling(200).mean()
sma50 = qqq_daily.rolling(50).mean()
features['qqq_vs_sma200'] = ((qqq_daily / sma200 - 1) * 100).resample('ME').last().reindex(qqq.index)
features['qqq_vs_sma50'] = ((qqq_daily / sma50 - 1) * 100).resample('ME').last().reindex(qqq.index)

# Realized vol
daily_ret = qqq_daily.pct_change()
features['realized_vol_20d'] = (daily_ret.rolling(20).std() * np.sqrt(252) * 100).resample('ME').last().reindex(qqq.index)

# ── Our Strategy Z-Scores ──
full_idx = qqq_daily.dropna().index
hyg_full = yahoo_data['HYG'].reindex(full_idx).ffill()
ief_full = yahoo_data['IEF'].reindex(full_idx).ffill()
tip_full = yahoo_data['TIP'].reindex(full_idx).ffill()
tlt_full = yahoo_data['TLT'].reindex(full_idx).ffill()

credit_z = compute_credit_z(hyg_full, ief_full)
vol_z = compute_vol_z(daily_ret.reindex(full_idx))
inf_z = compute_inflation_z(tip_full, tlt_full)

features['credit_z'] = credit_z.resample('ME').last().reindex(qqq.index)
features['vol_z'] = vol_z.resample('ME').last().reindex(qqq.index)
features['inf_z'] = inf_z.resample('ME').last().reindex(qqq.index)

# ── Cross-asset ──
spy = yahoo_data['SPY'].resample('ME').last().reindex(qqq.index)
features['qqq_vs_spy_3m'] = (qqq.pct_change(3) - spy.pct_change(3)) * 100

gld = yahoo_data['GLD'].resample('ME').last().reindex(qqq.index)
features['gold_ret_3m'] = gld.pct_change(3) * 100

if 'UUP' in yahoo_data:
    uup = yahoo_data['UUP'].resample('ME').last().reindex(qqq.index)
    features['dollar_ret_3m'] = uup.pct_change(3) * 100

# ── VIX percentile ──
if 'VIXCLS' in fred_data:
    vix_m = fred_data['VIXCLS'].resample('ME').last().ffill().reindex(qqq.index, method='ffill')
    features['vix_pctl_12m'] = vix_m.rolling(12).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)

# ── Target Variables ──
targets = pd.DataFrame(index=qqq.index)
targets['fwd_1m'] = qqq.pct_change(1).shift(-1) * 100
targets['fwd_3m'] = qqq.pct_change(3).shift(-3) * 100
targets['fwd_6m'] = qqq.pct_change(6).shift(-6) * 100
targets['fwd_12m'] = qqq.pct_change(12).shift(-12) * 100

# Binary targets (up/down)
targets['fwd_3m_up'] = (targets['fwd_3m'] > 0).astype(int)
targets['fwd_6m_up'] = (targets['fwd_6m'] > 0).astype(int)

# Fill NaN: forward fill then drop rows with >30% missing
features = features.ffill().bfill()
# Drop features that are >50% NaN
good_cols = features.columns[features.isnull().mean() < 0.5]
features = features[good_cols]
# Drop rows that still have any NaN
features = features.dropna()
# Require at least fwd_3m target
valid = features.index.intersection(targets.dropna(subset=['fwd_3m']).index)
# Also require start from 2007 (need 12m lookback for change features)
valid = valid[valid >= '2007-01-01']
X_all = features.loc[valid].copy()
y_all = targets.loc[valid].copy()

print(f"\n  Features: {X_all.shape[1]}")
print(f"  Samples:  {len(X_all)} months ({X_all.index[0].strftime('%Y-%m')} to {X_all.index[-1].strftime('%Y-%m')})")
print(f"  Feature list:")
for i, c in enumerate(X_all.columns):
    print(f"    {i+1:>2}. {c}")

# ══════════════════════════════════════════════════
# 3. WALK-FORWARD ML MODELS
# ══════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  PHASE 3: WALK-FORWARD ML TRAINING")
print("=" * 80)

# Walk-forward: train on expanding window, test on next 12 months
# Minimum train = 60 months (5 years)
MIN_TRAIN = 60
STEP = 12  # step forward 12 months

horizons = ['fwd_3m', 'fwd_6m']
results = {}

for horizon in horizons:
    print(f"\n{'─'*60}")
    print(f"  Target: {horizon}")
    print(f"{'─'*60}")
    
    y_h = y_all[horizon].dropna()
    valid_h = X_all.index.intersection(y_h.index)
    X = X_all.loc[valid_h]
    y = y_h.loc[valid_h]
    y_bin = (y > 0).astype(int)
    
    # Walk-forward folds
    folds = []
    start = MIN_TRAIN
    while start + STEP <= len(X):
        train_idx = list(range(start))
        test_idx = list(range(start, min(start + STEP, len(X))))
        folds.append((train_idx, test_idx))
        start += STEP
    
    print(f"  Folds: {len(folds)}")
    
    # Storage for results
    all_importance_rf = []
    all_importance_xgb_arr = []
    all_preds = {'rf': [], 'xgb': [], 'lasso': [], 'actual': [], 'dates': []}
    all_preds_bin = {'rf': [], 'xgb': [], 'logistic': [], 'actual': []}
    
    for fold_i, (train_idx, test_idx) in enumerate(folds):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
        yb_train, yb_test = y_bin.iloc[train_idx], y_bin.iloc[test_idx]
        
        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_train)
        X_te_s = scaler.transform(X_test)
        
        # Random Forest Regressor
        rf = RandomForestRegressor(n_estimators=200, max_depth=5, min_samples_leaf=5, random_state=42, n_jobs=-1)
        rf.fit(X_tr_s, y_train)
        rf_pred = rf.predict(X_te_s)
        all_preds['rf'].extend(rf_pred)
        all_importance_rf.append(rf.feature_importances_)
        
        # XGBoost Regressor
        xgb_model = xgb.XGBRegressor(n_estimators=200, max_depth=4, learning_rate=0.05, 
                                      subsample=0.8, colsample_bytree=0.8, random_state=42, verbosity=0)
        xgb_model.fit(X_tr_s, y_train)
        xgb_pred = xgb_model.predict(X_te_s)
        all_preds['xgb'].extend(xgb_pred)
        all_importance_xgb_arr.append(xgb_model.feature_importances_)
        
        # Lasso Regression
        lasso = LassoCV(cv=5, random_state=42, max_iter=5000)
        lasso.fit(X_tr_s, y_train)
        lasso_pred = lasso.predict(X_te_s)
        all_preds['lasso'].extend(lasso_pred)
        
        all_preds['actual'].extend(y_test.values)
        all_preds['dates'].extend(X_test.index)
        
        # Classification
        rfc = RandomForestClassifier(n_estimators=200, max_depth=5, min_samples_leaf=5, random_state=42, n_jobs=-1)
        rfc.fit(X_tr_s, yb_train)
        all_preds_bin['rf'].extend(rfc.predict(X_te_s))
        
        xgbc = xgb.XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05,
                                  subsample=0.8, colsample_bytree=0.8, random_state=42, verbosity=0, eval_metric='logloss')
        xgbc.fit(X_tr_s, yb_train)
        all_preds_bin['xgb'].extend(xgbc.predict(X_te_s))
        
        lr = LogisticRegressionCV(cv=5, random_state=42, max_iter=5000)
        lr.fit(X_tr_s, yb_train)
        all_preds_bin['logistic'].extend(lr.predict(X_te_s))
        
        all_preds_bin['actual'].extend(yb_test.values)
        
        period = f"{X_test.index[0].strftime('%Y-%m')}→{X_test.index[-1].strftime('%Y-%m')}"
        print(f"    Fold {fold_i+1}: train={len(train_idx)}m test={len(test_idx)}m ({period})")
    
    if len(folds) == 0:
        print(f"  ⚠️  Not enough data for walk-forward (need {MIN_TRAIN}+ months, have {len(X)})")
        results[horizon] = None
        continue
    
    # ── Feature Importance ──
    imp_rf = np.mean(all_importance_rf, axis=0)
    imp_xgb_mean = np.mean(all_importance_xgb_arr, axis=0)
    
    # Combined importance (average RF + XGB, normalized)
    imp_rf_norm = imp_rf / imp_rf.sum()
    imp_xgb_norm = imp_xgb_mean / imp_xgb_mean.sum()
    imp_combined = (imp_rf_norm + imp_xgb_norm) / 2
    
    feat_imp = pd.DataFrame({
        'Feature': X.columns,
        'RF': imp_rf_norm,
        'XGB': imp_xgb_norm,
        'Combined': imp_combined,
    }).sort_values('Combined', ascending=False)
    
    # Lasso coefficients (from last fold)
    lasso_coefs = pd.Series(np.abs(lasso.coef_), index=X.columns).sort_values(ascending=False)
    lasso_selected = lasso_coefs[lasso_coefs > 0]
    
    # ── Prediction Accuracy ──
    actual_bin = np.array(all_preds_bin['actual'])
    
    acc = {}
    for model_name in ['rf', 'xgb', 'logistic']:
        preds = np.array(all_preds_bin[model_name])
        acc[model_name] = accuracy_score(actual_bin, preds)
    
    # Direction accuracy for regression models
    actual_cont = np.array(all_preds['actual'])
    dir_acc = {}
    for model_name in ['rf', 'xgb', 'lasso']:
        preds = np.array(all_preds[model_name])
        dir_acc[model_name] = np.mean((preds > 0) == (actual_cont > 0))
    
    # Correlation
    corr = {}
    for model_name in ['rf', 'xgb', 'lasso']:
        preds = np.array(all_preds[model_name])
        corr[model_name] = np.corrcoef(preds, actual_cont)[0, 1]
    
    results[horizon] = {
        'feat_imp': feat_imp,
        'lasso_selected': lasso_selected,
        'acc': acc,
        'dir_acc': dir_acc,
        'corr': corr,
        'preds': all_preds,
    }
    
    # ── Print Results ──
    print(f"\n  Classification Accuracy (is forward return positive?):")
    for m, a in acc.items():
        print(f"    {m:>10}: {a:.1%}")
    
    print(f"\n  Regression Direction Accuracy:")
    for m, a in dir_acc.items():
        print(f"    {m:>10}: {a:.1%}")
    
    print(f"\n  Regression Correlation (pred vs actual):")
    for m, c in corr.items():
        print(f"    {m:>10}: {c:.3f}")
    
    print(f"\n  Top 15 Features (RF + XGB combined importance):")
    for i, (_, row) in enumerate(feat_imp.head(15).iterrows()):
        bar = '█' * int(row['Combined'] * 100)
        print(f"    {i+1:>2}. {row['Feature']:<25} {row['Combined']:.3f}  {bar}")
    
    print(f"\n  Lasso Selected Features ({len(lasso_selected)}/{len(X.columns)}):")
    for feat_name, c in lasso_selected.head(10).items():
        print(f"    • {feat_name:<25} coef={c:.4f}")

# ══════════════════════════════════════════════════
# 4. SINGLE FEATURE ANALYSIS
# ══════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  PHASE 4: SINGLE FEATURE PREDICTIVE POWER")
print("=" * 80)

for horizon in horizons:
    if results.get(horizon) is None: continue
    print(f"\n{'─'*60}")
    print(f"  Single Feature → {horizon}")
    print(f"{'─'*60}")
    
    y_h = y_all[horizon].dropna()
    valid_h = X_all.index.intersection(y_h.index)
    X = X_all.loc[valid_h]
    y = y_h.loc[valid_h]
    
    single_corr = []
    for col in X.columns:
        c = X[col].corr(y)
        # Also compute rank correlation (Spearman)
        sc = X[col].rank().corr(y.rank())
        single_corr.append({'Feature': col, 'Pearson': c, 'Spearman': sc, 'AbsPearson': abs(c)})
    
    sc_df = pd.DataFrame(single_corr).sort_values('AbsPearson', ascending=False)
    
    print(f"\n  {'Feature':<25} {'Pearson':>8} {'Spearman':>8} {'Direction':>10}")
    print(f"  {'─'*25} {'─'*8} {'─'*8} {'─'*10}")
    for _, row in sc_df.head(20).iterrows():
        direction = "↑ bullish" if row['Pearson'] > 0 else "↓ bearish"
        print(f"  {row['Feature']:<25} {row['Pearson']:>+8.3f} {row['Spearman']:>+8.3f} {direction:>10}")

# ══════════════════════════════════════════════════
# 5. STRATEGY BACKTEST: ML TIMING vs BUY-AND-HOLD
# ══════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  PHASE 5: ML TIMING STRATEGY BACKTEST")
print("=" * 80)

# Use 3M forward prediction to decide: IN (3x) or OUT (cash/1x)
horizon = 'fwd_3m'
if results.get(horizon) is None:
    print("  ⚠️  No results for fwd_3m — skipping backtest")
else:
    preds_data = results[horizon]['preds']
    dates = preds_data['dates']
    rf_preds = np.array(preds_data['rf'])
    xgb_preds = np.array(preds_data['xgb'])
    actual = np.array(preds_data['actual'])

    ensemble_pred = (rf_preds + xgb_preds) / 2

    qqq_monthly_ret = qqq.pct_change().reindex(pd.DatetimeIndex(dates)).values

    eq_bh = [1.0]; eq_ml = [1.0]; eq_always_1x = [1.0]
    lev_history = []

    for i in range(len(dates)):
        r = qqq_monthly_ret[i] if not np.isnan(qqq_monthly_ret[i]) else 0
        eq_bh.append(eq_bh[-1] * (1 + 3 * r))
        eq_always_1x.append(eq_always_1x[-1] * (1 + r))
        if ensemble_pred[i] > 2: ml_lev = 3
        elif ensemble_pred[i] > 0: ml_lev = 2
        else: ml_lev = 1
        lev_history.append(ml_lev)
        eq_ml.append(eq_ml[-1] * (1 + ml_lev * r))

    eq_bh = np.array(eq_bh[1:]); eq_ml = np.array(eq_ml[1:]); eq_1x = np.array(eq_always_1x[1:])

    def calc_metrics(eq):
        ny = len(eq) / 12
        cagr = (eq[-1] / eq[0]) ** (1/ny) - 1
        rm = np.maximum.accumulate(eq)
        mdd = (eq / rm - 1).min()
        rets = np.diff(eq) / eq[:-1]
        sh = np.mean(rets) / np.std(rets) * np.sqrt(12) if np.std(rets) > 0 else 0
        down = rets[rets < 0]
        down_std = np.sqrt(np.mean(down**2)) if len(down) > 0 else 1e-10
        sortino = np.mean(rets) / down_std * np.sqrt(12)
        return cagr, mdd, sh, sortino

    cagr_bh, mdd_bh, sh_bh, so_bh = calc_metrics(eq_bh)
    cagr_ml, mdd_ml, sh_ml, so_ml = calc_metrics(eq_ml)
    cagr_1x, mdd_1x, sh_1x, so_1x = calc_metrics(eq_1x)

    period = f"{dates[0].strftime('%Y-%m')} to {dates[-1].strftime('%Y-%m')}"
    print(f"\n  Backtest Period: {period}")
    print(f"  ML Signal: ensemble(RF+XGB) predicting 3M forward QQQ return")
    print(f"  Rule: pred > 2% → 3x | pred > 0% → 2x | pred < 0% → 1x")

    print(f"\n  {'Strategy':<25} {'CAGR':>8} {'MDD':>8} {'Sharpe':>8} {'Sortino':>8}")
    print(f"  {'─'*25} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")
    print(f"  {'Buy & Hold 3x QQQ':<25} {cagr_bh*100:>+7.1f}% {mdd_bh*100:>7.1f}% {sh_bh:>8.2f} {so_bh:>8.2f}")
    print(f"  {'ML Timing (1x-3x)':<25} {cagr_ml*100:>+7.1f}% {mdd_ml*100:>7.1f}% {sh_ml:>8.2f} {so_ml:>8.2f}")
    print(f"  {'Always 1x QQQ':<25} {cagr_1x*100:>+7.1f}% {mdd_1x*100:>7.1f}% {sh_1x:>8.2f} {so_1x:>8.2f}")

    lev_arr = np.array(lev_history)
    print(f"\n  ML Leverage Distribution:")
    print(f"    3x: {(lev_arr==3).sum()} months ({(lev_arr==3).mean()*100:.0f}%)")
    print(f"    2x: {(lev_arr==2).sum()} months ({(lev_arr==2).mean()*100:.0f}%)")
    print(f"    1x: {(lev_arr==1).sum()} months ({(lev_arr==1).mean()*100:.0f}%)")

# ══════════════════════════════════════════════════
# 6. FINAL SUMMARY
# ══════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  FINAL SUMMARY: BEST INDICATORS")
print("=" * 80)

print("\n  ┌─────────────────────────────────────────────────────────────┐")
print("  │  TOP INDICATORS BY ML IMPORTANCE (averaged across models)  │")
print("  └─────────────────────────────────────────────────────────────┘")

# Average importance across horizons
all_imp = []
for h in horizons:
    if results.get(h) is None: continue
    imp = results[h]['feat_imp'].set_index('Feature')['Combined']
    all_imp.append(imp)
if len(all_imp) == 0:
    print("  No results to summarize.")
    sys.exit(0)
avg_imp = pd.concat(all_imp, axis=1).mean(axis=1).sort_values(ascending=False)

# Categorize features
categories = {
    'Macro/Rates': ['fed_rate', 'fed_rate_chg12m', 'yield_10y', 'yield_10y_chg3m', 'yield_2y', 
                    'spread_10y2y', 'spread_10y2y_chg3m', 'spread_10y3m', 'breakeven_inf',
                    'nfci', 'indpro_yoy', 'm2_yoy', 'unemployment', 'claims_4wk'],
    'Credit/Spread': ['hy_oas', 'hy_oas_chg3m', 'ig_oas', 'credit_z'],
    'Valuation/Inflation': ['cpi_yoy', 'core_pce_yoy'],
    'Sentiment': ['vix', 'vix_pctl_12m', 'consumer_sent', 'ism_pmi'],
    'Technical/Momentum': ['qqq_ret_1m', 'qqq_ret_3m', 'qqq_ret_6m', 'qqq_ret_12m',
                           'qqq_vs_sma200', 'qqq_vs_sma50', 'realized_vol_20d', 'vol_z', 'inf_z'],
    'Cross-Asset': ['qqq_vs_spy_3m', 'gold_ret_3m', 'dollar_ret_3m'],
}

cat_weights = {}
for cat, feats in categories.items():
    w = avg_imp.reindex(feats).dropna().sum()
    cat_weights[cat] = w

total_w = sum(cat_weights.values())
print(f"\n  {'Category':<25} {'ML Weight':>10} {'Your Weight':>12}")
print(f"  {'─'*25} {'─'*10} {'─'*12}")

user_weights = {
    'Macro/Rates': 20,
    'Credit/Spread': 10,
    'Valuation/Inflation': 10,
    'Sentiment': 10,
    'Technical/Momentum': 35,
    'Cross-Asset': 15,
}

for cat in sorted(cat_weights, key=cat_weights.get, reverse=True):
    pct = cat_weights[cat] / total_w * 100
    uw = user_weights.get(cat, '?')
    print(f"  {cat:<25} {pct:>9.1f}% {uw:>10}%")

print(f"\n  Top 10 Individual Indicators:")
for i, (feat, imp) in enumerate(avg_imp.head(10).items()):
    bar = '█' * int(imp * 150)
    print(f"    {i+1:>2}. {feat:<25} {imp:.4f}  {bar}")

print(f"\n  Lasso-Selected Features (non-zero coefficients):")
for h in horizons:
    if results.get(h) is None: continue
    selected = results[h]['lasso_selected']
    print(f"    {h}: {', '.join(selected.head(8).index.tolist())}")

print("\n" + "=" * 80)
print("  DONE")
print("=" * 80)
