import React from 'react';
import { getConstraintIcon, formatPercent } from './utils';

const ContrastBarChart = ({ items, mode = 'violation' }) => {
  if (!items || items.length === 0) {
    return (
      <div className="bar-list">
        <p className="summary-empty">No constraints have data for this mode.</p>
      </div>
    );
  }

  const isViolation = mode === 'violation';

  const classLabel = (rc) => {
    if (rc === 'useful') return { text: 'Useful', cls: 'class-useful' };
    if (rc === 'harmful') return { text: 'Harmful', cls: 'class-harmful' };
    return { text: 'Not Significant', cls: 'class-neutral' };
  };

  return (
    <div className="contrast-list">
      <div className="contrast-legend">
        <div className="legend-item"><span className="swatch success"></span> Successful Trials</div>
        <div className="legend-item"><span className="swatch failure"></span> Failed Trials</div>
        <div className="legend-hint">Length = % of that group {isViolation ? 'violating' : 'satisfying'} the rule</div>
      </div>
      
      {items.map((item) => {
        const icon = getConstraintIcon(item.constraint_id);
        const rateSuccess = isViolation ? (item.violation_rate_success ?? 0) : (item.satisfaction_rate_success ?? 0);
        const rateFailure = isViolation ? (item.violation_rate_failure ?? 0) : (item.satisfaction_rate_failure ?? 0);
        const lift = isViolation ? (item.lift_failure ?? 1) : (item.lift_success ?? 1);
        const delta = Math.abs(rateFailure - rateSuccess);
        const cl = classLabel(item.rule_class);

        const liftClass = isViolation 
          ? (lift > 1.2 ? 'high-lift' : lift < 0.8 ? 'low-lift' : '')
          : (lift > 1.2 ? 'high-success-lift' : lift < 0.8 ? 'low-success-lift' : '');

        return (
          <div key={item.constraint_id} className="contrast-row">
            <div className="contrast-info">
              <div className="icon-label-wrapper">
                {icon && <img src={icon} alt="" className="constraint-icon" />}
                <span className="bar-label" title={item.constraint_label}>{item.constraint_label}</span>
              </div>
              <div className="lift-metrics">
                <div className={`lift-tag ${liftClass}`}>
                   {isViolation ? 'Failure Lift' : 'Success Lift'}: <strong>{(lift || 1).toFixed(2)}x</strong>
                </div>
                 <div className="delta-tag">
                    {delta > 0.01 && <span className="delta-val">Δ {formatPercent(delta)}</span>}
                 </div>
                 <span className={`class-tag ${cl.cls}`}>{cl.text}</span>
              </div>
            </div>
            
            <div className="dual-track-container">
              <div className="dual-track">
                <div className="track-grid">
                  {[0, 25, 50, 75, 100].map(v => <div key={v} className="grid-line" style={{ left: `${v}%` }}><span>{v}%</span></div>)}
                </div>
                
                <div className="track-layer">
                  <div 
                    className="track-fill success-fill" 
                    style={{ width: `${rateSuccess * 100}%` }}
                  >
                    <span className={`rate-label ${rateSuccess < 0.2 ? 'is-low' : ''}`}>Success: {formatPercent(rateSuccess)}</span>
                  </div>
                </div>
                <div className="track-layer">
                  <div 
                    className="track-fill failure-fill" 
                    style={{ width: `${rateFailure * 100}%` }}
                  >
                    <span className={`rate-label ${rateFailure < 0.2 ? 'is-low' : ''}`}>Failure: {formatPercent(rateFailure)}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default ContrastBarChart;
