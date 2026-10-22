import React, { Suspense, lazy } from 'react';
import { count, formatP, pct } from './charts';
import { ruleLabel } from '../../ruleNames';

// Charts used by the defense story and the rule drill-down. Same styling as
// charts.jsx; Plotly stays lazy.
const Plot = lazy(() => import('./Plot'));
const PlotFallback = <div className="insight-chart-loading">Loading chart…</div>;

const GRID = '#e2e8f0';
const PRIMARY = '#1976d2';
const VIOLATION = '#c62828';
const NEUTRAL = '#546e7a';
const INVERTED = '#e65100';

/* ── Thesis cause palette ────────────────────────────────────────
   Same colours as the step-08 figures, so the app matches the thesis. */
export const CAUSE_COLORS = {
  satisfied: '#2e7d32',
  undocumented: '#9ecae1',
  no_payload: '#3182bd',
  partial_payload: '#08519c',
  unmet: '#d62728',
};

const ciText = (rr, lo, hi, digits = 2) =>
  `${Number(rr || 0).toFixed(digits)} [${Number(lo || 0).toFixed(digits)}, ${Number(hi || 0).toFixed(digits)}]`;

const rrClass = (rr, significant) => {
  if (!significant) return 'ns';
  return rr < 1 ? 'protective' : 'inverted';
};

function Lazy({ data, layout, height, onClick, onLegendClick, onLegendDoubleClick }) {
  return (
    <div className="insight-chart" style={{ minHeight: height }}>
      <Suspense fallback={PlotFallback}>
        <Plot data={data} layout={layout} height={height} onClick={onClick}
              onLegendClick={onLegendClick} onLegendDoubleClick={onLegendDoubleClick} />
      </Suspense>
    </div>
  );
}

/* Shared forest plot: one row per estimate, log x-axis, null line at RR 1. */
function Forest({ rows, height, xTitle, legend = true }) {
  const classes = [
    { key: 'protective', name: 'Violation → lower success', color: PRIMARY },
    { key: 'inverted', name: 'Violation → higher success', color: INVERTED },
    { key: 'ns', name: 'Not significant', color: '#b0bec5' },
  ];
  const ids = rows.map((r) => r.id);
  const data = classes.map((c) => {
    const sub = rows.filter((r) => r.cls === c.key);
    return {
      type: 'scatter',
      mode: 'markers',
      name: c.name,
      x: sub.map((r) => r.rr),
      y: sub.map((r) => r.id),
      marker: {
        color: c.color,
        size: sub.map((r) => r.size || 10),
        symbol: sub.map((r) => r.symbol || 'circle'),
        line: { color: '#fff', width: 1 },
      },
      error_x: {
        type: 'data',
        symmetric: false,
        array: sub.map((r) => Math.max(0, r.hi - r.rr)),
        arrayminus: sub.map((r) => Math.max(0, r.rr - r.lo)),
        color: c.color,
        thickness: 1.6,
        width: 0,
      },
      customdata: sub.map((r) => r.hover),
      hovertemplate: '%{customdata}<extra></extra>',
      showlegend: legend && sub.length > 0,
    };
  });

  const bounds = rows.flatMap((r) => [r.lo, r.hi]).filter((v) => v > 0);
  const lo = Math.min(0.5, ...bounds) * 0.95;
  const hi = Math.max(1.5, ...bounds) * 1.05;
  const ticks = [0.2, 0.3, 0.4, 0.5, 0.67, 0.8, 1, 1.25, 1.5, 2, 3].filter((t) => t >= lo && t <= hi);

  const layout = {
    height,
    margin: { t: 8, b: legend ? 78 : 48, l: 150, r: 16 },
    xaxis: {
      type: 'log',
      range: [Math.log10(lo), Math.log10(hi)],
      tickvals: ticks,
      ticktext: ticks.map(String),
      title: { text: xTitle, standoff: 6 },
      gridcolor: GRID,
      zeroline: false,
      fixedrange: true,
    },
    yaxis: {
      type: 'category',
      categoryorder: 'array',
      categoryarray: ids,
      autorange: 'reversed',
      tickvals: ids,
      ticktext: rows.map((r) => r.tick || r.id),
      automargin: true,
      fixedrange: true,
    },
    shapes: [{
      type: 'line', xref: 'x', x0: 1, x1: 1, yref: 'paper', y0: 0, y1: 1,
      line: { color: NEUTRAL, width: 1.2, dash: 'dash' },
    }],
    legend: { orientation: 'h', yref: 'container', y: 0, yanchor: 'bottom', x: 0 },
    showlegend: legend,
  };

  return <Lazy data={data} layout={layout} height={height} />;
}

/* ── Outcome association forest ──────────────────────────────────
   Risk ratio of SBT success when the rule is violated vs not (activations
   only, Fisher, Bonferroni). Diamonds are scored on the next episode. */
export function RiskRatioForest({ association, hideIds = [], measure = 'rr' }) {
  const name = measure === 'or' ? 'Odds ratio' : 'Risk ratio';
  const short = measure === 'or' ? 'OR' : 'RR';
  // Keep the RR ordering for both measures so the rows do not jump on toggle.
  const rows = (association || [])
    .filter((r) => !r.degenerate_estimate && !hideIds.includes(r.constraint_id) && r[measure] > 0)
    .slice()
    .sort((a, b) => a.rr - b.rr)
    .map((r) => ({
      id: r.constraint_id,
      tick: r.constraint_id.startsWith('RC-DP') ? `<b>${ruleLabel(r.constraint_id)}</b>` : ruleLabel(r.constraint_id),
      rr: r[measure],
      lo: r[`${measure}_ci_low`],
      hi: r[`${measure}_ci_high`],
      cls: rrClass(r[measure], r.significant_bonferroni),
      symbol: r.reference === 'next' ? 'diamond' : 'circle',
      hover:
        `<b>${r.constraint_id}</b> ${r.label}<br>` +
        `RR ${ciText(r.rr, r.rr_ci_low, r.rr_ci_high, 3)}<br>` +
        (r.or !== undefined ? `OR ${ciText(r.or, r.or_ci_low, r.or_ci_high, 3)}<br>` : '') +
        `violated ${count(r.n_exposed)} · not violated ${count(r.n_unexposed)}<br>` +
        `outcome: ${r.reference === 'next' ? 'next episode' : 'same episode'}<br>` +
        `p (Bonferroni, ${r.n_tests} tests) = ${formatP(r.p_bonferroni)}`,
    }));
  if (!rows.length) return <p className="summary-empty">No association table available.</p>;
  return (
    <Forest rows={rows} height={100 + rows.length * 24}
            xTitle={`${name} (${short}) of SBT success, violated vs not (log scale)`} />
  );
}

/* ── Outcome association, readiness split by cause ───────────────
   Readiness rules get two rows: violations where the criterion was assessed
   and not met, and violations that are documentation gaps. The other rules
   have no data condition on their target, so a violation is a missing action
   and keeps its single estimate. Colour = kind of violation, fill = significant
   after Bonferroni, diamond = next-episode outcome. Each readiness rule also
   shows its pooled (uncorrected) estimate in purple, significance as in step 04.
   Every legend entry filters: the arms, and also the not-significant and
   next-episode markers, which cut across the arms. Hidden rows leave the axis. */
const NOT_SIGNIFICANT = 'ns';
const NEXT_EPISODE = 'next';
export const FAMILY_ORDER = ['Readiness assessment', 'SBT execution', 'Failure correction'];
export const ARMS = {
  unmet: { name: 'Assessed, not met', short: 'not met', color: CAUSE_COLORS.unmet },
  documentation: { name: 'Documentation gap', short: 'documentation gap', color: CAUSE_COLORS.no_payload },
  missing_action: { name: 'Missing action (no data condition)', short: '', color: '#37474f' },
  pooled: { name: 'All violations pooled (uncorrected)', short: 'all violations', color: '#7b3fa0' },
};
const ARM_ORDER = { unmet: 0, documentation: 1, missing_action: 2 };

/* Split rows in display order: by family, then rule by headline estimate, then arm. */
export function orderSplitRows(rows, groups, measure = 'rr') {
  const headline = {};
  rows.forEach((r) => {
    const cur = headline[r.constraint_id];
    if (!cur || ARM_ORDER[r.arm] < ARM_ORDER[cur.arm]) headline[r.constraint_id] = r;
  });
  const fam = (r) => FAMILY_ORDER.indexOf(groups?.[r.constraint_id]);
  return rows.slice().sort((a, b) => fam(a) - fam(b)
    || headline[a.constraint_id][measure] - headline[b.constraint_id][measure]
    || a.constraint_id.localeCompare(b.constraint_id)
    || ARM_ORDER[a.arm] - ARM_ORDER[b.arm]);
}

export function SplitRiskRatioForest({ rows: input, groups, hideIds = [], measure = 'rr' }) {
  const [hidden, setHidden] = React.useState(() => new Set());
  const name = measure === 'or' ? 'Odds ratio' : 'Risk ratio';
  const short = measure === 'or' ? 'OR' : 'RR';
  const ordered = orderSplitRows(
    (input || []).filter((r) => !r.degenerate_estimate && !hideIds.includes(r.constraint_id) && r[measure] > 0),
    groups, measure,
  );
  // A pooled row on top of each readiness rule, built from the columns its arms carry.
  const allRows = ordered.flatMap((r, i) => {
    const own = { ...r, id: `${r.constraint_id}·${r.arm}` };
    if (!(r.pooled_rr > 0) || (i > 0 && ordered[i - 1].constraint_id === r.constraint_id)) return [own];
    return [{
      ...r,
      id: `${r.constraint_id}·pooled`,
      arm: 'pooled',
      rr: r.pooled_rr,
      rr_ci_low: r.pooled_rr_ci_low,
      rr_ci_high: r.pooled_rr_ci_high,
      or: r.pooled_or,
      or_ci_low: r.pooled_or_ci_low,
      or_ci_high: r.pooled_or_ci_high,
      significant_bonferroni: r.pooled_significant_bonferroni,
    }, own];
  });
  if (!allRows.length) return <p className="summary-empty">No association table available.</p>;
  const rows = allRows.filter((r) => !hidden.has(r.arm)
    && !(hidden.has(NOT_SIGNIFICANT) && !r.significant_bonferroni)
    && !(hidden.has(NEXT_EPISODE) && r.reference === 'next'));
  const shown = (key) => (hidden.has(key) ? 'legendonly' : true);
  const onLegendClick = (e) => {
    const key = e.data[e.curveNumber]?.meta;
    if (key) {
      setHidden((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key); else next.add(key);
        return next;
      });
    }
    return false;
  };

  // Category axis: a header row per family, then the rule rows.
  const ids = [];
  const ticktext = [];
  rows.forEach((r, i) => {
    const family = groups?.[r.constraint_id] || 'Other';
    if (i === 0 || (groups?.[rows[i - 1].constraint_id] || 'Other') !== family) {
      ids.push(`§${family}`);
      ticktext.push(`<span style="color:${NEUTRAL}"><b>${family.toUpperCase()}</b></span>`);
    }
    const first = i === 0 || rows[i - 1].constraint_id !== r.constraint_id;
    const armText = ARMS[r.arm].short;
    ids.push(r.id);
    ticktext.push(first
      ? `<b>${ruleLabel(r.constraint_id)}</b>${armText ? `  ${armText}` : ''}`
      : armText);
  });

  const hover = (r) => {
    if (r.arm === 'pooled') {
      return `<b>${r.constraint_id}</b> ${r.label}<br>` +
        `<i>${ARMS.pooled.name}</i><br>` +
        `RR ${ciText(r.rr, r.rr_ci_low, r.rr_ci_high, 3)}<br>` +
        `OR ${ciText(r.or, r.or_ci_low, r.or_ci_high, 3)}<br>` +
        'the estimate before splitting by cause<br>' +
        `significant (Bonferroni, per-rule tests): ${r.significant_bonferroni ? 'yes' : 'no'}`;
    }
    const pooled = r.pooled_rr !== null && r.pooled_rr !== undefined
      ? `pooled, all violations: RR ${ciText(r.pooled_rr, r.pooled_rr_ci_low, r.pooled_rr_ci_high, 3)}<br>`
      : '';
    return `<b>${r.constraint_id}</b> ${r.label}<br>` +
      `<i>${ARMS[r.arm].name}</i><br>` +
      `RR ${ciText(r.rr, r.rr_ci_low, r.rr_ci_high, 3)}<br>` +
      `OR ${ciText(r.or, r.or_ci_low, r.or_ci_high, 3)}<br>` +
      pooled +
      `violated ${count(r.n_exposed)} · satisfied ${count(r.n_unexposed)}<br>` +
      `outcome: ${r.reference === 'next' ? 'next episode' : 'same episode'}<br>` +
      `p (Bonferroni, ${r.n_tests} tests) = ${formatP(r.p_bonferroni)}`;
  };

  const symbol = (r) => `${r.reference === 'next' ? 'diamond' : 'circle'}${r.significant_bonferroni ? '' : '-open'}`;
  const data = Object.entries(ARMS).map(([key, arm]) => {
    const sub = rows.filter((r) => r.arm === key);
    return {
      type: 'scatter',
      mode: 'markers',
      name: arm.name,
      meta: key,
      visible: shown(key),
      x: sub.map((r) => r[measure]),
      y: sub.map((r) => r.id),
      marker: {
        color: arm.color,
        size: 10,
        symbol: sub.map(symbol),
        line: { color: arm.color, width: 2 },
      },
      error_x: {
        type: 'data',
        symmetric: false,
        array: sub.map((r) => Math.max(0, r[`${measure}_ci_high`] - r[measure])),
        arrayminus: sub.map((r) => Math.max(0, r[measure] - r[`${measure}_ci_low`])),
        color: arm.color,
        thickness: 1.8,
        width: 0,
      },
      customdata: sub.map(hover),
      hovertemplate: '%{customdata}<extra></extra>',
      showlegend: allRows.some((r) => r.arm === key),
    };
  });
  // Invisible points so the family header rows exist on the category axis.
  const headers = ids.filter((id) => id.startsWith('§'));
  data.push({
    type: 'scatter', mode: 'markers', x: headers.map(() => 1), y: headers,
    marker: { opacity: 0 }, hoverinfo: 'skip', showlegend: false,
  });
  data.push({
    type: 'scatter', mode: 'markers', x: [null], y: [null],
    name: 'Hollow: not significant (Bonferroni)',
    meta: NOT_SIGNIFICANT,
    visible: shown(NOT_SIGNIFICANT),
    marker: { color: NEUTRAL, size: 10, symbol: 'circle-open', line: { color: NEUTRAL, width: 2 } },
    hoverinfo: 'skip',
  });
  data.push({
    type: 'scatter', mode: 'markers', x: [null], y: [null],
    name: 'Diamond: next-episode outcome',
    meta: NEXT_EPISODE,
    visible: shown(NEXT_EPISODE),
    marker: { color: NEUTRAL, size: 10, symbol: 'diamond' },
    hoverinfo: 'skip',
  });

  // Alternate shading per rule inside the readiness family, where rules span two rows.
  const shapes = [];
  let band = 0;
  rows.forEach((r, i) => {
    if (r.arm === 'missing_action' || (i > 0 && rows[i - 1].constraint_id === r.constraint_id)) return;
    const last = rows.slice(i).findIndex((x) => x.constraint_id !== r.constraint_id);
    const end = last === -1 ? rows.length - 1 : i + last - 1;
    if (band++ % 2 === 0) {
      shapes.push({
        type: 'rect', xref: 'paper', x0: 0, x1: 1, yref: 'y',
        y0: ids.indexOf(r.id) - 0.5, y1: ids.indexOf(rows[end].id) + 0.5,
        fillcolor: 'rgba(13, 60, 110, 0.05)', line: { width: 0 }, layer: 'below',
      });
    }
  });
  shapes.push({
    type: 'line', xref: 'x', x0: 1, x1: 1, yref: 'paper', y0: 0, y1: 1,
    line: { color: NEUTRAL, width: 1.2, dash: 'dash' },
  });

  const bounds = rows.flatMap((r) => [r[`${measure}_ci_low`], r[`${measure}_ci_high`]]).filter((v) => v > 0);
  const lo = Math.min(0.5, ...bounds) * 0.95;
  const hi = Math.max(1.5, ...bounds) * 1.05;
  const ticks = [0.2, 0.3, 0.4, 0.5, 0.67, 0.8, 1, 1.25, 1.5, 2, 3].filter((t) => t >= lo && t <= hi);
  const height = 130 + ids.length * 24;
  const layout = {
    height,
    margin: { t: 8, b: 104, l: 150, r: 16 },
    xaxis: {
      type: 'log',
      range: [Math.log10(lo), Math.log10(hi)],
      tickvals: ticks,
      ticktext: ticks.map(String),
      title: { text: `${name} (${short}) of SBT success, violated vs satisfied (log scale)`, standoff: 6 },
      gridcolor: GRID,
      zeroline: false,
      fixedrange: true,
    },
    yaxis: {
      type: 'category', categoryorder: 'array', categoryarray: ids, autorange: 'reversed',
      tickvals: ids, ticktext, automargin: true, fixedrange: true,
    },
    shapes,
    legend: { orientation: 'h', yref: 'container', y: 0, yanchor: 'bottom', x: 0 },
  };
  return <Lazy data={data} layout={layout} height={height}
               onLegendClick={onLegendClick} onLegendDoubleClick={() => false} />;
}

/* ── Generic satisfied-vs-violated histogram ─────────────────────
   Bins come pre-computed from step 10 (frequency_detail.json). */
export function PairHistogram({ hist, xTitle, violatedLabel = 'Violated', height = 250 }) {
  if (!hist?.edges?.length) return null;
  const { edges } = hist;
  const centers = edges.slice(0, -1).map((e, i) => (e + edges[i + 1]) / 2);
  const width = edges[1] - edges[0];
  const bars = (key, name, color, n) => ({
    type: 'bar',
    name: `${name} (n=${count(n)})`,
    x: centers,
    y: hist[key],
    width,
    marker: { color, line: { width: 0 } },
    opacity: 0.7,
    hovertemplate: `${name}: %{y:,} episodes<br>≈ %{x:.3~g}<extra></extra>`,
  });
  const data = [];
  if (hist.n_satisfied) data.push(bars('satisfied', 'Satisfied', CAUSE_COLORS.satisfied, hist.n_satisfied));
  if (hist.n_violated) data.push(bars('violated', violatedLabel, CAUSE_COLORS.unmet, hist.n_violated));
  const t = hist.threshold;
  const hasT = t !== null && t !== undefined;
  const layout = {
    height,
    barmode: 'overlay',
    bargap: 0,
    margin: { t: 22, b: 84, l: 56, r: 16 },
    xaxis: { title: { text: xTitle, standoff: 6 }, gridcolor: GRID, fixedrange: true },
    yaxis: { title: { text: 'Episodes' }, gridcolor: GRID, fixedrange: true },
    shapes: hasT ? [{
      type: 'line', xref: 'x', x0: t, x1: t, yref: 'paper', y0: 0, y1: 1,
      line: { color: '#0f1f2e', width: 1.5, dash: 'dash' },
    }] : [],
    annotations: hasT ? [{
      xref: 'x', x: t, yref: 'paper', y: 1, yanchor: 'bottom', showarrow: false,
      text: `threshold ${t}`, font: { size: 11, color: '#0f1f2e' },
    }] : [],
    legend: { orientation: 'h', yref: 'container', y: 0, yanchor: 'bottom', x: 0 },
  };
  return <Lazy data={data} layout={layout} height={height} />;
}

/* ── Margin tertiles ─────────────────────────────────────────────
   Unmet readings split by how far they miss the threshold; each tertile is
   compared with the satisfied episodes of the same rule. */
const STRATUM_ORDER = { near: 0, moderate: 1, gross: 2 };
// Sequential reds: the further the reading misses, the darker the marker.
const STRATA = [
  { key: 'near', name: 'Near miss', color: '#f08a6c' },
  { key: 'moderate', name: 'Moderate miss', color: '#d62728' },
  { key: 'gross', name: 'Gross miss', color: '#7f0000' },
];

export function MarginTertileForest({ strata, constraintIds }) {
  const rows = (strata || [])
    .filter((r) => !constraintIds || constraintIds.includes(r.constraint_id))
    .slice()
    .sort((a, b) => a.constraint_id.localeCompare(b.constraint_id)
      || STRATUM_ORDER[a.stratum] - STRATUM_ORDER[b.stratum])
    .map((r) => ({
      ...r,
      id: `${r.constraint_id} · ${r.stratum}`,
      significant: r.rr_ci_high < 1 || r.rr_ci_low > 1,
      hover:
        `<b>${r.constraint_id}</b> — ${r.stratum} miss<br>` +
        `margin ${r.margin_min} … ${r.margin_max} (median value ${r.value_median})<br>` +
        `n = ${count(r.n_violated)} · success ${pct(r.success_rate)} vs ${pct(r.reference_success_rate)}<br>` +
        `RR ${ciText(r.rr_point, r.rr_ci_low, r.rr_ci_high, 3)} · p = ${formatP(r.p_raw)}`,
    }));
  if (!rows.length) return <p className="summary-empty">No margin strata available.</p>;

  const ids = rows.map((r) => r.id);
  // Rule label only on the first row of its group; the other rows show the stratum.
  const ticktext = rows.map((r, i) => (i === 0 || rows[i - 1].constraint_id !== r.constraint_id
    ? `<b>${ruleLabel(r.constraint_id)}</b>  ${r.stratum}`
    : r.stratum));

  const data = STRATA.map((s) => {
    const sub = rows.filter((r) => r.stratum === s.key);
    return {
      type: 'scatter',
      mode: 'markers',
      name: s.name,
      x: sub.map((r) => r.rr_point),
      y: sub.map((r) => r.id),
      marker: {
        color: s.color,
        size: 10,
        symbol: sub.map((r) => (r.significant ? 'circle' : 'circle-open')),
        line: { color: s.color, width: 2 },
      },
      error_x: {
        type: 'data',
        symmetric: false,
        array: sub.map((r) => Math.max(0, r.rr_ci_high - r.rr_point)),
        arrayminus: sub.map((r) => Math.max(0, r.rr_point - r.rr_ci_low)),
        color: s.color,
        thickness: 1.8,
        width: 0,
      },
      customdata: sub.map((r) => r.hover),
      hovertemplate: '%{customdata}<extra></extra>',
      showlegend: sub.length > 0,
    };
  });
  // Legend-only entry explaining the hollow markers.
  data.push({
    type: 'scatter', mode: 'markers', x: [null], y: [null],
    name: 'Hollow: CI includes 1',
    marker: { color: NEUTRAL, size: 10, symbol: 'circle-open', line: { color: NEUTRAL, width: 2 } },
    hoverinfo: 'skip',
  });

  // One band per rule (alternating shade) plus a line between rules.
  const groups = [];
  rows.forEach((r, i) => {
    const last = groups[groups.length - 1];
    if (last && last.cid === r.constraint_id) last.end = i;
    else groups.push({ cid: r.constraint_id, start: i, end: i });
  });
  const shapes = [
    ...groups.flatMap((g, gi) => [
      ...(gi % 2 === 0 ? [{
        type: 'rect', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: g.start - 0.5, y1: g.end + 0.5,
        fillcolor: 'rgba(13, 60, 110, 0.05)', line: { width: 0 }, layer: 'below',
      }] : []),
      ...(gi > 0 ? [{
        type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: g.start - 0.5, y1: g.start - 0.5,
        line: { color: '#90a4ae', width: 1 },
      }] : []),
    ]),
    {
      type: 'line', xref: 'x', x0: 1, x1: 1, yref: 'paper', y0: 0, y1: 1,
      line: { color: NEUTRAL, width: 1.2, dash: 'dash' },
    },
  ];

  const bounds = rows.flatMap((r) => [r.rr_ci_low, r.rr_ci_high]).filter((v) => v > 0);
  const lo = Math.min(0.5, ...bounds) * 0.95;
  const hi = Math.max(1.5, ...bounds) * 1.05;
  const ticks = [0.2, 0.3, 0.4, 0.5, 0.67, 0.8, 1, 1.25, 1.5, 2, 3].filter((t) => t >= lo && t <= hi);
  const height = 100 + rows.length * 24;
  const layout = {
    height,
    margin: { t: 8, b: 78, l: 150, r: 16 },
    xaxis: {
      type: 'log',
      range: [Math.log10(lo), Math.log10(hi)],
      tickvals: ticks,
      ticktext: ticks.map(String),
      title: { text: 'Risk ratio of SBT success vs satisfied (log scale)', standoff: 6 },
      gridcolor: GRID,
      zeroline: false,
      fixedrange: true,
    },
    yaxis: {
      type: 'category', categoryorder: 'array', categoryarray: ids, autorange: 'reversed',
      tickvals: ids, ticktext, automargin: true, fixedrange: true,
    },
    shapes,
    legend: { orientation: 'h', yref: 'container', y: 0, yanchor: 'bottom', x: 0 },
  };
  return <Lazy data={data} layout={layout} height={height} />;
}

/* ── Segmentation ablation ───────────────────────────────────────
   Per constraint, the stays whose verdict changes when the whole stay is
   evaluated as one trace: masked = violated per episode, hidden per stay;
   invented = violated only per stay. */
export function AblationBars({ ablation, limit = 10 }) {
  const rows = (ablation?.per_constraint || [])
    .filter((r) => !r.not_comparable && (r.disagreement || 0) > 0)
    .slice()
    .sort((a, b) => (b.disagreement || 0) - (a.disagreement || 0))
    .slice(0, limit);
  if (!rows.length) return <p className="summary-empty">No ablation table available.</p>;

  const ids = rows.map((r) => r.constraint_id);
  const series = [
    { key: 'masked_stays', name: 'Masked: episode violation hidden in the stay trace', color: VIOLATION },
    { key: 'trace_only_stays', name: 'Invented: violation only in the stay trace', color: '#b07d00' },
  ];
  const data = series.map((s) => ({
    type: 'bar',
    orientation: 'h',
    name: s.name,
    x: rows.map((r) => r[s.key] || 0),
    y: ids,
    marker: { color: s.color },
    customdata: rows.map((r) => `<b>${r.constraint_id}</b> ${r.label}<br>` +
      `flagged per episode ${count(r.stays_flagged_episode_level)} · per stay ${count(r.stays_flagged_trace_level)}`),
    hovertemplate: `%{customdata}<br>${s.name.split(':')[0]}: %{x:,} stays<extra></extra>`,
  }));
  const height = 110 + rows.length * 26;
  const layout = {
    height,
    barmode: 'stack',
    margin: { t: 8, b: 90, l: 130, r: 16 },
    xaxis: {
      title: { text: `Stays with a changed verdict (of ${count(ablation.n_stays_compared)})`, standoff: 6 },
      gridcolor: GRID,
      fixedrange: true,
    },
    yaxis: {
      type: 'category', categoryorder: 'array', categoryarray: ids, autorange: 'reversed', fixedrange: true,
      tickvals: ids, ticktext: ids.map(ruleLabel), automargin: true,
    },
    legend: { orientation: 'h', yref: 'container', y: 0, yanchor: 'bottom', x: 0 },
  };
  return <Lazy data={data} layout={layout} height={height} />;
}

/* ── Activation vs violation rate ────────────────────────────────
   One bar per rule on a common denominator (all episodes): the bar length is
   the activation rate, split into violated and satisfied activations. The
   conditional violation rate is printed at the end of the bar. */
export function ActivationViolationBars({ frequency, selectedId, onSelect }) {
  const rows = (frequency || [])
    .slice()
    .sort((a, b) => (b.violation_rate_activated || 0) - (a.violation_rate_activated || 0));
  if (!rows.length) return <p className="summary-empty">No frequency table available.</p>;
  const ids = rows.map((r) => r.constraint_id);
  const violatedShare = (r) => (r.activation_rate || 0) * (r.violation_rate_activated || 0);
  const series = [
    { name: 'Activated, violated', color: VIOLATION, x: violatedShare },
    { name: 'Activated, satisfied', color: '#90caf9', x: (r) => (r.activation_rate || 0) - violatedShare(r) },
  ];
  const data = series.map((s) => ({
    type: 'bar',
    orientation: 'h',
    name: s.name,
    x: rows.map(s.x),
    y: ids,
    marker: { color: s.color },
    customdata: rows.map((r) => `<b>${r.constraint_id}</b> ${r.label}<br>` +
      `activated in ${pct(r.activation_rate)} of episodes · violated in ${pct(r.violation_rate_activated)} of activations<br>` +
      `activated ${count(r.n_activated)} · violated ${count(r.n_violated)} · vacuous ${count(r.n_vacuous)}`),
    hovertemplate: `%{customdata}<br>${s.name}: %{x:.1%} of all episodes<extra></extra>`,
  }));
  const annotations = rows.map((r) => ({
    x: r.activation_rate || 0, y: r.constraint_id, xref: 'x', yref: 'y',
    text: `${pct(r.violation_rate_activated, 0)} of activations`,
    xanchor: 'left', xshift: 4, showarrow: false,
    font: { size: 11, color: NEUTRAL },
  }));
  const height = 110 + rows.length * 26;
  const layout = {
    height,
    barmode: 'stack',
    bargap: 0.3,
    margin: { t: 8, b: 80, l: 130, r: 110 },
    annotations,
    xaxis: {
      tickformat: '.0%', range: [0, 1], gridcolor: GRID, fixedrange: true,
      title: { text: 'Share of all episodes', font: { size: 12 } },
    },
    yaxis: {
      type: 'category', categoryorder: 'array', categoryarray: ids, autorange: 'reversed', fixedrange: true,
      tickvals: ids,
      ticktext: ids.map((cid) => (cid === selectedId ? `<b>▸ ${ruleLabel(cid)}</b>` : ruleLabel(cid))),
      automargin: true,
    },
    shapes: selectedId && ids.includes(selectedId) ? [{
      type: 'rect', xref: 'paper', x0: 0, x1: 1, yref: 'y',
      y0: ids.indexOf(selectedId) - 0.5, y1: ids.indexOf(selectedId) + 0.5,
      fillcolor: 'rgba(13, 60, 110, 0.08)', line: { width: 0 }, layer: 'below',
    }] : [],
    legend: { orientation: 'h', yref: 'container', y: 0, yanchor: 'bottom', x: 0 },
  };
  const handleClick = onSelect
    ? (e) => { const cid = e?.points?.[0]?.y; if (cid) onSelect(cid); }
    : undefined;
  return <Lazy data={data} layout={layout} height={height} onClick={handleClick} />;
}

/* ── Episodes per stay ───────────────────────────────────────────── */
export function EpisodesPerStayBars({ rows }) {
  if (!rows?.length) return <p className="summary-empty">No episode counts available.</p>;
  const max = Math.max(...rows.map((r) => r.share_of_stays || 0)) || 1;
  return (
    <div className="insight-rowlist">
      {rows.map((row) => (
        <div key={row.label} className="insight-row compact">
          <div className="insight-row-head">
            <span className="insight-row-label">
              {row.label} {row.label === '1' ? 'episode' : 'episodes'}
            </span>
            <span className="insight-row-meta">{count(row.n_stays)} stays</span>
          </div>
          <div className="insight-track">
            <div className="insight-track-fill"
                 style={{ width: `${((row.share_of_stays || 0) / max) * 100}%`,
                          background: row.label === '1' ? '#b0bec5' : PRIMARY }} />
            <span className="insight-track-value">{pct(row.share_of_stays)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Value distribution: satisfied vs unmet ──────────────────────
   Pre-binned in step 10 (1st–99th percentile); the dashed line is the
   criterion threshold. */
export function ValueHistogram({ histogram, height = 280 }) {
  if (!histogram?.edges?.length) return null;
  const { edges } = histogram;
  const centers = edges.slice(0, -1).map((e, i) => (e + edges[i + 1]) / 2);
  const width = edges[1] - edges[0];
  const bars = (key, name, color) => ({
    type: 'bar',
    name,
    x: centers,
    y: histogram[key],
    width,
    marker: { color, line: { width: 0 } },
    opacity: 0.7,
    hovertemplate: `${name.split(' (')[0]}: %{y:,} episodes<br>value ≈ %{x:.3~g}<extra></extra>`,
  });
  const data = [
    bars('satisfied', `Satisfied (n=${count(histogram.n_satisfied_with_reading)})`, CAUSE_COLORS.satisfied),
    bars('unmet', `Assessed & not met (n=${count(histogram.n_unmet_with_reading)})`, CAUSE_COLORS.unmet),
  ];
  const t = histogram.threshold;
  const hasT = t !== null && t !== undefined;
  const layout = {
    height,
    barmode: 'overlay',
    bargap: 0,
    margin: { t: 22, b: 84, l: 56, r: 16 },
    xaxis: { title: { text: histogram.unit || 'value', standoff: 6 }, gridcolor: GRID, fixedrange: true },
    yaxis: { title: { text: 'Episodes' }, gridcolor: GRID, fixedrange: true },
    shapes: hasT ? [{
      type: 'line', xref: 'x', x0: t, x1: t, yref: 'paper', y0: 0, y1: 1,
      line: { color: '#0f1f2e', width: 1.5, dash: 'dash' },
    }] : [],
    annotations: hasT ? [{
      xref: 'x', x: t, yref: 'paper', y: 1, yanchor: 'bottom', showarrow: false,
      text: `threshold ${t}`, font: { size: 11, color: '#0f1f2e' },
    }] : [],
    legend: { orientation: 'h', yref: 'container', y: 0, yanchor: 'bottom', x: 0 },
  };
  return <Lazy data={data} layout={layout} height={height} />;
}
