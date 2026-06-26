import React, { useMemo, useState } from 'react';

const StatsDeepDive = ({ summaryData }) => {
  const [onlySignificant, setOnlySignificant] = useState(false);
  const [classFilter, setClassFilter] = useState(null);

  const formatPValue = (value) => {
    if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
    return value < 0.001 ? '<0.001' : value.toFixed(3);
  };

  const formatEstimate = (value) => {
    if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
    return value.toFixed(2);
  };

  const formatCount = (value) => {
    if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
    return Number(value).toFixed(0);
  };

  const classCounts = useMemo(() => {
    const raw = (summaryData?.violation_frequency || []).filter(v => v.count > 0 && v.odds_ratio !== undefined);
    const counts = { useful: 0, harmful: 0, neutral: 0 };
    raw.forEach(v => { counts[v.rule_class] = (counts[v.rule_class] || 0) + 1; });
    return counts;
  }, [summaryData]);

  const statsData = useMemo(() => {
    const raw = (summaryData?.violation_frequency || [])
      .filter(v => v.count > 0 && v.odds_ratio !== undefined);

    const sorted = [...raw].sort((a, b) => {
      const pa = a.p_value_raw ?? 1;
      const pb = b.p_value_raw ?? 1;
      if (pa !== pb) return pa - pb;
      const getAbsLogOR = (or) => Math.abs(Math.log(or || 1));
      return getAbsLogOR(b.odds_ratio) - getAbsLogOR(a.odds_ratio);
    });

    let filtered = sorted;
    if (onlySignificant) {
      filtered = filtered.filter(s => s.is_significant);
    }
    if (classFilter) {
      filtered = filtered.filter(s => s.rule_class === classFilter);
    }
    return filtered;
  }, [summaryData, onlySignificant, classFilter]);

  if (!statsData.length) return <p className="summary-empty">No statistical data available.</p>;

  const handleClassFilter = (cls) => {
    setClassFilter(classFilter === cls ? null : cls);
  };

  return (
    <div className="stats-deep-dive">
      <div className="class-summary-banner">
        {['useful', 'harmful', 'neutral'].map(cls => (
          <button
            key={cls}
            className={`class-pill class-${cls} ${classFilter === cls ? 'active' : ''}`}
            onClick={() => handleClassFilter(cls)}
          >
            <span className="class-dot" /> {cls.charAt(0).toUpperCase() + cls.slice(1)}: {classCounts[cls] || 0}
          </button>
        ))}
      </div>

      <div className="stats-controls">
        <label className="checkbox-label">
          <input 
            type="checkbox" 
            checked={onlySignificant} 
            onChange={(e) => setOnlySignificant(e.target.checked)} 
          />
          Show only statistically significant (p &lt; 0.05)
        </label>
      </div>

      <div className="summary-table-wrapper">
        <table className="summary-table stats-table">
          <thead>
            <tr>
              <th>Clinical Rule</th>
              <th title="Number of exposed (violated) episodes">Exposed (Violated) #</th>
              <th title="Number of unexposed episodes">Unexposed (Satisfied) #</th>
              <th title="Odds Ratio with 95% confidence interval">OR [95% CI]</th>
              <th title="Risk Ratio with 95% confidence interval">RR [95% CI]</th>
              <th>p-value</th>
              <th>Clinical Relevance</th>
            </tr>
          </thead>
          <tbody>
            {statsData.map((item) => {
              const or = item.odds_ratio;
              const orLow = item.odds_ratio_low;
              const orHigh = item.odds_ratio_high;
              const rr = item.risk_ratio;
              const rrLow = item.rr_ci_low;
              const rrHigh = item.rr_ci_high;

              let badge = { label: "Not Significant", class: "neutral" };
              if (item.rule_class === "useful") {
                badge = { label: "Useful", class: "useful" };
              } else if (item.rule_class === "harmful") {
                badge = { label: "Harmful", class: "harmful" };
              }

              const rowClass = item.rule_class === "useful" ? 'row-useful'
                : item.rule_class === "harmful" ? 'row-harmful'
                : '';

              return (
                <tr key={item.constraint_id} className={rowClass}>
                  <td>
                    <div className="rule-cell">
                      <span className="id-badge">{item.constraint_id}</span>{' '}
                      <span className="rule-label">{item.constraint_label}</span>
                    </div>
                  </td>
                  <td className="val-cell">{formatCount(item.n_exposed)}</td>
                  <td className="val-cell">{formatCount(item.n_unexposed)}</td>
                  <td className="val-cell">
                    <strong>{formatEstimate(or)}</strong>
                    <div className="rr-ci">[{formatEstimate(orLow)} – {formatEstimate(orHigh)}]</div>
                  </td>
                  <td className="val-cell">
                    {rr === null || isNaN(rr) ? 'N/A' : (
                      <>
                        <strong>{formatEstimate(rr)}</strong>
                        <div className="rr-ci">[{formatEstimate(rrLow)} – {formatEstimate(rrHigh)}]</div>
                      </>
                    )}
                  </td>
                  <td className="val-cell">
                    {formatPValue(item.p_value_raw)}
                  </td>
                  <td>
                    <span className={`stat-sig-label ${badge.class}`}>{badge.label}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default StatsDeepDive;
