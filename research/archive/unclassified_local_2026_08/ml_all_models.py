#!/usr/bin/env python3
"""
ALL ML Models Comparison — purged walk-forward with embargo.
Tests every major ML method on the same data + same validation.
"""
import os, sys, warnings, time as _time
import numpy as np, pandas as pd
from sklearn.ensemble import (RandomForestClassifier, GradientBoostingClassifier,
                               AdaBoostClassifier, ExtraTreesClassifier, 
                               BaggingClassifier, VotingClassifier, StackingClassifier)
from sklearn.linear_model import (LogisticRegressionCV, RidgeClassifier, SGDClassifier,
                                   LassoCV, RidgeCV, ElasticNetCV)
from sklearn.svm import SVC, LinearSVC
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis, QuadraticDiscriminantAnalysis
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, matthews_corrcoef,
                              precision_score, recall_score, roc_auc_score)
import xgboost as xgb

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

warnings.filterwarnings('ignore')

# ── Load data (reuse cached features from ml_validate.py) ──
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, 'tools'))

# Re-run the feature building from ml_validate
exec(open(os.path.join(PROJECT_DIR, 'tools', 'ml_validate.py')).read().split(
    '# ═══════════════════════════════════════\n# VALIDATION 1')[0])

print("\n" + "=" * 100)
print("  ALL ML MODELS COMPARISON — PURGED WALK-FORWARD + EMBARGO")
print("=" * 100)

MIN_TRAIN = 60
STEP = 12

def build_models():
    """Return dict of name → model instance."""
    models = {
        # ── Tree-based ──
        'RandomForest':      RandomForestClassifier(n_estimators=200, max_depth=5, min_samples_leaf=5, random_state=42, n_jobs=-1),
        'ExtraTrees':        ExtraTreesClassifier(n_estimators=200, max_depth=5, min_samples_leaf=5, random_state=42, n_jobs=-1),
        'GradientBoosting':  GradientBoostingClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8, random_state=42),
        'AdaBoost':          AdaBoostClassifier(n_estimators=100, learning_rate=0.1, random_state=42, algorithm='SAMME'),
        'DecisionTree':      DecisionTreeClassifier(max_depth=5, min_samples_leaf=5, random_state=42),
        'Bagging':           BaggingClassifier(n_estimators=100, random_state=42, n_jobs=-1),
        'XGBoost':           xgb.XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8,
                                                colsample_bytree=0.8, random_state=42, verbosity=0, eval_metric='logloss'),
        # ── Linear ──
        'LogisticRegression': LogisticRegressionCV(cv=5, random_state=42, max_iter=5000),
        'Ridge':              RidgeClassifier(alpha=1.0),
        'SGD':                SGDClassifier(loss='log_loss', penalty='elasticnet', l1_ratio=0.5, max_iter=2000, random_state=42),
        'LDA':                LinearDiscriminantAnalysis(),
        # ── SVM ──
        'SVM_RBF':            SVC(kernel='rbf', C=1.0, gamma='scale', random_state=42, probability=True),
        'SVM_Linear':         LinearSVC(C=1.0, max_iter=5000, random_state=42, dual=True),
        # ── Instance-based ──
        'KNN_5':              KNeighborsClassifier(n_neighbors=5),
        'KNN_10':             KNeighborsClassifier(n_neighbors=10),
        'KNN_20':             KNeighborsClassifier(n_neighbors=20),
        # ── Neural Net ──
        'MLP_small':          MLPClassifier(hidden_layer_sizes=(32,16), max_iter=1000, random_state=42, early_stopping=True),
        'MLP_large':          MLPClassifier(hidden_layer_sizes=(64,32,16), max_iter=1000, random_state=42, early_stopping=True),
        # ── Probabilistic ──
        'NaiveBayes':         GaussianNB(),
        'QDA':                QuadraticDiscriminantAnalysis(),
    }
    
    if HAS_LGB:
        models['LightGBM'] = lgb.LGBMClassifier(n_estimators=200, max_depth=4, learning_rate=0.05,
                                                  subsample=0.8, colsample_bytree=0.8, random_state=42, verbosity=-1)
    
    return models

def run_all_models(X_all, y_all, horizon, embargo):
    y_h = y_all[horizon].dropna()
    valid_h = X_all.index.intersection(y_h.index)
    X = X_all.loc[valid_h]
    y = y_h.loc[valid_h]
    y_bin = (y > 0).astype(int)
    
    # Build folds with embargo
    folds = []
    start = MIN_TRAIN
    while start + embargo + STEP <= len(X):
        train_idx = list(range(start))
        test_start = start + embargo
        test_end = min(test_start + STEP, len(X))
        test_idx = list(range(test_start, test_end))
        folds.append((train_idx, test_idx))
        start += STEP
    
    if not folds:
        return None
    
    baseline_up_pct = y_bin.iloc[[i for f in folds for i in f[1]]].mean()
    
    all_results = {}
    models = build_models()
    
    for model_name, model_template in models.items():
        t0 = _time.time()
        all_actual = []; all_pred = []
        
        for train_idx, test_idx in folds:
            X_tr, X_te = X.iloc[train_idx], X.iloc[test_idx]
            yb_tr, yb_te = y_bin.iloc[train_idx], y_bin.iloc[test_idx]
            
            scaler = StandardScaler()
            X_tr_s = scaler.fit_transform(X_tr)
            X_te_s = scaler.transform(X_te)
            
            # Clone model for each fold
            from sklearn.base import clone
            model = clone(model_template)
            
            try:
                model.fit(X_tr_s, yb_tr)
                preds = model.predict(X_te_s)
            except Exception as e:
                preds = np.ones(len(X_te), dtype=int)  # fallback: predict all up
            
            all_actual.extend(yb_te.values)
            all_pred.extend(preds)
        
        elapsed = _time.time() - t0
        actual = np.array(all_actual)
        pred = np.array(all_pred)
        
        n_pred_down = (pred == 0).sum()
        n_pred_up = (pred == 1).sum()
        
        all_results[model_name] = {
            'acc': accuracy_score(actual, pred),
            'bacc': balanced_accuracy_score(actual, pred),
            'mcc': matthews_corrcoef(actual, pred),
            'prec_down': precision_score(actual, pred, pos_label=0, zero_division=0),
            'rec_down': recall_score(actual, pred, pos_label=0, zero_division=0),
            'prec_up': precision_score(actual, pred, pos_label=1, zero_division=0),
            'rec_up': recall_score(actual, pred, pos_label=1, zero_division=0),
            'n_down': n_pred_down,
            'n_up': n_pred_up,
            'time': elapsed,
        }
    
    return all_results, baseline_up_pct, len(folds), len(all_actual)

# ── Run for both horizons ──
for horizon, embargo in [('fwd_3m', 3), ('fwd_6m', 6)]:
    print(f"\n{'━'*100}")
    print(f"  TARGET: {horizon}  |  EMBARGO: {embargo} months  |  PURGED WALK-FORWARD")
    print(f"{'━'*100}")
    
    ret = run_all_models(X_all, y_all, horizon, embargo)
    if ret is None:
        print("  Not enough data"); continue
    
    results, baseline, n_folds, n_samples = ret
    
    print(f"  Folds: {n_folds} | Samples: {n_samples} | Baseline (always-up): {baseline:.1%}")
    
    # Sort by MCC (most honest metric)
    sorted_models = sorted(results.items(), key=lambda x: x[1]['mcc'], reverse=True)
    
    print(f"\n  {'Rank':>4} {'Model':<22} {'Acc':>6} {'BalAcc':>7} {'MCC':>6} │ {'P↓':>5} {'R↓':>5} {'P↑':>5} {'R↑':>5} │ {'#↓':>4} {'#↑':>4} │ {'Time':>5}")
    print(f"  {'─'*4} {'─'*22} {'─'*6} {'─'*7} {'─'*6} │ {'─'*5} {'─'*5} {'─'*5} {'─'*5} │ {'─'*4} {'─'*4} │ {'─'*5}")
    
    for rank, (name, r) in enumerate(sorted_models, 1):
        # Highlight if MCC > 0.1 (actual edge)
        marker = '★' if r['mcc'] > 0.1 else ' '
        print(f"  {marker}{rank:>3} {name:<22} {r['acc']:.1%} {r['bacc']:>6.1%} {r['mcc']:>+5.2f} │ "
              f"{r['prec_down']:>4.0%} {r['rec_down']:>4.0%} {r['prec_up']:>4.0%} {r['rec_up']:>4.0%} │ "
              f"{r['n_down']:>4} {r['n_up']:>4} │ {r['time']:>4.1f}s")
    
    print(f"\n  {'':>4} {'BASELINE (always up)':<22} {baseline:.1%}   {'—':>7}   {'—':>6} │   {'—':>5} {'—':>5} {'—':>5} {'—':>5} │ {'0':>4} {n_samples:>4} │")
    
    # Summary
    best = sorted_models[0]
    worst = sorted_models[-1]
    avg_mcc = np.mean([r['mcc'] for _, r in sorted_models])
    pos_mcc = sum(1 for _, r in sorted_models if r['mcc'] > 0)
    
    print(f"\n  Summary:")
    print(f"    Best model:  {best[0]} (MCC={best[1]['mcc']:+.2f}, BalAcc={best[1]['bacc']:.1%})")
    print(f"    Worst model: {worst[0]} (MCC={worst[1]['mcc']:+.2f})")
    print(f"    Average MCC: {avg_mcc:+.3f}")
    print(f"    Models with positive MCC: {pos_mcc}/{len(sorted_models)}")
    print(f"    Models that beat baseline accuracy: {sum(1 for _, r in sorted_models if r['acc'] > baseline)}/{len(sorted_models)}")
    
    # How many models just predict "always up"?
    always_up = sum(1 for _, r in sorted_models if r['n_down'] == 0)
    print(f"    Models that NEVER predict down: {always_up}/{len(sorted_models)}")

print("\n" + "=" * 100)
print("  FINAL VERDICT")
print("=" * 100)
print("""
  Key question: Is there ANY ML method that can reliably predict QQQ direction
  at monthly frequency using macro/sentiment/technical features?

  The answer depends on the MCC scores above.
  
  MCC interpretation:
    +1.0  = perfect prediction
    +0.3  = moderate positive correlation (decent signal)
    +0.1  = weak but possibly real signal
     0.0  = random (no edge)
    -0.1  = slightly worse than random

  If the best model across all methods has MCC < 0.15, then:
  → Monthly ML timing has NO reliable edge for QQQ
  → Your daily Z-score strategy wins because it operates at a different timescale
  → The right use of macro data is REGIME OVERLAY, not DIRECTION PREDICTION
""")
