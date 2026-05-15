import React from 'react';
import { getConstraintIcon, formatPercent } from './utils';

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

export default MiniBarChart;
