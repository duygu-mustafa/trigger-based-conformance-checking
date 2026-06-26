# Graph Report - .  (2026-06-02)

## Corpus Check
- Corpus is ~48,039 words - fits in a single context window. You may not need a graph.

## Summary
- 564 nodes · 1419 edges · 26 communities (16 shown, 10 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 222 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Rule Evaluation Engine|Rule Evaluation Engine]]
- [[_COMMUNITY_Declare Model Types|Declare Model Types]]
- [[_COMMUNITY_Conformance Checking Pipeline|Conformance Checking Pipeline]]
- [[_COMMUNITY_Event Log Construction|Event Log Construction]]
- [[_COMMUNITY_Batch Processing Runner|Batch Processing Runner]]
- [[_COMMUNITY_Frontend Summary Views|Frontend Summary Views]]
- [[_COMMUNITY_Database Preparation|Database Preparation]]
- [[_COMMUNITY_Evaluation Core Logic|Evaluation Core Logic]]
- [[_COMMUNITY_Activity Derivation|Activity Derivation]]
- [[_COMMUNITY_Database Client|Database Client]]
- [[_COMMUNITY_Statistical Analysis|Statistical Analysis]]
- [[_COMMUNITY_Summary Generation|Summary Generation]]
- [[_COMMUNITY_Clinical Methodology|Clinical Methodology]]
- [[_COMMUNITY_Outcome Postprocessing|Outcome Postprocessing]]
- [[_COMMUNITY_Clock Icon|Clock Icon]]
- [[_COMMUNITY_Shell Script|Shell Script]]
- [[_COMMUNITY_Data Icon|Data Icon]]
- [[_COMMUNITY_Correlation Tests|Correlation Tests]]
- [[_COMMUNITY_SBT Episode Tests|SBT Episode Tests]]
- [[_COMMUNITY_Package Init|Package Init]]
- [[_COMMUNITY_Negative Templates|Negative Templates]]
- [[_COMMUNITY_Conformance Scoring Docs|Conformance Scoring Docs]]
- [[_COMMUNITY_Control Flow Icon|Control Flow Icon]]
- [[_COMMUNITY_Info Icon|Info Icon]]
- [[_COMMUNITY_Statistics Tables|Statistics Tables]]

## God Nodes (most connected - your core abstractions)
1. `ConformanceOutcome` - 44 edges
2. `DataFrame` - 40 edges
3. `DeclareTemplate` - 39 edges
4. `str` - 38 edges
5. `DeclareModel` - 37 edges
6. `TraceResult` - 36 edges
7. `_evaluate_constraint_impl()` - 35 edges
8. `DeclareConstraint` - 34 edges
9. `ConstraintResult` - 32 edges
10. `DeclareConstraint` - 30 edges

## Surprising Connections (you probably didn't know these)
- `Episode-level over Stay-level Evaluation` --rationale_for--> `_build_trigger_episodes()`  [INFERRED]
  methodological_overview.md → main_per_sbt.py
- `DuckDB Batch Processing` --rationale_for--> `main()`  [INFERRED]
  methodological_overview.md → prepare_event_log.py
- `_build_trigger_episodes()` --semantically_similar_to--> `_full_support_start_times_from_settings()`  [INFERRED] [semantically similar]
  main_per_sbt.py → derive/pipeline.py
- `Constraint (weighted scoring)` --conceptually_related_to--> `Constraint weights config`  [INFERRED]
  conformance/weighted_scoring.py → configs/declare/weights.yaml
- `Post-SBT failure correction Declare model` --references--> `build_failure_correction_model()`  [INFERRED]
  configs/declare/failure_correction.yaml → conformance/rules.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Conformance checking pipeline** — conformance_event_log_builder_build_event_log, conformance_checker_check_log_conformance, conformance_checker_evaluate_constraint, conformance_checker__template_evaluators, conformance_checker__evaluate_constraint_impl, conformance_results_ConstraintResult, conformance_results_TraceResult [EXTRACTED 1.00]
- **Declare constraint type system** — conformance_types_DeclareTemplate, conformance_types_DeclareConstraint, conformance_types_DeclareModel, conformance_types_DataCondition, conformance_types_TimeCondition, conformance_types_UNARY_TEMPLATES, conformance_types_NEGATIVE_TEMPLATES [EXTRACTED 1.00]
- **Fuzzy weighted scoring system** — conformance_weighted_scoring_Constraint, conformance_weighted_scoring_ViolationInstance, conformance_weighted_scoring_TraceScore, conformance_weighted_scoring_compute_w_max, conformance_weighted_scoring_compute_importance_weight, conformance_weighted_scoring_compute_threshold_severity, conformance_weighted_scoring_compute_violation_severity, conformance_weighted_scoring_compute_violation_weight, conformance_weighted_scoring_score_trace_result, conformance_weighted_scoring_sugeno_kpi [EXTRACTED 1.00]
- **Pipeline Stages: Data Extraction → Event Log → Conformance → Statistics → Frontend** — database_materialize_all_icu_events_main, prepare_event_log_main, main_per_sbt_main, derive_statistical_analysis_build_case_level_table, main_per_sbt_export_to_frontend [EXTRACTED 1.00]
- **SBT Derivation: Weaning Frame → State Classification → Episode Construction → Event Emission** — derive_pipeline_derive_weaning_frame_from_raw, derive_sbt_episodes_map_weaning_state, derive_sbt_episodes_build_sbt_episodes, derive_pipeline_raw_to_event_log [EXTRACTED 1.00]
- **Three Declare Rule Models: Readiness, SBT Execution, Failure Correction** — main_per_sbt_build_combined_model, trigger_episode_segmentation, episode_level_evaluation, fuzzy_weighted_scoring [INFERRED 0.85]
- **Statistical association analysis pipeline** — test_correlation_condition_TestCorrelationCondition, statistics_R_analyze_rule, summaryview_statsdeepdive_StatsDeepDive, concept_fisher_exact_test, concept_benjamini_hochberg [INFERRED 0.75]
- **Summary dashboard visualization components** — summaryview_contrastbarchart_ContrastBarChart, summaryview_outcomescatterplot_OutcomeScatterPlot, summaryview_histogram_Histogram, summaryview_constraintdetailview_ConstraintDetailView, components_summaryview_SummaryView [INFERRED 0.85]
- **Data export to frontend pipeline** — scratch_export_case_export_case_data, scratch_export_sample_case_export_case_data, components_timeline_Timeline, components_summaryview_SummaryView [INFERRED 0.75]

## Communities (26 total, 10 thin omitted)

### Community 0 - "Rule Evaluation Engine"
Cohesion: 0.08
Nodes (78): _build_eval_context(), _build_items_snapshot(), _coerce_value(), evaluate_absence_rule(), evaluate_alternate_precedence_rule(), evaluate_alternate_response_rule(), evaluate_alternate_succession_rule(), evaluate_chain_precedence_rule() (+70 more)

### Community 1 - "Declare Model Types"
Cohesion: 0.09
Nodes (70): Constraint weights config, bool, DeclareModel, int, object, Series, TraceResult, ConformanceOutcome (+62 more)

### Community 2 - "Conformance Checking Pipeline"
Cohesion: 0.08
Nodes (51): Activity mapping config, Post-SBT failure correction Declare model, Readiness assessment Declare model, SBT execution Declare model, MIMIC-IV item dictionary, check_log_conformance(), Check an entire event log for conformance to a Declare process model.      Evalu, TraceResult (+43 more)

### Community 3 - "Event Log Construction"
Cohesion: 0.06
Nodes (58): BatchConformanceRunner, CANONICAL_EVENT_LOG_COLUMNS, build_event_log(), DataFrame, Normalize activity dataframe to canonical conformance event-log schema., build_sbt_episodes(), _derive_weaning_frame_from_raw(), _explicit_invasive_vent_start_times_from_raw() (+50 more)

### Community 4 - "Batch Processing Runner"
Cohesion: 0.08
Nodes (49): BatchConformanceRunner, BatchConformanceRunner, Any, int, Path, str, TraceResult, Batch conformance runner for large-scale ICU event logs.  This module provides a (+41 more)

### Community 5 - "Frontend Summary Views"
Cohesion: 0.06
Nodes (31): RulesOverview, RulesOverview(), SummaryView, RULE_MODE_LABEL_MAP, SORT_LABEL_MAP, SummaryView(), Timeline, getConstraintIcon() (+23 more)

### Community 6 - "Database Preparation"
Cohesion: 0.14
Nodes (31): DuckDBPyConnection, Exception, Namespace, _backup_dir_default(), _checkpoint_skip_count(), _create_view(), _event_log_table_exists(), _export_checkpoint_backup() (+23 more)

### Community 7 - "Evaluation Core Logic"
Cohesion: 0.08
Nodes (28): _build_eval_context, _build_items_snapshot, _coerce_value, _evaluate_constraint_impl, _evaluate_data_condition, _evaluate_data_condition_status, _filter_activation_rows, _first_ts (+20 more)

### Community 8 - "Activity Derivation"
Cohesion: 0.17
Nodes (20): _activity_rules(), _derive_activities(), emit_activities(), _item_label_lookup(), _load_yaml(), _measurement_activity_label(), _normalize_raw_input(), Any (+12 more)

### Community 9 - "Database Client"
Cohesion: 0.19
Nodes (17): get_postgres_connection(), PostgreSQL connection helpers for MIMIC-IV queries., Create a PostgreSQL connection using environment variables.      Defaults match, _create_table_sql(), _export_csv(), _export_data(), _export_parquet(), main() (+9 more)

### Community 10 - "Statistical Analysis"
Cohesion: 0.15
Nodes (17): binarize_outcome(), build_case_level_table(), calculate_stats(), generate_contingency_table(), get_rule_binary(), load_conformance_data(), DataFrame, float (+9 more)

### Community 11 - "Summary Generation"
Cohesion: 0.32
Nodes (14): build_summary(), classify_outcome(), infer_input_dir(), _load_item_labels(), main(), parse_constraint_list(), Any, bool (+6 more)

### Community 12 - "Clinical Methodology"
Cohesion: 0.22
Nodes (9): Akella et al. (2022) SBT Guidelines, Custom Declare Engine, DuckDB Batch Processing, Episode-level over Stay-level Evaluation, Fuzzy Weighted Scoring over Binary Conformance, Clinical Conformance Checking for SBT Weaning Methodology, MIMIC-IV Database, SBT Conformance Testing Pipeline README (+1 more)

### Community 13 - "Outcome Postprocessing"
Cohesion: 0.43
Nodes (6): build_model_level_summary_frame(), DataFrame, str, Outcome-based post-processing utilities., Build a case-level wide table for analysis.      The output contains one row per, _require_columns()

### Community 14 - "Clock Icon"
Cohesion: 0.67
Nodes (3): Frontend Application, Clock SVG Icon, Clock Icon

## Knowledge Gaps
- **56 isolated node(s):** `DataFrame`, `bool`, `bool`, `bool`, `int` (+51 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `raw_to_event_log()` connect `Event Log Construction` to `Activity Derivation`, `Batch Processing Runner`, `Database Preparation`?**
  _High betweenness centrality (0.211) - this node is a cross-community bridge._
- **Why does `main()` connect `Database Preparation` to `Database Client`, `Event Log Construction`, `Clinical Methodology`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Why does `ConformanceOutcome` connect `Declare Model Types` to `Rule Evaluation Engine`, `Conformance Checking Pipeline`, `Batch Processing Runner`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Are the 36 inferred relationships involving `ConformanceOutcome` (e.g. with `BatchConformanceRunner` and `bool`) actually correct?**
  _`ConformanceOutcome` has 36 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `DataFrame` (e.g. with `ConformanceOutcome` and `ConstraintResult`) actually correct?**
  _`DataFrame` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 32 inferred relationships involving `DeclareTemplate` (e.g. with `bool` and `ConstraintResult`) actually correct?**
  _`DeclareTemplate` has 32 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `str` (e.g. with `ConformanceOutcome` and `ConstraintResult`) actually correct?**
  _`str` has 6 INFERRED edges - model-reasoned connections that need verification._