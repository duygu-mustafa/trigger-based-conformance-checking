
# ============================================================================
# Multivariable Logistic Regression Analysis for ICU Weaning Rule Violations
# ============================================================================
# This script analyzes the independent association of four Declare constraints
# with SBT outcome using binary logistic regression.
#
# Author: [Your Name]
# Date: 2026-05-11
# ============================================================================

# Require packages to be installed before sourcing this script.
required_packages <- c('readr', 'dplyr', 'corrplot', 'car', 'pROC', 'ResourceSelection')
missing_packages <- setdiff(required_packages, rownames(installed.packages()))
if (length(missing_packages) > 0) {
  stop(
    sprintf(
      'Missing required packages: %s. Install them first with install.packages().',
      paste(missing_packages, collapse = ', ')
    ),
    call. = FALSE
  )
}

# Load required libraries
library(readr)
library(dplyr)
library(corrplot)
library(car)          # For VIF
library(pROC)         # For ROC curve and AUC
library(ResourceSelection)  # For Hosmer-Lemeshow test

# ============================================================================
# 1. LOAD AND PREPARE DATA
# ============================================================================

# Load case-level table
cases <- read_csv("data/results/statistical_analysis_table.csv")

# Rename columns to remove hyphens (R-friendly names)
cases <- cases %>%
  rename_with(~ gsub("-", "_", .), everything())

# Check data structure
cat("\n=== DATA SUMMARY ===\n")
cat("Total cases:", nrow(cases), "\n")
cat("Outcome distribution:\n")
print(table(cases$outcome, useNA = "ifany"))

# ============================================================================
# 2. SUBSET TO CANDIDATE PREDICTORS
# ============================================================================

# Select outcome and four candidate rules
model_data <- cases %>%
  select(outcome, INT_DX_04, RC_DP_05, RC_TM_02, RC_TM_03) %>%
  filter(!is.na(outcome))  # Drop rows with missing outcome

# Count complete cases for each predictor
cat("\n=== PREDICTOR AVAILABILITY ===\n")
for (var in c("INT_DX_04", "RC_DP_05", "RC_TM_02", "RC_TM_03")) {
  n_avail <- sum(!is.na(model_data[[var]]))
  cat(sprintf("%s: %d cases (%.1f%%)\n", var, n_avail, 100 * n_avail / nrow(model_data)))
}

# Remove rows with NA in any predictor (complete case analysis)
model_data_complete <- model_data %>%
  filter(complete.cases(.))

cat("\nComplete cases for analysis:", nrow(model_data_complete), "\n")

# ============================================================================
# 3. PAIRWISE CORRELATIONS
# ============================================================================

cat("\n=== PAIRWISE CORRELATIONS ===\n")

# Compute correlation matrix for the four predictors
cor_matrix <- cor(model_data_complete[, c("INT_DX_04", "RC_DP_05", "RC_TM_02", "RC_TM_03")], 
                  use = "complete.obs")

print(round(cor_matrix, 3))

# Visual correlation matrix
png("data/multivar_log_regr/correlation_matrix.png", width = 800, height = 800, res = 120)
corrplot(cor_matrix, method = "number", type = "upper", 
         tl.col = "black", tl.srt = 45,
         title = "Pairwise Correlations Among Rule Violations",
         mar = c(0, 0, 2, 0))
dev.off()

cat("\n✓ Correlation plot saved to data/multivar_log_regr/correlation_matrix.png\n")

# Check for high collinearity (|r| > 0.7)
high_cor <- which(abs(cor_matrix) > 0.7 & abs(cor_matrix) < 1, arr.ind = TRUE)
if (nrow(high_cor) > 0) {
  cat("\n⚠ WARNING: High correlations detected (|r| > 0.7):\n")
  for (i in 1:nrow(high_cor)) {
    cat(sprintf("  %s <-> %s: r = %.3f\n", 
                rownames(cor_matrix)[high_cor[i, 1]], 
                colnames(cor_matrix)[high_cor[i, 2]],
                cor_matrix[high_cor[i, 1], high_cor[i, 2]]))
  }
} else {
  cat("\n✓ No high collinearity detected (all |r| < 0.7)\n")
}

# ============================================================================
# 4. FIT MULTIVARIABLE LOGISTIC REGRESSION MODEL
# ============================================================================

cat("\n=== MULTIVARIABLE LOGISTIC REGRESSION ===\n")

# Fit the model
model <- glm(outcome ~ INT_DX_04 + RC_DP_05 + RC_TM_02 + RC_TM_03,
             data = model_data_complete,
             family = binomial(link = "logit"))

# Model summary
cat("\nModel coefficients:\n")
print(summary(model))

# ============================================================================
# 5. EXTRACT ADJUSTED ODDS RATIOS AND 95% CI
# ============================================================================

cat("\n=== ADJUSTED ODDS RATIOS ===\n")

# Get coefficients and confidence intervals
coef_ci <- cbind(
  OR = exp(coef(model)),
  exp(confint(model))
)

# Add p-values
coef_summary <- summary(model)$coefficients
results_table <- data.frame(
  Predictor = rownames(coef_ci),
  OR = coef_ci[, "OR"],
  CI_lower = coef_ci[, 2],
  CI_upper = coef_ci[, 3],
  p_value = coef_summary[, "Pr(>|z|)"]
)

print(results_table)

# Save to CSV
write_csv(results_table, "data/multivar_log_regr/logistic_regression_results.csv")
cat("\n✓ Results saved to data/multivar_log_regr/logistic_regression_results.csv\n")

# ============================================================================
# 6. CHECK FOR MULTICOLLINEARITY (VIF)
# ============================================================================

cat("\n=== VARIANCE INFLATION FACTORS (VIF) ===\n")

vif_values <- vif(model)
print(vif_values)

if (any(vif_values > 5)) {
  cat("\n⚠ WARNING: VIF > 5 detected for some predictors (high multicollinearity)\n")
} else if (any(vif_values > 3)) {
  cat("\n⚠ CAUTION: VIF > 3 detected for some predictors (moderate multicollinearity)\n")
} else {
  cat("\n✓ All VIF < 3 (acceptable multicollinearity)\n")
}

# ============================================================================
# 7. MODEL FIT DIAGNOSTICS
# ============================================================================

cat("\n=== MODEL FIT DIAGNOSTICS ===\n")

# Hosmer-Lemeshow goodness-of-fit test
hl_test <- hoslem.test(model_data_complete$outcome, fitted(model))
cat("\nHosmer-Lemeshow test:\n")
cat(sprintf("  Chi-square = %.3f, df = %d, p = %.4f\n", 
            hl_test$statistic, hl_test$parameter, hl_test$p.value))

if (hl_test$p.value > 0.05) {
  cat("  ✓ Good model fit (p > 0.05)\n")
} else {
  cat("  ⚠ Poor model fit (p < 0.05)\n")
}

# AUC (discrimination)
roc_obj <- roc(model_data_complete$outcome, fitted(model), quiet = TRUE)
auc_value <- auc(roc_obj)

cat(sprintf("\nArea Under ROC Curve (AUC): %.3f\n", auc_value))

if (auc_value > 0.8) {
  cat("  ✓ Excellent discrimination\n")
} else if (auc_value > 0.7) {
  cat("  ✓ Acceptable discrimination\n")
} else {
  cat("  ⚠ Poor discrimination\n")
}

# Plot ROC curve
png("data/multivar_log_regr/roc_curve.png", width = 800, height = 800, res = 120)
plot(roc_obj, main = paste0("ROC Curve (AUC = ", round(auc_value, 3), ")"),
     col = "#1f77b4", lwd = 2)
abline(a = 0, b = 1, lty = 2, col = "gray")
dev.off()

cat("\n✓ ROC curve saved to data/multivar_log_regr/roc_curve.png\n")

# ============================================================================
# 8. COMPARISON WITH UNIVARIATE ODDS RATIOS
# ============================================================================

cat("\n=== ADJUSTED vs UNADJUSTED ODDS RATIOS ===\n")

# Load univariate results if available
if (file.exists("data/results/rule_statistics_R.csv")) {
  univariate <- read_csv("data/results/rule_statistics_R.csv", show_col_types = FALSE) %>%

    filter(rule_name %in% c("INT-DX-04", "RC-DP-05", "RC-TM-02", "RC-TM-03")) %>%
    select(rule_name, or_unadjusted = or, or_low_unadj = or_low, or_high_unadj = or_high)
  
  # Match with adjusted results (skip intercept)
  comparison <- results_table %>%
    filter(Predictor != "(Intercept)") %>%
    mutate(rule_name = gsub("_", "-", Predictor)) %>%
    left_join(univariate, by = "rule_name") %>%
    select(rule_name, 
           OR_adjusted = OR, CI_adj_lower = CI_lower, CI_adj_upper = CI_upper,
           OR_unadjusted = or_unadjusted, CI_unadj_lower = or_low_unadj, CI_unadj_upper = or_high_unadj,
           p_adjusted = p_value)
  
  print(comparison)
  
  write_csv(comparison, "data/multivar_log_regr/adjusted_vs_unadjusted_comparison.csv")
  cat("\n✓ Comparison saved to data/multivar_log_regr/adjusted_vs_unadjusted_comparison.csv\n")
} else {
  cat("\n⚠ Univariate results not found (rule_statistics_R.csv). Skipping comparison.\n")
}

# ============================================================================
# 9. INTERPRETATION SUMMARY
# ============================================================================

cat("\n=== INTERPRETATION SUMMARY ===\n")
cat("\nFor each unit increase in a predictor (0 -> 1, i.e. no violation -> violation):\n")

for (i in 2:nrow(results_table)) {  # Skip intercept
  pred <- results_table$Predictor[i]
  or <- results_table$OR[i]
  ci_low <- results_table$CI_lower[i]
  ci_high <- results_table$CI_upper[i]
  p <- results_table$p_value[i]
  
  if (or < 1) {
    pct_change <- (1 - or) * 100
    direction <- "LOWER"
  } else {
    pct_change <- (or - 1) * 100
    direction <- "HIGHER"
  }
  
  sig <- ifelse(p < 0.001, "***", ifelse(p < 0.01, "**", ifelse(p < 0.05, "*", "n.s.")))
  
  cat(sprintf("\n%s:\n", pred))
  cat(sprintf("  Adjusted OR = %.3f (95%% CI: %.3f - %.3f), p = %.4f %s\n", 
              or, ci_low, ci_high, p, sig))
  cat(sprintf("  → %.1f%% %s odds of success when this rule is violated,\n", 
              pct_change, direction))
  cat(sprintf("     holding all other rules constant.\n"))
}

cat("\n*** p < 0.001, ** p < 0.01, * p < 0.05, n.s. = not significant\n")

cat("\n=== ANALYSIS COMPLETE ===\n")
cat("\nOutput files created:
")
cat("  1. data/multivar_log_regr/correlation_matrix.png\n")
cat("  2. data/multivar_log_regr/logistic_regression_results.csv\n")
cat("  3. data/multivar_log_regr/roc_curve.png\n")
cat("  4. data/multivar_log_regr/adjusted_vs_unadjusted_comparison.csv (if univariate results available)\n")
