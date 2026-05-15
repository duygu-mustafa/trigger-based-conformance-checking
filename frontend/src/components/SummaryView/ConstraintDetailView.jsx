import React, { useMemo } from 'react';
import Histogram from './Histogram';
import { formatPercent } from './utils';

const ConstraintDetailView = ({ constraint, itemLabels = {} }) => {
  if (!constraint) return (
    <div className="detail-empty">
      <p>Select a constraint to view violation details</p>
    </div>
  );

  const forensicsV = constraint.forensics?.violation || constraint.forensics || {};
  const forensicsS = constraint.forensics?.satisfaction || {};
  
  const delaysV = forensicsV.delays || [];
  const delaysS = forensicsS.delays || [];
  
  const outcomesV = forensicsV.delay_outcomes || [];
  const outcomesS = forensicsS.delay_outcomes || [];
  
  const deltasV = forensicsV.delta_distributions || {};
  const deltasS = forensicsS.delta_distributions || {};
  
  const allDelaysHours = useMemo(() => [...delaysV, ...delaysS].map(d => d / 3600), [delaysV, delaysS]);
  
  const isTimingConstraint = constraint.constraint_id === 'RC-TM-03';
  
  const timingStats = useMemo(() => {
    if (!isTimingConstraint || (delaysV.length === 0 && delaysS.length === 0)) return null;
    
    const combinedData = [];
    delaysV.forEach((d, i) => combinedData.push({ h: d / 3600, outcome: outcomesV[i] }));
    delaysS.forEach((d, i) => combinedData.push({ h: d / 3600, outcome: outcomesS[i] }));

    const getStats = (subset, totalCount) => {
      if (subset.length === 0) return { count: 0, pct: 0, successPct: 0 };
      const successCount = subset.filter(p => p.outcome?.toLowerCase().includes('success')).length;
      return {
        count: subset.length,
        pct: (subset.length / totalCount) * 100,
        successPct: (successCount / subset.length) * 100
      };
    };

    const tooEarly = combinedData.filter(p => p.h < 48);
    const tooLate = combinedData.filter(p => p.h > 72);
    const onTime = combinedData.filter(p => p.h >= 48 && p.h <= 72);
    const total = combinedData.length;
    
    return {
      tooEarly: getStats(tooEarly, total),
      tooLate: getStats(tooLate, total),
      onTime: getStats(onTime, total)
    };
  }, [isTimingConstraint, delaysV, outcomesV, delaysS, outcomesS]);

  const allDeltaKeys = Array.from(new Set([...Object.keys(deltasV), ...Object.keys(deltasS)]));
  
  const inferThresholds = (key, c) => {
    const expr = c.activation_condition || c.target_condition || '';
    if (!expr) return { min: null, max: null, inverted: false };
    
    const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp(`(?:items\\s*\\[\\s*['"]?${escapedKey}['"]?\\s*\\]|\\b${escapedKey}\\b)\\s*(>=|>|<=|<)\\s*([0-9.]+)`, 'gi');
    
    let minThresh = null;
    let maxThresh = null;
    let match;
    while ((match = pattern.exec(expr)) !== null) {
      const op = match[1];
      const val = parseFloat(match[2]);
      if (op === '>=' || op === '>') minThresh = val;
      else if (op === '<=' || op === '<') maxThresh = val;
    }
    
    const lowerExpr = expr.trim().toLowerCase();
    const isInverted = lowerExpr.includes('violation') || lowerExpr.includes('avoid');
    
    return { min: minThresh, max: maxThresh, inverted: isInverted };
  };

  return (
    <div className="forensics-detail-content">
      <div className="detail-header">
        <div className="header-top" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div className="id-tag">{constraint.constraint_id}</div>
          <span className="template-badge">{constraint.template}</span>
        </div>
        <h4>{constraint.constraint_label}</h4>
        {constraint.rationale && <p className="rationale-text">{constraint.rationale}</p>}
      </div>
      
      <div className="detail-stats-grid">
        <div className="detail-stat">
          <label>Total Violations</label>
          <span className="val">{constraint.count}</span>
        </div>
        <div className="detail-stat">
          <label>Affected Episodes</label>
          <span className="val">{formatPercent(constraint.episode_share || 0)}</span>
        </div>
        <div className="detail-stat">
          <label>Failure Lift</label>
          <span className={`val ${constraint.lift_failure > 1.2 ? 'text-danger' : ''}`}>
            {(constraint.lift_failure || 1).toFixed(2)}x
          </span>
        </div>
        {constraint.odds_ratio !== undefined && (
          <div className="detail-stat">
            <label>Odds Ratio</label>
            <span className={`val ${constraint.is_significant ? 'text-danger' : ''}`}>
              {constraint.odds_ratio === null ? 'N/A' : constraint.odds_ratio.toFixed(2)}
            </span>
          </div>
        )}
        {constraint.p_value_fdr !== undefined && (
          <div className="detail-stat">
            <label>p-value (FDR)</label>
            <span className={`val ${constraint.is_significant ? 'text-danger' : ''}`}>
              {constraint.p_value_fdr === null ? 'N/A' : (constraint.p_value_fdr < 0.001 ? '<0.001' : constraint.p_value_fdr.toFixed(3))}
            </span>
          </div>
        )}
      </div>

      <div className="forensics-charts">
        <Histogram 
          data={allDelaysHours} 
          title="Timing Distribution (All Episodes)" 
          unit="h" 
          color="#64748b"
          expectedMin={constraint.min_gap_hours}
          expectedMax={constraint.max_gap_hours}
        />

        {timingStats && (
          <div className="timing-breakdown-card">
            <label>Clinical Timing Breakdown</label>
            <div className="breakdown-summary">
              Total Evaluated Episodes: <strong>{timingStats.tooEarly.count + timingStats.onTime.count + timingStats.tooLate.count}</strong>
            </div>
            <div className="breakdown-bar">
              <div className="segment early" style={{ width: `${(timingStats.tooEarly.pct || 0)}%` }} title={`Too Early: ${timingStats.tooEarly.count} episodes`}>
                {timingStats.tooEarly.pct > 5 && <span>{(timingStats.tooEarly.pct || 0).toFixed(0)}%</span>}
              </div>
              <div className="segment on-time" style={{ width: `${(timingStats.onTime.pct || 0)}%` }} title={`On Time: ${timingStats.onTime.count} episodes`}>
                {timingStats.onTime.pct > 5 && <span>{(timingStats.onTime.pct || 0).toFixed(0)}%</span>}
              </div>
              <div className="segment late" style={{ width: `${(timingStats.tooLate.pct || 0)}%` }} title={`Too Late: ${timingStats.tooLate.count} episodes`}>
                {timingStats.tooLate.pct > 5 && <span>{(timingStats.tooLate.pct || 0).toFixed(0)}%</span>}
              </div>
            </div>
            <div className="breakdown-legend">
              <div className="legend-item">
                <span className="dot early"></span> Too Early (&lt;48h): <strong>{timingStats.tooEarly.count}</strong> ({(timingStats.tooEarly.pct || 0).toFixed(1)}%)
                <span className="outcome-link">{(timingStats.tooEarly.successPct || 0).toFixed(0)}% success</span>
              </div>
              <div className="legend-item">
                <span className="dot on-time"></span> On Time (48-72h): <strong>{timingStats.onTime.count}</strong> ({(timingStats.onTime.pct || 0).toFixed(1)}%)
                <span className="outcome-link">{(timingStats.onTime.successPct || 0).toFixed(0)}% success</span>
              </div>
              <div className="legend-item">
                <span className="dot late"></span> Too Late (&gt;72h): <strong>{timingStats.tooLate.count}</strong> ({(timingStats.tooLate.pct || 0).toFixed(1)}%)
                <span className="outcome-link">{(timingStats.tooLate.successPct || 0).toFixed(0)}% success</span>
              </div>
            </div>
          </div>
        )}
        
        {allDeltaKeys
          .filter(key => !['ventilation_duration_hours', 'hours_since_intubation', 'sbt_duration_min', 'gap_hours'].includes(key))
          .map((key) => {
            const thresh = inferThresholds(key, constraint);
            let combinedData = [...(deltasV[key] || []), ...(deltasS[key] || [])];
            
            if (key.toLowerCase().includes('fio2')) {
              combinedData = combinedData.map(v => (v > 0 && v <= 1) ? v * 100 : v);
            }

            return (
              <Histogram 
                key={key} 
                data={combinedData} 
                title={`Value Distribution: ${itemLabels[key] || key}`} 
                unit="" 
                color="#64748b"
                expectedMin={thresh.min}
                expectedMax={thresh.max}
                inverted={thresh.inverted}
              />
            );
          })}

        {delaysV.length === 0 && allDeltaKeys.length === 0 && (
          <div className="no-data-notice">
             <p>No magnitude forensics available for this constraint.</p>
             <p className="subtext">This can happen if the rule is Boolean (e.g., "Medication Present") or if the trace contains no numeric data for the relevant variables.</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default ConstraintDetailView;
