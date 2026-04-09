"""Threshold tuning and precision-recall analysis for constraint model."""

import pandas as pd
from sklearn.metrics import precision_recall_curve, roc_curve, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.linear_model import LogisticRegression
from run_logistic_regression import _build_stay_level_constraint_matrix

# Load and prepare data
tracking = pd.read_csv('weighted_scoring_trace_tracking.csv')
stay_matrix, feature_cols = _build_stay_level_constraint_matrix(tracking)
rows = stay_matrix[['case_id','y', *feature_cols]].dropna().copy()
X = rows[feature_cols]
y = rows['y'].astype(int)

print("=" * 80)
print("THRESHOLD TUNING ANALYSIS (class_weight='balanced')")
print("=" * 80)
print(f"Dataset: n={len(rows)}, positives={int(y.sum())}, negatives={int((1-y).sum())}\n")

# Get cross-validated probabilities
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
model = LogisticRegression(max_iter=5000, class_weight='balanced')
y_prob_cv = cross_val_predict(model, X, y, cv=cv, method="predict_proba")[:, 1]

# Compute precision-recall curve
precision_vals, recall_vals, thresholds_pr = precision_recall_curve(y, y_prob_cv)
# Compute ROC curve
fpr, tpr, thresholds_roc = roc_curve(y, y_prob_cv)

# Test a range of thresholds
test_thresholds = [0.01, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7]

print("THRESHOLD SWEEP RESULTS")
print("-" * 80)
print(f"{'Thresh':<8} {'Prec':<8} {'Rec':<8} {'F1':<8} {'Acc':<8} {'Bal.Acc':<8} {'TP':<6} {'FP':<6} {'FN':<6} {'TN':<6}")
print("-" * 80)

best_f1 = 0
best_f1_thresh = 0.5
best_f1_prec = 0
best_f1_rec = 0

best_bal = 0
best_bal_thresh = 0.5
best_bal_prec = 0
best_bal_rec = 0

for threshold in test_thresholds:
    y_pred = (y_prob_cv >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, y_pred).ravel()
    
    prec = precision_score(y, y_pred, zero_division=0)
    rec = recall_score(y, y_pred, zero_division=0)
    f1 = f1_score(y, y_pred, zero_division=0)
    acc = (tp + tn) / (tp + tn + fp + fn)
    bal_acc = (tp / (tp + fn) + tn / (tn + fp)) / 2 if (tp + fn) > 0 and (tn + fp) > 0 else 0
    
    print(f"{threshold:<8.2f} {prec:<8.3f} {rec:<8.3f} {f1:<8.3f} {acc:<8.3f} {bal_acc:<8.3f} {tp:<6} {fp:<6} {fn:<6} {tn:<6}")
    
    if f1 > best_f1:
        best_f1 = f1
        best_f1_thresh = threshold
        best_f1_prec = prec
        best_f1_rec = rec
    
    if bal_acc > best_bal:
        best_bal = bal_acc
        best_bal_thresh = threshold
        best_bal_prec = prec
        best_bal_rec = rec

print("-" * 80)
print(f"\nOPTIMAL THRESHOLDS:")
print(f"  • Max F1 ({best_f1:.4f}):          threshold={best_f1_thresh:.2f}, precision={best_f1_prec:.3f}, recall={best_f1_rec:.3f}")
print(f"  • Max Balanced Acc ({best_bal:.4f}): threshold={best_bal_thresh:.2f}, precision={best_bal_prec:.3f}, recall={best_bal_rec:.3f}")
print(f"\nNote: High precision means fewer false alarms. High recall means catching more positives.")
print(f"      Choose threshold based on your use case (e.g., 0.05-0.1 for high sensitivity).")
