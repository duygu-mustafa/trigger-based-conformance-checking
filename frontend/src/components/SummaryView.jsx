import React, { useMemo, useState } from 'react';

const formatPercent = (ratio) => `${(Number(ratio || 0) * 100).toFixed(1)}%`;

const MiniBarChart = ({ title, items, emptyMessage, toneClass = '' }) => {
  if (!items || items.length === 0) {
    return (
      <section className={`summary-card ${toneClass}`}>
        <h3>{title}</h3>
        <p className="summary-empty">{emptyMessage}</p>
      </section>
    );
  }

  const maxCount = Math.max(...items.map(item => item.count), 1);

  return (
    <section className={`summary-card ${toneClass}`}>
      <h3>{title}</h3>
      <div className="bar-list">
        {items.map((item) => (
          <div key={item.constraint_id} className="bar-row">
            <div className="bar-row-header">
              <span className="bar-label">{item.constraint_label || item.constraint_id}</span>
              <span className="bar-value">{item.count}</span>
            </div>
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: `${(item.count / maxCount) * 100}%` }}
                title={`${item.constraint_id}: ${item.count}`}
              />
            </div>
            <div className="bar-meta">
              <span>{item.constraint_id}</span>
              <span>Episodes: {formatPercent(item.episode_share)}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};

const SummaryView = ({ summaryData, onSelectStay }) => {
  const [query, setQuery] = useState('');
  const [sortBy, setSortBy] = useState('total_mandatory_violations');

  const topViolations = useMemo(
    () => (summaryData?.violation_frequency || []).slice(0, 10),
    [summaryData]
  );

  const topReadinessBottlenecks = useMemo(
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
          <h3>Avg Violations (Success)</h3>
          <p className="metric-value">{Number(successStats.avg_mandatory_violations || 0).toFixed(2)}</p>
          <p className="metric-subtext">n={successStats.episodes || 0}</p>
        </section>
        <section className="summary-card metric-card">
          <h3>Avg Violations (Failure)</h3>
          <p className="metric-value">{Number(failureStats.avg_mandatory_violations || 0).toFixed(2)}</p>
          <p className="metric-subtext">n={failureStats.episodes || 0}</p>
        </section>
      </div>

      <div className="summary-charts-grid">
        <MiniBarChart
          title="Most Frequent Violations"
          items={topViolations}
          emptyMessage="No violation data found."
          toneClass="chart-violations"
        />
        <MiniBarChart
          title="Readiness Check Bottlenecks"
          items={topReadinessBottlenecks}
          emptyMessage="No readiness bottlenecks found."
          toneClass="chart-readiness"
        />
      </div>

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
