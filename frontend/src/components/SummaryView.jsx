import React, { useMemo, useState, useEffect, useRef } from 'react';
import { getConstraintIcon, formatPercent } from './SummaryView/utils';
import ContrastBarChart from './SummaryView/ContrastBarChart';
import ConstraintDetailView from './SummaryView/ConstraintDetailView';
import OutcomeScatterPlot from './SummaryView/OutcomeScatterPlot';
import StatsDeepDive from './SummaryView/StatsDeepDive';

const DEFAULT_STAY_SORT_BY = 'total_mandatory_violations';
const SORT_LABEL_MAP = {
  total_mandatory_violations: 'Total Violations',
  avg_mandatory_violations: 'Avg Violations',
  episodes: 'Episode Count',
  overall_outcome: 'Overall Outcome',
  stay_id: 'Stay ID',
};

const RULE_MODE_LABEL_MAP = {
  violated: 'Violated',
  satisfied: 'Satisfied',
  both: 'Either',
};

// section: 'frequencies' | 'correlations' | 'statistics' | 'patients'
const SummaryView = ({ summaryData, section = 'frequencies', onSelectStay }) => {
  const [query, setQuery] = useState('');
  const [sortBy, setSortBy] = useState(DEFAULT_STAY_SORT_BY);
  const [analysisMode, setAnalysisMode] = useState('violation');
  const [selectedConstraintId, setSelectedConstraintId] = useState(null);
  const [forensicsSidebarWidth, setForensicsSidebarWidth] = useState(550);
  const [selectedRules, setSelectedRules] = useState([]);
  const [ruleToAdd, setRuleToAdd] = useState('');
  const [ruleFilterMode, setRuleFilterMode] = useState('violated');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [isRulePickerOpen, setIsRulePickerOpen] = useState(false);
  const isResizing = React.useRef(false);
  const rulePickerButtonRef = useRef(null);
  const rulePickerMenuRef = useRef(null);

  const activeFilterChips = useMemo(() => {
    const chips = [];
    const trimmedQuery = query.trim();
    if (trimmedQuery) chips.push({ label: 'Search', value: trimmedQuery });
    if (sortBy !== DEFAULT_STAY_SORT_BY) chips.push({ label: 'Sort', value: SORT_LABEL_MAP[sortBy] || sortBy });
    if (ruleFilterMode !== 'violated') chips.push({ label: 'Mode', value: RULE_MODE_LABEL_MAP[ruleFilterMode] || ruleFilterMode });
    return chips;
  }, [query, ruleFilterMode, sortBy]);

  const ruleOptions = summaryData?.violation_frequency || [];

  const selectedRuleDetails = useMemo(() => {
    if (selectedRules.length === 0) return [];
    const selectedSet = new Set(selectedRules);
    return ruleOptions.filter(rule => selectedSet.has(rule.constraint_id));
  }, [ruleOptions, selectedRules]);

  const availableRuleOptions = useMemo(() => {
    const selectedSet = new Set(selectedRules);
    return ruleOptions.filter(rule => !selectedSet.has(rule.constraint_id));
  }, [ruleOptions, selectedRules]);

  useEffect(() => {
    if (!ruleToAdd && availableRuleOptions.length > 0) {
      setRuleToAdd(availableRuleOptions[0].constraint_id);
    }
    if (ruleToAdd && !availableRuleOptions.some(r => r.constraint_id === ruleToAdd)) {
      setRuleToAdd(availableRuleOptions[0]?.constraint_id || '');
    }
  }, [availableRuleOptions, ruleToAdd]);

  useEffect(() => {
    if (!isRulePickerOpen) return;
    const handlePointerDown = e => {
      if (rulePickerButtonRef.current?.contains(e.target) || rulePickerMenuRef.current?.contains(e.target)) return;
      setIsRulePickerOpen(false);
    };
    const handleKeyDown = e => { if (e.key === 'Escape') setIsRulePickerOpen(false); };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isRulePickerOpen]);

  useEffect(() => { setCurrentPage(1); }, [query, sortBy, ruleFilterMode, selectedRules]);

  const resetStayFilters = () => {
    setQuery('');
    setSortBy(DEFAULT_STAY_SORT_BY);
    setRuleFilterMode('violated');
    setSelectedRules([]);
    setRuleToAdd('');
    setCurrentPage(1);
  };

  const addSelectedRule = () => {
    if (!ruleToAdd || selectedRules.includes(ruleToAdd)) return;
    setSelectedRules(prev => [...prev, ruleToAdd]);
    setRuleToAdd('');
    setIsRulePickerOpen(false);
  };

  const selectedRuleToAdd = availableRuleOptions.find(r => r.constraint_id === ruleToAdd) || availableRuleOptions[0] || null;

  const removeSelectedRule = constraintId => setSelectedRules(prev => prev.filter(id => id !== constraintId));

  const startResizing = () => {
    isResizing.current = true;
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', stopResizing);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  const stopResizing = () => {
    isResizing.current = false;
    document.removeEventListener('mousemove', handleMouseMove);
    document.removeEventListener('mouseup', stopResizing);
    document.body.style.cursor = 'default';
    document.body.style.userSelect = 'auto';
  };

  const handleMouseMove = e => {
    if (!isResizing.current) return;
    const sec = document.querySelector('.forensics-layout');
    if (sec) {
      const rect = sec.getBoundingClientRect();
      const newWidth = e.clientX - rect.left;
      if (newWidth > 200 && newWidth < 800) setForensicsSidebarWidth(newWidth);
    }
  };

  const topViolations = useMemo(() =>
    (summaryData?.violation_frequency || []).filter(v => v.count > 0).sort((a, b) => b.count - a.count),
    [summaryData]
  );

  const selectedConstraint = useMemo(
    () => topViolations.find(v => v.constraint_id === selectedConstraintId) || topViolations[0],
    [topViolations, selectedConstraintId]
  );

  const allCorrelationData = useMemo(() => {
    const data = [...(summaryData?.violation_frequency || [])];
    const isViolation = analysisMode === 'violation';
    return data.sort((a, b) => {
      const aCount = isViolation ? (a.count_success + a.count_failure) : a.count_satisfied;
      const bCount = isViolation ? (b.count_success + b.count_failure) : b.count_satisfied;
      if (aCount === 0 && bCount > 0) return 1;
      if (bCount === 0 && aCount > 0) return -1;
      const liftA = isViolation ? (a.lift_failure || 1) : (a.lift_success || 1);
      const liftB = isViolation ? (b.lift_failure || 1) : (b.lift_success || 1);
      return Math.abs(liftB - 1) - Math.abs(liftA - 1);
    });
  }, [summaryData, analysisMode]);

  const allFilteredStays = useMemo(() => {
    const rows = [...(summaryData?.stay_summaries || [])];
    const normalizedQuery = query.trim().toLowerCase();
    let filtered = normalizedQuery
      ? rows.filter(row => String(row.stay_id).toLowerCase().includes(normalizedQuery))
      : rows;
    if (selectedRules.length > 0) {
      filtered = filtered.filter(row => {
        const v = row.violated_constraints || [];
        const s = row.satisfied_constraints || [];
        return selectedRules.some(cid => {
          if (ruleFilterMode === 'violated') return v.includes(cid);
          if (ruleFilterMode === 'satisfied') return s.includes(cid);
          return v.includes(cid) || s.includes(cid);
        });
      });
    }
    filtered.sort((a, b) => {
      if (sortBy === 'stay_id') return String(a.stay_id).localeCompare(String(b.stay_id));
      if (sortBy === 'overall_outcome') return String(a.overall_outcome).localeCompare(String(b.overall_outcome));
      return Number(b[sortBy] || 0) - Number(a[sortBy] || 0);
    });
    return filtered;
  }, [summaryData, query, ruleFilterMode, selectedRules, sortBy]);

  const totalResults = allFilteredStays.length;
  const totalPages = Math.ceil(totalResults / pageSize);
  const stayRows = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return allFilteredStays.slice(start, start + pageSize);
  }, [allFilteredStays, currentPage, pageSize]);

  const openFirstMatch = () => {
    const normalizedQuery = query.trim();
    if (!normalizedQuery || allFilteredStays.length === 0) return;
    const exactMatch = allFilteredStays.find(row => String(row.stay_id).toLowerCase() === normalizedQuery.toLowerCase());
    const target = exactMatch || allFilteredStays[0];
    if (target) onSelectStay?.(String(target.stay_id));
  };

  const handleSearchKeyDown = e => { if (e.key === 'Enter') { e.preventDefault(); openFirstMatch(); } };

  const outcomeStats = summaryData?.conformance_vs_outcome || {};
  const successStats = outcomeStats.success || {};
  const failureStats = outcomeStats.failure || {};

  // ── FREQUENCIES ──────────────────────────────────────────────
  if (section === 'frequencies') {
    return (
      <div className="section-page">
        <div className="section-kpi-grid">
          <section className="summary-card metric-card">
            <h3>Total Stays</h3>
            <p className="metric-value">{summaryData?.total_stays ?? 0}</p>
          </section>
          <section className="summary-card metric-card">
            <h3>Total Episodes</h3>
            <p className="metric-value">{summaryData?.total_episodes ?? 0}</p>
          </section>
          <section className="summary-card metric-card">
            <h3>Avg Violations (SBT Success)</h3>
            <p className="metric-value">{Number(successStats.avg_mandatory_violations || 0).toFixed(2)}</p>
            <p className="metric-subtext">n={successStats.episodes || 0}</p>
          </section>
          <section className="summary-card metric-card">
            <h3>Avg Violations (SBT Failure)</h3>
            <p className="metric-value">{Number(failureStats.avg_mandatory_violations || 0).toFixed(2)}</p>
            <p className="metric-subtext">n={failureStats.episodes || 0}</p>
          </section>
        </div>

        <section className="summary-card forensics-explorer">
          <div className="section-header">
            <div className="title-group">
              <h3>Violation Forensics Explorer</h3>
              <p className="header-subtitle">Deep-dive into the magnitudes and timing of rule breaches</p>
            </div>
          </div>
          <div className="forensics-layout">
            <div className="forensics-master" style={{ width: forensicsSidebarWidth, flex: 'none' }}>
              <div className="master-header">
                <h4>Most Frequent {analysisMode === 'violation' ? 'Violations' : 'Satisfactions'}</h4>
              </div>
              <div className="runner-freq-legend">
                <span className="runner-freq-legend-item runner-freq-legend-item--fail">Failure violation rate</span>
                <span className="runner-freq-legend-item runner-freq-legend-item--succ">Success violation rate</span>
              </div>
              <div className="forensics-list">
                {topViolations.slice(0, 15).map(v => {
                  const cls = v.rule_class || 'neutral'
                  const pct = ((v.episode_share || 0) * 100).toFixed(1)
                  const icon = getConstraintIcon(v.constraint_id)
                  return (
                    <div
                      key={v.constraint_id}
                      className={`run-constraint-row ${selectedConstraint?.constraint_id === v.constraint_id ? 'run-constraint-row--selected' : ''}`}
                      onClick={() => setSelectedConstraintId(v.constraint_id)}
                    >
                      <div className="run-constraint-row-top">
                        {icon && <img className="run-constraint-icon" src={icon} alt="" />}
                        <span className="run-constraint-label" title={v.constraint_label}>{v.constraint_label}</span>
                        <span className={`run-constraint-class run-constraint-class--${cls}`}>{cls}</span>
                      </div>
                      <div className="run-constraint-bar-wrap">
                        <div className="run-constraint-bar-track">
                          <div className="run-constraint-bar-viol" style={{ width: `${((v.violation_rate_failure || 0) * 100).toFixed(1)}%` }} title={`Failure: ${((v.violation_rate_failure || 0) * 100).toFixed(1)}%`} />
                          <div className="run-constraint-bar-succ" style={{ width: `${((v.violation_rate_success || 0) * 100).toFixed(1)}%` }} title={`Success: ${((v.violation_rate_success || 0) * 100).toFixed(1)}%`} />
                        </div>
                        <span className="run-constraint-pct">{pct}%</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="forensics-resizer" onMouseDown={startResizing} />
            <div className="forensics-detail">
              <ConstraintDetailView constraint={selectedConstraint} itemLabels={summaryData?.item_labels} />
            </div>
          </div>
        </section>
      </div>
    );
  }

  // ── STATISTICS ────────────────────────────────────────────────
  if (section === 'statistics') {
    return (
      <div className="section-page">
        <section className="summary-card">
          <div className="section-header">
            <div className="title-group">
              <h3>Statistical Significance Analysis</h3>
              <p className="header-subtitle">Formal associations between process adherence and weaning outcome</p>
            </div>
          </div>
          <StatsDeepDive summaryData={summaryData} />
        </section>
        <section className="summary-card correlation-deep-dive">
          <div className="section-header">
            <div className="title-group">
              <h3>SBT Outcome Correlation Analysis</h3>
              <p className="header-subtitle">Understanding which constraints drive trial {analysisMode === 'violation' ? 'failure' : 'success'}</p>
            </div>
            <div className="tab-switcher">
              <button className={`tab-btn ${analysisMode === 'violation' ? 'active' : ''}`} onClick={() => setAnalysisMode('violation')}>
                Violation Analysis
              </button>
              <button className={`tab-btn ${analysisMode === 'satisfaction' ? 'active' : ''}`} onClick={() => setAnalysisMode('satisfaction')}>
                Satisfaction Analysis
              </button>
            </div>
          </div>
          <div className="correlation-layout">
            <div className="correlation-plot-area">
              <h4>{analysisMode === 'violation' ? 'Outcome Distribution (Success vs. Failure)' : 'Outcome Distribution (Failure vs. Success)'}</h4>
              <OutcomeScatterPlot items={allCorrelationData} mode={analysisMode} />
            </div>
            <div className="correlation-list-area">
              <h4>All Constraints Ranked by {analysisMode === 'violation' ? 'Failure' : 'Success'} Lift</h4>
              <div className="scrollable-lift-list">
                <ContrastBarChart items={allCorrelationData} mode={analysisMode} />
              </div>
            </div>
          </div>
        </section>
      </div>
    );
  }

  // ── PATIENTS ──────────────────────────────────────────────────
  if (section === 'patients') {
    return (
      <div className="section-page">
        <section className="summary-card">
          <div className="section-header stay-explorer-header">
            <div className="title-group">
              <h3>Stay Explorer</h3>
              <p className="header-subtitle">Filter stays by case ID, ranking, and rule involvement before opening the timeline.</p>
            </div>
            <div className="stay-explorer-status">
              <span className="stay-match-pill">
                {totalResults} {totalResults === 1 ? 'match' : 'matches'}
              </span>
              {activeFilterChips.length > 0 && (
                <button type="button" className="stay-reset-btn" onClick={resetStayFilters}>
                  Clear filters
                </button>
              )}
            </div>
          </div>

          <div className="stay-filter-panel">
            <div className="stay-filter-grid">
              <div className="stay-filter-block stay-search-block">
                <div className="stay-filter-label-row">
                  <span className="stay-filter-label">Search</span>
                  <span className="stay-filter-hint">Case ID or stay ID</span>
                </div>
                <div className="stay-search-row">
                  <input
                    className="summary-input stay-search-input"
                    type="text"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    onKeyDown={handleSearchKeyDown}
                    placeholder="Search case ID…"
                  />
                  <button
                    type="button"
                    className="pag-btn stay-primary-action"
                    disabled={!query.trim() || totalResults === 0}
                    onClick={openFirstMatch}
                  >
                    Open first match
                  </button>
                </div>
              </div>

              <div className="stay-filter-block stay-sort-block">
                <div className="stay-filter-label-row">
                  <span className="stay-filter-label">Sort and mode</span>
                  <span className="stay-filter-hint">Rank and constrain the table</span>
                </div>
                <div className="stay-inline-controls">
                  <select className="summary-select stay-control-select" value={sortBy} onChange={e => setSortBy(e.target.value)}>
                    <option value="total_mandatory_violations">Sort: Total Violations</option>
                    <option value="avg_mandatory_violations">Sort: Avg Violations</option>
                    <option value="episodes">Sort: Episode Count</option>
                    <option value="overall_outcome">Sort: Overall Outcome</option>
                    <option value="stay_id">Sort: Stay ID</option>
                  </select>
                  <select className="summary-select stay-control-select" value={ruleFilterMode} onChange={e => setRuleFilterMode(e.target.value)}>
                    <option value="violated">Filter Mode: Violated</option>
                    <option value="satisfied">Filter Mode: Satisfied</option>
                    <option value="both">Filter Mode: Either</option>
                  </select>
                </div>
              </div>

              <div className="stay-filter-block stay-rules-block">
                <div className="stay-filter-label-row">
                  <span className="stay-filter-label">Rule filter</span>
                  <div className="stay-rule-meta">
                    <span className="stay-filter-hint">{selectedRules.length} selected</span>
                    {selectedRules.length > 0 && (
                      <button type="button" className="stay-clear-rules-btn" onClick={() => setSelectedRules([])}>
                        Clear all
                      </button>
                    )}
                  </div>
                </div>
                <div className="stay-rule-picker-row">
                  <div className="stay-rule-picker">
                    <button
                      ref={rulePickerButtonRef}
                      type="button"
                      className="summary-select stay-rule-picker-trigger"
                      onClick={() => setIsRulePickerOpen(prev => !prev)}
                      disabled={availableRuleOptions.length === 0}
                      aria-haspopup="listbox"
                      aria-expanded={isRulePickerOpen}
                    >
                      <span className="stay-rule-picker-trigger-text">
                        {selectedRuleToAdd ? (
                          <>
                            <span className="stay-rule-picker-trigger-id">{selectedRuleToAdd.constraint_id}</span>
                            <span className="stay-rule-picker-trigger-label">{selectedRuleToAdd.constraint_label}</span>
                          </>
                        ) : 'No more rules available'}
                      </span>
                      <span className="stay-rule-picker-caret" aria-hidden="true">▾</span>
                    </button>
                    {isRulePickerOpen && availableRuleOptions.length > 0 && (
                      <div ref={rulePickerMenuRef} className="stay-rule-picker-menu" role="listbox">
                        {availableRuleOptions.map(rule => (
                          <button
                            key={rule.constraint_id}
                            type="button"
                            className={`stay-rule-option ${rule.constraint_id === ruleToAdd ? 'active' : ''}`}
                            onClick={() => { setRuleToAdd(rule.constraint_id); setIsRulePickerOpen(false); }}
                            title={`${rule.constraint_id} — ${rule.constraint_label}`}
                          >
                            <span className="stay-rule-option-id">{rule.constraint_id}</span>
                            <span className="stay-rule-option-label">{rule.constraint_label}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    className="pag-btn stay-add-rule-btn"
                    onClick={addSelectedRule}
                    disabled={!ruleToAdd || availableRuleOptions.length === 0}
                  >
                    Add rule
                  </button>
                </div>
                <div className="selected-rule-chips" aria-label="Selected rules">
                  {selectedRuleDetails.length > 0 ? selectedRuleDetails.map(rule => (
                    <button
                      key={rule.constraint_id}
                      type="button"
                      className="selected-rule-chip"
                      onClick={() => removeSelectedRule(rule.constraint_id)}
                      title={`Remove ${rule.constraint_id}`}
                    >
                      <span className="selected-rule-chip-id">{rule.constraint_id}</span>
                      <span className="selected-rule-chip-label">{rule.constraint_label}</span>
                      <span className="selected-rule-chip-remove">×</span>
                    </button>
                  )) : (
                    <div className="selected-rule-empty">No rules selected. Choose a rule and add it to narrow the table.</div>
                  )}
                </div>
              </div>
            </div>

            <div className="stay-filter-footer">
              <div className="active-filter-chips" aria-label="Active filters">
                {activeFilterChips.length > 0 ? activeFilterChips.map(chip => (
                  <span key={`${chip.label}:${chip.value}`} className="filter-chip">
                    <span className="filter-chip-label">{chip.label}</span>
                    <span className="filter-chip-value">{chip.value}</span>
                  </span>
                )) : (
                  <span className="filter-chip filter-chip-muted">No active filters</span>
                )}
              </div>
              <div className="stay-filter-note">Press Enter in search to open the first match.</div>
            </div>
          </div>

          <div className="summary-table-wrapper">
            <table className="summary-table">
              <thead>
                <tr>
                  <th>Stay ID</th>
                  <th>Outcome</th>
                  <th>Episodes</th>
                  <th>Total Violations</th>
                  <th>Avg Violations</th>
                  <th>Unique Violated Constraints</th>
                  <th>Violations</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {stayRows.map(row => (
                  <tr key={row.stay_id}>
                    <td>{row.stay_id}</td>
                    <td>{row.overall_outcome}</td>
                    <td>{row.episodes}</td>
                    <td>{row.total_mandatory_violations}</td>
                    <td>{Number(row.avg_mandatory_violations || 0).toFixed(2)}</td>
                    <td>{row.violated_constraints_count}</td>
                    <td>
                      {(row.violated_constraints || []).slice(0, 2).join(', ')}
                      {(row.violated_constraints || []).length > 2 ? ` (+${(row.violated_constraints || []).length - 2})` : ''}
                    </td>
                    <td>
                      <button className="open-stay-button" onClick={() => onSelectStay?.(String(row.stay_id))}>
                        Open Timeline
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {stayRows.length === 0 && <p className="summary-empty">No stays match the current filter.</p>}
          </div>

          {totalResults > 0 && (
            <div className="table-pagination">
              <div className="pagination-info">
                Showing <strong>{(currentPage - 1) * pageSize + 1}</strong> to <strong>{Math.min(currentPage * pageSize, totalResults)}</strong> of <strong>{totalResults}</strong> stays
              </div>
              <div className="pagination-controls">
                <div className="page-size-selector">
                  <label>Rows per page:</label>
                  <select value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
                    <option value={10}>10</option>
                    <option value={25}>25</option>
                    <option value={50}>50</option>
                    <option value={100}>100</option>
                  </select>
                </div>
                <button className="pag-btn" disabled={currentPage === 1} onClick={() => setCurrentPage(p => p - 1)}>Previous</button>
                <span className="page-num">Page <strong>{currentPage}</strong> of {totalPages}</span>
                <button className="pag-btn" disabled={currentPage === totalPages} onClick={() => setCurrentPage(p => p + 1)}>Next</button>
              </div>
            </div>
          )}
        </section>
      </div>
    );
  }

  return null;
};

export default SummaryView;
