import clockIcon from '../../static/clock.svg';
import dataIcon from '../../static/data.svg';
import controlFlowIcon from '../../static/control_flow.svg';

export const formatPercent = (ratio) => `${(Number(ratio || 0) * 100).toFixed(1)}%`;

export const getConstraintIcon = (id) => {
  if (id.includes('-TM-') || id.includes('-TR-')) return clockIcon;
  if (id.includes('-DP-') || id.includes('-DX-')) return dataIcon;
  if (id.includes('-CF-') || id.includes('COMPOSITE') || id.includes('SEQ')) return controlFlowIcon;
  return null;
};
