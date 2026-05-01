import React, { useMemo, useState } from 'react';
import clockIcon from '../static/clock.svg';
import dataIcon from '../static/data.svg';
import controlFlowIcon from '../static/control_flow.svg';

const formatPercent = (ratio) => `${(Number(ratio || 0) * 100).toFixed(1)}%`;

const getConstraintIcon = (id) => {
  if (id.includes('-TM-')) return clockIcon;
  if (id.includes('-DP-')) return dataIcon;
  if (id.includes('-CF-') || id.includes('COMPOSITE')) return controlFlowIcon;
  return null;
};

const MiniBarChart = ({ items, emptyMessage, getValue, getPercentage, toneClass = '', subtitle }) => {
  if (!items || items.length === 0) {
    return (
      <div className="bar-list">
        <p className="summary-empty">{emptyMessage}</p>
      </div>
    );
  }

  const maxPercent = Math.max(...items.map(item => getPercentage(item)), 0.01);

  return (
    <div className="bar-list">
      {subtitle && <p className="chart-subtitle">{subtitle}</p>}
      {items.map((item) => {
        const icon = getConstraintIcon(item.constraint_id);
        const percent = getPercentage(item);
        const valueDisplay = getValue(item);

        return (
          <div key={item.constraint_id} className="bar-row">
            <div className="bar-row-header">
              <div className="icon-label-wrapper">
                {icon && <img src={icon} alt="" className="constraint-icon" />}
                <span className="bar-label" title={item.constraint_label}>{item.constraint_label || item.constraint_id}</span>
              </div>
              <span className="bar-value">{valueDisplay}</span>
            </div>
            <div className="bar-track">
              <div
                className={`bar-fill ${toneClass}`}
                style={{ width: `${(percent / maxPercent) * 100}%` }}
                title={`${item.constraint_id}: ${item.count} (${formatPercent(percent)})`}
              />
            </div>
            <div className="bar-meta">
              <span>{item.constraint_id}</span>
              <span>Total: {item.count}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
};

const ContrastBarChart = ({ items, emptyMessage, mode = 'violation' }) => {
  if (!items || items.length === 0) {
    return (
      <div className="bar-list">
        <p className="summary-empty">{emptyMessage}</p>
      </div>
    );
  }

  const isViolation = mode === 'violation';

  return (
    <div className="contrast-list">
      {items.map((item) => {
        const icon = getConstraintIcon(item.constraint_id);
        
        // Rates depend on mode but order is now always Success then Failure
        const rateSuccess = isViolation ? (item.violation_rate_success ?? 0) : (item.satisfaction_rate_success ?? 0);
        const rateFailure = isViolation ? (item.violation_rate_failure ?? 0) : (item.satisfaction_rate_failure ?? 0);
        const lift = isViolation ? (item.lift_failure ?? 1) : (item.lift_success ?? 1);

        const colorSuccess = isViolation ? 'success-fill' : 'success-fill'; // Both green in their context
        const colorFailure = isViolation ? 'failure-fill' : 'failure-fill';

        return (
          <div key={item.constraint_id} className="contrast-row">
            <div className="contrast-info">
              <div className="icon-label-wrapper">
                {icon && <img src={icon} alt="" className="constraint-icon" />}
                <span className="bar-label" title={item.constraint_label}>{item.constraint_label}</span>
              </div>
              <div className="lift-metrics">
                <div className={`lift-tag ${isViolation ? (lift > 1.2 ? 'high-lift' : lift < 0.8 ? 'low-lift' : '') : (lift > 1.2 ? 'high-success-lift' : lift < 0.8 ? 'low-success-lift' : '')}`}>
                  {isViolation ? 'Failure Lift' : 'Success Lift'}: {lift.toFixed(2)}x
                </div>
              </div>
            </div>
            
            <div className="dual-track">
              <div className="track-layer">
                <div 
                  className={`track-fill success-fill`} 
                  style={{ width: `${rateSuccess * 100}%` }}
                />
                <span className="track-text">Success: {formatPercent(rateSuccess)}</span>
              </div>
              <div className="track-layer">
                <div 
                  className={`track-fill failure-fill`} 
                  style={{ width: `${rateFailure * 100}%` }}
                />
                <span className="track-text">Failure: {formatPercent(rateFailure)}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

const OutcomeScatterPlot = ({ items, mode = 'violation' }) => {
  if (!items || items.length === 0) return <p className="summary-empty">No data available for plot.</p>;

  const margin = { top: 20, right: 20, bottom: 40, left: 40 };
  const width = 400;
  const height = 400;
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;

  const getX = (val) => (val * plotW);
  const getY = (val) => (plotH - (val * plotH));

  const isViolation = mode === 'violation';

  return (
    <div className="scatter-plot-container">
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="scatter-plot-svg">
        {/* Grid and Axes */}
        <g transform={`translate(${margin.left}, ${margin.top})`}>
          <rect width={plotW} height={plotH} fill="#f8fafc" />
          <line x1={0} y1={plotH} x2={plotW} y2={plotH} stroke="#cbd5e1" strokeWidth="1" />
          <line x1={0} y1={0} x2={0} y2={plotH} stroke="#cbd5e1" strokeWidth="1" />
          
          {/* Diagonal Guideline */}
          <line x1={0} y1={plotH} x2={plotW} y2={0} stroke="#e2e8f0" strokeWidth="1" strokeDasharray="4" />
          
          {/* Axis Labels */}
          {[0, 0.25, 0.5, 0.75, 1].map(v => (
            <React.Fragment key={v}>
              <text x={getX(v)} y={plotH + 15} textAnchor="middle" fontSize="10" fill="#94a3b8">{v * 100}%</text>
              <text x={-5} y={getY(v)} textAnchor="end" fontSize="10" fill="#94a3b8" alignmentBaseline="middle">{v * 100}%</text>
            </React.Fragment>
          ))}

          {/* Dots */}
          {items.filter(item => isViolation ? (item.count_success + item.count_failure) > 0 : true).map((item) => {
            const xVal = isViolation ? item.violation_rate_success : item.satisfaction_rate_success;
            const yVal = isViolation ? item.violation_rate_failure : item.satisfaction_rate_failure;
            const lift = isViolation ? item.lift_failure : item.lift_success;
            
            const x = getX(xVal || 0);
            const y = getY(yVal || 0);
            
            const color = lift > 1.2 ? (isViolation ? '#ef4444' : '#10b981') 
                        : lift < 0.8 ? (isViolation ? '#10b981' : '#ef4444') 
                        : '#64748b';

            return (
              <circle
                key={item.constraint_id}
                cx={x}
                cy={y}
                r="6"
                fill={color}
                stroke="#fff"
                strokeWidth="1.5"
                className="scatter-dot"
              >
                <title>{`${item.constraint_label}\nSuccess ${isViolation ? 'Violation' : 'Satisfaction'}: ${formatPercent(xVal)}\nFailure ${isViolation ? 'Violation' : 'Satisfaction'}: ${formatPercent(yVal)}\n${isViolation ? 'Failure Lift' : 'Success Lift'}: ${lift.toFixed(2)}x`}</title>
              </circle>
            );
          })}
        </g>
        <text x={width / 2 + 10} y={height - 5} textAnchor="middle" fontSize="12" fontWeight="600" fill="#64748b">{isViolation ? 'Violation Rate (Success)' : 'Satisfaction Rate (Success)'}</text>
        <text x={10} y={height / 2} textAnchor="middle" fontSize="12" fontWeight="600" fill="#64748b" transform={`rotate(-90, 10, ${height/2})`}>{isViolation ? 'Violation Rate (Failure)' : 'Satisfaction Rate (Failure)'}</text>
      </svg>
    </div>
  );
};

const SummaryView = ({ summaryData, onSelectStay }) => {
  const [query, setQuery] = useState('');
  const [sortBy, setSortBy] = useState('total_mandatory_violations');
  const [analysisMode, setAnalysisMode] = useState('violation'); // 'violation' or 'satisfaction'

  const topViolations = useMemo(
    () => (summaryData?.violation_frequency || []).slice(0, 7),
    [summaryData]
  );

  const allCorrelationData = useMemo(() => {
    const data = [...(summaryData?.violation_frequency || [])];
    const isViolation = analysisMode === 'violation';

    return data.sort((a, b) => {
        // Push constraints with NO data in current mode to bottom
        const aCount = isViolation ? (a.count_success + a.count_failure) : (a.count_satisfied);
        const bCount = isViolation ? (b.count_success + b.count_failure) : (b.count_satisfied);
        
        if (aCount === 0 && bCount > 0) return 1;
        if (bCount === 0 && aCount > 0) return -1;

        // Sort by significance (distance from Lift 1.0)
        const liftA = isViolation ? (a.lift_failure || 1) : (a.lift_success || 1);
        const liftB = isViolation ? (b.lift_failure || 1) : (b.lift_success || 1);

        return Math.abs(liftB - 1) - Math.abs(liftA - 1);
      });
  }, [summaryData, analysisMode]);

  const topUnmetReadinessCriteria = useMemo(
    () => (summaryData?.readiness_bottlenecks || []).slice(0, 7),
    [summaryData]
  );

  const stayRows = useMemo(() => {
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

  const outcomeStats = summaryData?.conformance_vs_outcome || {};
  const successStats = outcomeStats.success || {};
  const failureStats = outcomeStats.failure || {};

  return (
    <div className="summary-view">
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

      <div className="summary-charts-grid">
        <div className="chart-card">
          <div className="section-header">
            <h3>Top Violated Constraints</h3>
          </div>
          <MiniBarChart
            items={topViolations}
            emptyMessage="No violation data found."
            toneClass="chart-violations"
            getValue={(v) => formatPercent(v.episode_share)}
            getPercentage={(v) => v.episode_share}
          />
        </div>
        <div className="chart-card">
          <div className="section-header">
            <h3>Unmet Readiness Criteria</h3>
          </div>
          <MiniBarChart
            items={topUnmetReadinessCriteria}
            emptyMessage="No unmet criteria found."
            toneClass="chart-readiness"
            subtitle="Criteria blocking SBT start"
            getValue={(v) => formatPercent(v.episode_share)}
            getPercentage={(v) => v.episode_share}
          />
        </div>
      </div>

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
      </section>
    </div>
  );
};

export default SummaryView;
