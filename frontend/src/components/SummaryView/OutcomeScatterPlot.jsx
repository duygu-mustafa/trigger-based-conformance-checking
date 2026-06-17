import React from 'react';

const formatPercent = (ratio) => `${(Number(ratio || 0) * 100).toFixed(1)}%`;

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
        <g transform={`translate(${margin.left}, ${margin.top})`}>
          <rect width={plotW} height={plotH} fill="#f8fafc" />
          <line x1={0} y1={plotH} x2={plotW} y2={plotH} stroke="#cbd5e1" strokeWidth="1" />
          <line x1={0} y1={0} x2={0} y2={plotH} stroke="#cbd5e1" strokeWidth="1" />
          
          <line x1={0} y1={plotH} x2={plotW} y2={0} stroke="#e2e8f0" strokeWidth="1" strokeDasharray="4" />
          
          {[0, 0.25, 0.5, 0.75, 1].map(v => (
            <React.Fragment key={v}>
              <text x={getX(v)} y={plotH + 15} textAnchor="middle" fontSize="10" fill="#94a3b8">{v * 100}%</text>
              <text x={-5} y={getY(v)} textAnchor="end" fontSize="10" fill="#94a3b8" alignmentBaseline="middle">{v * 100}%</text>
            </React.Fragment>
          ))}

          {items.filter(item => isViolation ? (item.count_success + item.count_failure) > 0 : true).map((item) => {
            const xVal = isViolation ? item.violation_rate_success : item.satisfaction_rate_success;
            const yVal = isViolation ? item.violation_rate_failure : item.satisfaction_rate_failure;
            const lift = isViolation ? item.lift_failure : item.lift_success;
            
            const x = getX(xVal || 0);
            const y = getY(yVal || 0);

            let color = '#94a3b8';
            if (item.rule_class === 'useful') color = '#22c55e';
            else if (item.rule_class === 'harmful') color = '#ef4444';

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
                  <title>{`${item.constraint_label} [${item.rule_class === 'useful' ? 'Useful' : item.rule_class === 'harmful' ? 'Harmful' : 'Not Significant'}]\nSuccess ${isViolation ? 'Violation' : 'Satisfaction'}: ${formatPercent(xVal)}\nFailure ${isViolation ? 'Violation' : 'Satisfaction'}: ${formatPercent(yVal)}\n${isViolation ? 'Failure Lift' : 'Success Lift'}: ${(lift || 1).toFixed(2)}x`}</title>
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

export default OutcomeScatterPlot;
