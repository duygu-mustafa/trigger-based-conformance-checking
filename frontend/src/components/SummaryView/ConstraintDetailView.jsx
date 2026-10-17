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
  
  const deltasV = forensicsV.delta_distributions || {};
  const deltasS = forensicsS.delta_distributions || {};
  
  const allDelaysHours = useMemo(() => [...delaysV, ...delaysS].map(d => d / 3600), [delaysV, delaysS]);
  
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
            <label>Odds Ratio [95% CI]</label>
            <span className={`val ${constraint.is_significant ? 'text-danger' : ''}`}>
              {constraint.odds_ratio === null ? 'N/A' : `${constraint.odds_ratio.toFixed(2)} [${(constraint.odds_ratio_low ?? 0).toFixed(2)} – ${(constraint.odds_ratio_high ?? 0).toFixed(2)}]`}
            </span>
          </div>
        )}
        {constraint.p_value_raw !== undefined && (
          <div className="detail-stat">
            <label>p-value</label>
            <span className={`val ${constraint.is_significant ? 'text-danger' : ''}`}>
              {constraint.p_value_raw === null ? 'N/A' : (constraint.p_value_raw < 0.001 ? '<0.001' : constraint.p_value_raw.toFixed(3))}
            </span>
          </div>
        )}
        {constraint.p_value_raw !== undefined && constraint.rule_class && (
          <div className="detail-stat">
            <label>Classification</label>
            <span className={`stat-sig-label ${constraint.rule_class}`}>
              {constraint.rule_class === 'useful' ? 'Useful' : constraint.rule_class === 'harmful' ? 'Harmful' : 'Not Significant'}
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

        {allDeltaKeys
          .filter(key => !['ventilation_duration_hours', 'hours_since_intubation', 'sbt_duration_min', 'gap_hours', 'hours_since_stay_start'].includes(key))
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
