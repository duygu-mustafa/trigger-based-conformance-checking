import React, { useMemo, useState, useEffect } from 'react';
import { getConstraintIcon, formatPercent } from './SummaryView/utils';
import ContrastBarChart from './SummaryView/ContrastBarChart';
import ConstraintDetailView from './SummaryView/ConstraintDetailView';
import OutcomeScatterPlot from './SummaryView/OutcomeScatterPlot';
import StatsDeepDive from './SummaryView/StatsDeepDive';

const SummaryView = ({ summaryData, onSelectStay }) => {
  const [query, setQuery] = useState('');
  const [sortBy, setSortBy] = useState('total_mandatory_violations');
  const [analysisMode, setAnalysisMode] = useState('violation'); // 'violation' or 'satisfaction'
  const [subTab, setSubTab] = useState('dashboard'); // 'dashboard' or 'stats'
  const [selectedConstraintId, setSelectedConstraintId] = useState(null);
  const [forensicsSidebarWidth, setForensicsSidebarWidth] = useState(550);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const isResizing = React.useRef(false);

  // Reset to page 1 when searching or sorting
  useEffect(() => {
    setCurrentPage(1);
  }, [query, sortBy]);

  const startResizing = (e) => {
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

  const handleMouseMove = (e) => {
    if (!isResizing.current) return;
    const section = document.querySelector('.forensics-layout');
    if (section) {
      const rect = section.getBoundingClientRect();
      const newWidth = e.clientX - rect.left;
      if (newWidth > 200 && newWidth < 800) {
        setForensicsSidebarWidth(newWidth);
      }
    }
  };

  const topViolations = useMemo(
    () => {
      const all = (summaryData?.violation_frequency || [])
        .filter(v => v.count > 0)
        .sort((a, b) => b.count - a.count);
      return all;
    },
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
        const aCount = isViolation ? (a.count_success + a.count_failure) : (a.count_satisfied);
        const bCount = isViolation ? (b.count_success + b.count_failure) : (b.count_satisfied);
        
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

    const filtered = normalizedQuery
      ? rows.filter(row => String(row.stay_id).toLowerCase().includes(normalizedQuery))
      : rows;

    filtered.sort((a, b) => {
      if (sortBy === 'stay_id') return String(a.stay_id).localeCompare(String(b.stay_id));
      if (sortBy === 'overall_outcome') return String(a.overall_outcome).localeCompare(String(b.overall_outcome));
      return Number(b[sortBy] || 0) - Number(a[sortBy] || 0);
    });

    return filtered;
  }, [summaryData, query, sortBy]);

  const totalResults = allFilteredStays.length;
  const totalPages = Math.ceil(totalResults / pageSize);
  const stayRows = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return allFilteredStays.slice(start, start + pageSize);
  }, [allFilteredStays, currentPage, pageSize]);

  const outcomeStats = summaryData?.conformance_vs_outcome || {};
  const successStats = outcomeStats.success || {};
  const failureStats = outcomeStats.failure || {};

  return (
    <div className="summary-view">
      <div className="summary-header">
        <div className="sub-tab-switcher">
          <button 
            className={`sub-tab-btn ${subTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setSubTab('dashboard')}
          >
            Clinical Dashboard
          </button>
          <button 
            className={`sub-tab-btn ${subTab === 'stats' ? 'active' : ''}`}
            onClick={() => setSubTab('stats')}
          >
            Statistical Analysis
          </button>
        </div>
      </div>

      {subTab === 'dashboard' ? (
        <>
          <div className="summary-metrics-grid">
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
                  <span className="header-hint">Rate</span>
                </div>
                <div className="forensics-list">
                  {topViolations.slice(0, 15).map(v => {
                    const rate = analysisMode === 'violation' ? v.episode_share : (v.count_satisfied / (summaryData?.total_episodes || 1));
                    return (
                      <div 
                        key={v.constraint_id} 
                        className={`forensics-row ${selectedConstraint?.constraint_id === v.constraint_id ? 'active' : ''}`}
                        onClick={() => setSelectedConstraintId(v.constraint_id)}
                      >
                        <div className="row-bar-bg" style={{ 
                          width: `${rate * 100}%`,
                          backgroundColor: '#94a3b8',
                        }} />
                        <div className="row-content">
                          <div className="row-main">
                            <img src={getConstraintIcon(v.constraint_id)} alt="" className="row-icon" />
                            <span className="row-label" title={v.constraint_label}>{v.constraint_label}</span>
                          </div>
                          <div className="row-meta">
                            <span className="row-percent">{formatPercent(rate)}</span>
                          </div>
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

          <section className="summary-card correlation-deep-dive">
            <div className="section-header">
              <div className="title-group">
                <h3>SBT Outcome Correlation Analysis</h3>
                <p className="header-subtitle">Understanding which constraints drive trial {analysisMode === 'violation' ? 'failure' : 'success'}</p>
              </div>
              <div className="tab-switcher">
                <button 
                  className={`tab-btn ${analysisMode === 'violation' ? 'active' : ''}`} 
                  onClick={() => setAnalysisMode('violation')}
                >
                  Violation Analysis
                </button>
                <button 
                  className={`tab-btn ${analysisMode === 'satisfaction' ? 'active' : ''}`} 
                  onClick={() => setAnalysisMode('satisfaction')}
                >
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
        </>
      ) : (
        <section className="summary-card">
          <div className="section-header">
             <div className="title-group">
                <h3>Statistical Significance Analysis</h3>
                <p className="header-subtitle">Formal associations between process adherence and weaning outcome</p>
              </div>
          </div>
          <StatsDeepDive summaryData={summaryData} />
        </section>
      )}

      <section className="summary-card">
        <div className="table-header-row">
          <h3>Stay Explorer</h3>
          <div className="table-controls">
            <input
              className="summary-input"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search stay ID..."
            />
            <select
              className="summary-select"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
            >
              <option value="total_mandatory_violations">Sort: Total Violations</option>
              <option value="avg_mandatory_violations">Sort: Avg Violations</option>
              <option value="episodes">Sort: Episode Count</option>
              <option value="overall_outcome">Sort: Overall Outcome</option>
              <option value="stay_id">Sort: Stay ID</option>
            </select>
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
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {stayRows.map((row) => (
                <tr key={row.stay_id}>
                  <td>{row.stay_id}</td>
                  <td>{row.overall_outcome}</td>
                  <td>{row.episodes}</td>
                  <td>{row.total_mandatory_violations}</td>
                  <td>{Number(row.avg_mandatory_violations || 0).toFixed(2)}</td>
                  <td>{row.violated_constraints_count}</td>
                  <td>
                    <button
                      className="open-stay-button"
                      onClick={() => onSelectStay?.(String(row.stay_id))}
                    >
                      Open Timeline
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {stayRows.length === 0 ? (
            <p className="summary-empty">No stays match the current filter.</p>
          ) : null}
        </div>

        {totalResults > 0 && (
          <div className="table-pagination">
            <div className="pagination-info">
              Showing <strong>{((currentPage - 1) * pageSize) + 1}</strong> to <strong>{Math.min(currentPage * pageSize, totalResults)}</strong> of <strong>{totalResults}</strong> stays
            </div>
            <div className="pagination-controls">
              <div className="page-size-selector">
                <label>Rows per page:</label>
                <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>
                  <option value={10}>10</option>
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </div>
              <button 
                className="pag-btn" 
                disabled={currentPage === 1} 
                onClick={() => setCurrentPage(prev => prev - 1)}
              >
                Previous
              </button>
              <span className="page-num">Page <strong>{currentPage}</strong> of {totalPages}</span>
              <button 
                className="pag-btn" 
                disabled={currentPage === totalPages} 
                onClick={() => setCurrentPage(prev => prev + 1)}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
};

export default SummaryView;
