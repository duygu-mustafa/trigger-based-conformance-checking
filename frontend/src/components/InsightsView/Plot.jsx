import React from 'react';
import Plotly from 'plotly.js-basic-dist-min';
import createPlotlyComponent from 'react-plotly.js/factory';

const PlotlyChart = createPlotlyComponent(Plotly);

export const INK = '#64748b';
export const GRID = '#e2e8f0';

const BASE_LAYOUT = {
  font: {
    family: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    size: 12,
    color: INK,
  },
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  margin: { t: 16, r: 16, b: 56, l: 56 },
  hoverlabel: {
    bgcolor: '#ffffff',
    bordercolor: '#cbd5e1',
    font: { color: '#1e293b', size: 12 },
    align: 'left',
  },
};

const CONFIG = {
  responsive: true,
  displaylogo: false,
  modeBarButtonsToRemove: [
    'select2d', 'lasso2d', 'autoScale2d', 'zoomIn2d', 'zoomOut2d', 'resetScale2d',
  ],
  toImageButtonOptions: { format: 'png', scale: 2 },
};

/* Shared Plotly wrapper: fluid width, fixed pixel height, common styling. */
export default function Plot({ data, layout, height = 300, onClick, onLegendClick, onLegendDoubleClick }) {
  return (
    <PlotlyChart
      onClick={onClick}
      onLegendClick={onLegendClick}
      onLegendDoubleClick={onLegendDoubleClick}
      data={data}
      layout={{
        ...BASE_LAYOUT,
        ...layout,
        font: { ...BASE_LAYOUT.font, ...layout?.font },
        margin: { ...BASE_LAYOUT.margin, ...layout?.margin },
        hoverlabel: { ...BASE_LAYOUT.hoverlabel, ...layout?.hoverlabel },
        autosize: true,
      }}
      config={CONFIG}
      useResizeHandler
      style={{ width: '100%', height }}
    />
  );
}
