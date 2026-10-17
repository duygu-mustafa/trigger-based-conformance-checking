#!/usr/bin/env Rscript
# Outcome-association statistics per constraint, called by main.py.
#
#   Rscript statistics_R.r <trigger_results_csv> <analysis_table_csv> <rule_statistics_csv>
#
# Keeps episodes with an SBT attempt and an evaluable outcome (Success = 1,
# Failure = 0). Per constraint, an episode is exposed (violated, 1), unexposed
# (satisfied, 0) or excluded (vacuous). For each constraint a 2x2 table against
# the episode outcome (or the next episode's outcome for inter-episode rules)
# gives Fisher's exact p-value, the conditional-MLE odds ratio and its exact CI
# (fisher.test), and the risk ratio of Success with a log-scale 95% CI (0.5
# continuity correction if any cell is zero). Multiple-testing corrections are
# applied later, in derive/generate_summary.py. Base R only.

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 3) {
  stop('Usage: Rscript statistics_R.r <trigger_results_csv> <analysis_table_csv> <rule_statistics_csv>')
}

input_csv <- args[[1]]
analysis_table_csv <- args[[2]]
rule_statistics_csv <- args[[3]]

parse_constraint_list <- function(raw_value) {
  if (is.na(raw_value) || raw_value == '') {
    return(character(0))
  }
  tokens <- unlist(strsplit(as.character(raw_value), ';', fixed = TRUE))
  tokens <- trimws(tokens)
  tokens[tokens != '']
}

classify_outcome <- function(outcome) {
  outcome_str <- tolower(as.character(outcome))
  if (grepl('success', outcome_str, fixed = TRUE)) {
    return('success')
  }
  if (grepl('failure', outcome_str, fixed = TRUE)) {
    return('failure')
  }
  return('unknown')
}

safe_num <- function(value) {
  value_num <- suppressWarnings(as.numeric(value))
  if (length(value_num) == 0 || is.na(value_num) || is.nan(value_num) || is.infinite(value_num)) {
    return(NA_real_)
  }
  value_num
}

extract_all_rules <- function(df) {
  rule_columns <- c(
    'mandatory_violated_constraints',
    'mandatory_satisfied_constraints',
    'mandatory_vacuous_constraints',
    'info_violated_constraints',
    'info_satisfied_constraints',
    'info_vacuous_constraints'
  )
  present_columns <- intersect(rule_columns, names(df))
  if (length(present_columns) == 0) {
    return(character(0))
  }

  all_rules <- unlist(lapply(present_columns, function(column_name) {
    values <- df[[column_name]]
    values <- values[!is.na(values) & values != '']
    if (length(values) == 0) {
      return(character(0))
    }
    unlist(lapply(values, parse_constraint_list), use.names = FALSE)
  }), use.names = FALSE)

  unique(all_rules[all_rules != '' & !is.na(all_rules)])
}

build_case_level_table <- function(df) {
  sbt_df <- df[!is.na(df$sbt_attempt) & df$sbt_attempt != '', , drop = FALSE]
  if (nrow(sbt_df) == 0) {
    return(data.frame())
  }

  sbt_df$outcome <- vapply(sbt_df$sbt_outcome, function(x) {
    label <- classify_outcome(x)
    if (label == 'success') return(1)
    if (label == 'failure') return(0)
    return(NA_real_)
  }, numeric(1))

  # Inter-episode outcome: next episode's sbt_outcome (from pipeline column
  # next_sbt_outcome). NA = censored (no subsequent evaluable episode).
  if ('next_sbt_outcome' %in% names(sbt_df)) {
    sbt_df$next_outcome <- vapply(sbt_df$next_sbt_outcome, function(x) {
      label <- classify_outcome(x)
      if (label == 'success') return(1)
      if (label == 'failure') return(0)
      return(NA_real_)
    }, numeric(1))
  } else {
    sbt_df$next_outcome <- NA_real_
  }

  sbt_df <- sbt_df[!is.na(sbt_df$outcome), , drop = FALSE]
  if (nrow(sbt_df) == 0) {
    return(data.frame())
  }

  all_rules <- extract_all_rules(sbt_df)
  case_rows <- vector('list', nrow(sbt_df))

  for (i in seq_len(nrow(sbt_df))) {
    row <- sbt_df[i, ]
    case_row <- list(
      stay_id = row$stay_id,
      episode_index = row$episode_index,
      outcome = row$outcome,
      next_outcome = row$next_outcome
    )

    violated_rules <- unique(unlist(lapply(c(
      'mandatory_violated_constraints',
      'info_violated_constraints'
    ), function(column_name) {
      if (!column_name %in% names(sbt_df)) {
        return(character(0))
      }
      parse_constraint_list(sbt_df[[column_name]][i])
    }), use.names = FALSE))

    # Vacuous (never activated) is deliberately excluded, not pooled with
    # satisfied: for a failure-activated rule, vacuous means "no SBT failure
    # occurred" — a different population from "failure occurred and was
    # corrected". Pooling makes exposure a proxy for the outcome.
    satisfied_rules <- unique(unlist(lapply(c(
      'mandatory_satisfied_constraints',
      'info_satisfied_constraints'
    ), function(column_name) {
      if (!column_name %in% names(sbt_df)) {
        return(character(0))
      }
      parse_constraint_list(sbt_df[[column_name]][i])
    }), use.names = FALSE))

    for (rule_id in all_rules) {
      if (rule_id %in% violated_rules) {
        case_row[[rule_id]] <- 1
      } else if (rule_id %in% satisfied_rules) {
        case_row[[rule_id]] <- 0
      } else {
        case_row[[rule_id]] <- NA_real_
      }
    }
    case_rows[[i]] <- case_row
  }

  case_df <- do.call(rbind, lapply(case_rows, function(x) as.data.frame(x, stringsAsFactors = FALSE, check.names = FALSE)))
  rownames(case_df) <- NULL
  case_df$outcome <- as.numeric(case_df$outcome)
  case_df
}

analyze_rule <- function(data, rule_col, outcome_col = 'outcome') {
  # For inter-episode rules outcome_col = 'next_outcome'; the NA-drop below is
  # the censoring step (episodes without a subsequent evaluable episode).
  activated <- data[!is.na(data[[rule_col]]), , drop = FALSE]
  valid <- activated[!is.na(activated[[outcome_col]]), , drop = FALSE]
  n_censored <- nrow(activated) - nrow(valid)
  outcome_variable <- if (outcome_col == 'next_outcome') 'next_episode' else 'same_episode'
  if (nrow(valid) == 0) {
    return(data.frame(
      rule_name = rule_col,
      outcome_variable = outcome_variable,
      n_censored = n_censored,
      n_exposed = NA_real_,
      n_unexposed = NA_real_,
      a = NA_real_,
      b = NA_real_,
      c = NA_real_,
      d = NA_real_,
      fisher_p = NA_real_,
      or = NA_real_,
      or_low = NA_real_,
      or_high = NA_real_,
      rr = NA_real_,
      rr_low = NA_real_,
      rr_high = NA_real_,
      stringsAsFactors = FALSE
    ))
  }

  a <- sum(valid[[rule_col]] == 1 & valid[[outcome_col]] == 1)
  b <- sum(valid[[rule_col]] == 1 & valid[[outcome_col]] == 0)
  c <- sum(valid[[rule_col]] == 0 & valid[[outcome_col]] == 1)
  d <- sum(valid[[rule_col]] == 0 & valid[[outcome_col]] == 0)

  n_exposed <- a + b
  n_unexposed <- c + d

  if (n_exposed == 0 || n_unexposed == 0) {
    return(data.frame(
      rule_name = rule_col,
      outcome_variable = outcome_variable,
      n_censored = n_censored,
      n_exposed = n_exposed,
      n_unexposed = n_unexposed,
      a = a,
      b = b,
      c = c,
      d = d,
      fisher_p = NA_real_,
      or = NA_real_,
      or_low = NA_real_,
      or_high = NA_real_,
      rr = NA_real_,
      rr_low = NA_real_,
      rr_high = NA_real_,
      stringsAsFactors = FALSE
    ))
  }

  contingency <- matrix(c(a, b, c, d), nrow = 2, byrow = TRUE)
  fisher_result <- fisher.test(contingency)
  fisher_p <- fisher_result$p.value
  or <- as.numeric(fisher_result$estimate)
  or_low <- as.numeric(fisher_result$conf.int[1])
  or_high <- as.numeric(fisher_result$conf.int[2])

  has_zero <- any(c(a, b, c, d) == 0)
  ac <- if (has_zero) a + 0.5 else a
  bc <- if (has_zero) b + 0.5 else b
  cc <- if (has_zero) c + 0.5 else c
  dc <- if (has_zero) d + 0.5 else d

  rr <- (ac / (ac + bc)) / (cc / (cc + dc))
  rr <- safe_num(rr)
  if (is.na(rr) || is.nan(rr)) {
    rr_low <- NA_real_
    rr_high <- NA_real_
  } else {
    se_ln_rr <- sqrt(1 / ac - 1 / (ac + bc) + 1 / cc - 1 / (cc + dc))
    if (is.na(se_ln_rr) || is.nan(se_ln_rr) || is.infinite(se_ln_rr)) {
      rr_low <- NA_real_
      rr_high <- NA_real_
    } else {
      rr_low <- exp(log(rr) - 1.96 * se_ln_rr)
      rr_high <- exp(log(rr) + 1.96 * se_ln_rr)
    }
  }

  data.frame(
    rule_name = rule_col,
    outcome_variable = outcome_variable,
    n_censored = n_censored,
    n_exposed = n_exposed,
    n_unexposed = n_unexposed,
    a = a,
    b = b,
    c = c,
    d = d,
    fisher_p = fisher_p,
    or = or,
    or_low = or_low,
    or_high = or_high,
    rr = rr,
    rr_low = rr_low,
    rr_high = rr_high,
    stringsAsFactors = FALSE
  )
}

if (!file.exists(input_csv)) {
  stop(paste('Input file not found:', input_csv))
}

episodes <- read.csv(input_csv, stringsAsFactors = FALSE, na.strings = c('', 'NA'))
if (!'sbt_attempt' %in% names(episodes)) {
  stop('Input CSV must contain sbt_attempt and conformance columns')
}

case_table <- build_case_level_table(episodes)
if (nrow(case_table) == 0) {
  write.csv(case_table, analysis_table_csv, row.names = FALSE, na = '')
  write.csv(data.frame(), rule_statistics_csv, row.names = FALSE, na = '')
  quit(status = 0)
}

write.csv(case_table, analysis_table_csv, row.names = FALSE, na = '')

id_cols <- c('stay_id', 'episode_index', 'outcome', 'next_outcome')
rule_cols <- setdiff(names(case_table), id_cols)
rule_cols <- rule_cols[grepl('-', rule_cols)]

# Inter-episode rules: exposure measured in episode i, outcome = episode i+1.
# Keep in sync with `outcome_scope: next_episode` in configs/declare/*.yaml.
inter_episode_rules <- c(
  'INT-TR-01', 'INT-TR-02', 'INT-TR-03', 'INT-TR-04', 'INT-TR-05',
  'INT-DX-04', 'INT-DX-05', 'INT-COMPOSITE-01',
  'SBT-TM-01', 'SBT-TM-01-early', 'SBT-TM-01-late'
)

results <- do.call(rbind, lapply(rule_cols, function(rule_col) {
  outcome_col <- if (rule_col %in% inter_episode_rules) 'next_outcome' else 'outcome'
  analyze_rule(case_table, rule_col, outcome_col)
}))
if (nrow(results) == 0) {
  write.csv(results, rule_statistics_csv, row.names = FALSE, na = '')
  quit(status = 0)
}

write.csv(results, rule_statistics_csv, row.names = FALSE, na = '')
