import React, { useMemo, useState } from 'react';

const StatsDeepDive = ({ summaryData }) => {
  const [onlySignificant, setOnlySignificant] = useState(false);

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
  
  const statsData = useMemo(() => {
    const raw = (summaryData?.violation_frequency || [])
      .filter(v => v.count > 0 && v.odds_ratio !== undefined);
    
    const sorted = [...raw].sort((a, b) => {
      // Sort by significance (p-value) first
      if (a.p_value_fdr !== b.p_value_fdr) {
        return (a.p_value_fdr ?? 1) - (b.p_value_fdr ?? 1);
      }
      // Then by magnitude of association (abs log OR)
      const getAbsLogOR = (or) => Math.abs(Math.log(or || 1));
      return getAbsLogOR(b.odds_ratio) - getAbsLogOR(a.odds_ratio);
    });

    if (onlySignificant) {
      return sorted.filter(s => s.is_significant);
    }
    return sorted;
  }, [summaryData, onlySignificant]);

  if (!statsData.length) return <p className="summary-empty">No statistical data available.</p>;

  return (
    <div className="stats-deep-dive">
      <div className="stats-controls">
        <label className="checkbox-label">
          <input 
            type="checkbox" 
            checked={onlySignificant} 
            onChange={(e) => setOnlySignificant(e.target.checked)} 
          />
          Show only statistically significant associations (p &lt; 0.05)
        </label>
      </div>

      <div className="summary-table-wrapper">
        <table className="summary-table stats-table">
          <thead>
            <tr>
              <th>Clinical Rule</th>
              <th>Compliance Pattern</th>
              <th title="Number of exposed episodes from the CSV">Exposed n</th>
              <th title="Number of unexposed episodes from the CSV">Unexposed n</th>
              <th title="Odds Ratio: >1 means association with Failure">OR [95% CI]</th>
              <th title="Relative Risk: >1 means association with Failure">RR [95% CI]</th>
              <th>p-value (Raw)</th>
              <th>p-value (Bonf.)</th>
              <th>p-value (FDR)</th>
              <th>Interpretation</th>
            </tr>
          </thead>
          <tbody>
            {statsData.map((item) => {
              const pValFdr = item.p_value_fdr;
              const pValRaw = item.p_value_raw;
              const pValBonf = item.p_value_bonf;
              const or = item.odds_ratio;
              const orLow = item.odds_ratio_low;
              const orHigh = item.odds_ratio_high;
              const rr = item.risk_ratio;
              const rrLow = item.rr_ci_low;
              const rrHigh = item.rr_ci_high;
              const isSignificant = item.is_significant;
              const isBonfSignificant = item.is_significant_bonf;
              const isNominal = pValRaw < 0.05 && !isSignificant;
              
              // Determine clinical meaning
              let interpretation = "Neutral / Not Significant";
              let interpClass = "";
              
              const constraintId = String(item.constraint_id || '');
              const isSafetyRule = constraintId.startsWith('SBT-DP-') || constraintId.startsWith('INT-');
              const isAdherenceRule = constraintId.startsWith('RC-DP-');
              
              if (isSignificant) {
                if (isAdherenceRule) {
                  // Compliance = Good
                  if (or > 1.1) {
                    interpretation = "Significant Protective Factor";
                    interpClass = "stat-sig-label protective";
                  } else if (or < 0.9) {
                    interpretation = "Compliance associated with Failure";
                    interpClass = "stat-sig-label risk";
                  }
                } else if (isSafetyRule) {
                  // Violation = Bad
                  if (or < 0.9) {
                    interpretation = "Significant Risk Factor";
                    interpClass = "stat-sig-label risk";
                  } else if (or > 1.1) {
                    interpretation = "Violation associated with Success";
                    interpClass = "stat-sig-label protective";
                  }
                } else {
                   interpretation = "Significant Association";
                   interpClass = "stat-sig-label neutral";
                }
              } else if (isNominal) {
                interpretation = "Nominal Trend (p < 0.05)";
                interpClass = "stat-sig-label neutral";
              }

              if (isBonfSignificant && !isSignificant) {
                interpretation = "Bonferroni Significant";
                interpClass = "stat-sig-label neutral";
              }

              const rowClass = isSignificant ? 'row-significant' : (isNominal ? 'row-nominal' : '');

              return (
                <tr key={item.constraint_id} className={rowClass}>
                  <td>
                    <div className="rule-cell">
                      <span className="id-badge">{item.constraint_id}</span>
                      <span className="rule-label">{item.constraint_label}</span>
                    </div>
                  </td>
                  <td>{item.template}</td>
                  <td className="val-cell">{formatCount(item.n_exposed)}</td>
                  <td className="val-cell">{formatCount(item.n_unexposed)}</td>
                  <td className="val-cell">
                    <strong>{formatEstimate(or)}</strong>
                    <div className="rr-ci">[{formatEstimate(orLow)} - {formatEstimate(orHigh)}]</div>
                  </td>
                  <td className="val-cell">
                    {rr === null || isNaN(rr) ? 'N/A' : (
                      <div className="rr-group">
                        <span className="rr-val">{formatEstimate(rr)}</span>
                        <span className="rr-ci">[{formatEstimate(rrLow)} - {formatEstimate(rrHigh)}]</span>
                      </div>
                    )}
                  </td>
                  <td className={`stat-p-val ${isNominal ? 'text-accent bold' : ''}`}>
                    {formatPValue(pValRaw)}
                  </td>
                  <td className={isBonfSignificant ? 'bold text-accent' : ''}>
                    {formatPValue(pValBonf)}
                  </td>
                  <td className={isSignificant ? 'bold text-accent' : ''}>
                    {formatPValue(pValFdr)}
                  </td>
                  <td>
                    <span className={interpClass}>{interpretation}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="stats-footer">
        <p className="footer-note">* <strong>FDR p-value</strong>: Corrected for multiple testing (Benjamini-Hochberg). This is the main significance filter in the table.</p>
        <p className="footer-note">* <strong>Raw p-value</strong>: Fisher's exact test result from the CSV export. Values &lt; 0.05 with no FDR significance are shown as nominal trends.</p>
        <p className="footer-note">* <strong>Bonferroni p-value</strong>: Additional conservative correction from the same CSV export for reference.</p>
      </div>
    </div>
  );
};

export default StatsDeepDive;
