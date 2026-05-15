import clockIcon from '../../static/clock.svg';
import dataIcon from '../../static/data.svg';
import controlFlowIcon from '../../static/control_flow.svg';

export const formatPercent = (ratio) => `${(Number(ratio || 0) * 100).toFixed(1)}%`;

export const getConstraintIcon = (id) => {
  if (id.includes('-TM-')) return clockIcon;
  if (id.includes('-DP-')) return dataIcon;
  if (id.includes('-CF-') || id.includes('COMPOSITE')) return controlFlowIcon;
  return null;
};
