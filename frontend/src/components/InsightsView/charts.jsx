import React, { Suspense, lazy } from 'react';
import { ruleLabel } from '../../ruleNames';

// Plotly is large; keep it out of the main bundle until a chart renders.
const Plot = lazy(() => import('./Plot'));
const PlotFallback = <div className="insight-chart-loading">Loading chart…</div>;

export const pct = (ratio, digits = 1) =>
  `${(Number(ratio || 0) * 100).toFixed(digits)}%`;

export const count = (n) => Number(n || 0).toLocaleString();

export const formatP = (p) => {
  if (p === null || p === undefined) return '–';
  if (p === 0) return '< 1e-300';
  if (p < 0.001) return p.toExponential(1);
  return p.toFixed(3);
};

const AXIS = '#94a3b8';
const GRID = '#e2e8f0';
const INK = '#64748b';
const PRIMARY = '#1976d2';
const SUCCESS = '#2e7d32';
const VIOLATION = '#c62828';
const NEUTRAL = '#546e7a';

const SERIES_COLORS = ['#1976d2', '#c62828', '#2e7d32', '#b07d00', '#6a3fa0', '#0f7d8c'];

/* ── Breadth dose-response ───────────────────────────────────────
   Success rate per number of readiness criteria violated. The whiskers are the
   step-09 risk-ratio CI rescaled by the reference rate (RR = rate / reference),
   so they are a CI on the plotted rate, not on the ratio. */
export function DoseResponseChart({ breadth }) {
  const arms = breadth?.arms || [];
  if (!arms.length) return <p className="summary-empty">No breadth arms available.</p>;

  const reference = breadth.reference_success_rate || 0;
  const bars = [
    {
      n_violated: 0,
      n_episodes: breadth.reference_n_episodes,
      success_rate: reference,
      isReference: true,
    },
    ...arms,
  ];

  const rates = bars.map((b) => b.success_rate || 0);
  const lo = bars.map((b) => (b.isReference ? null : (b.rr_ci_low || 0) * reference));
  const hi = bars.map((b) => (b.isReference ? null : (b.rr_ci_high || 0) * reference));

  const trace = {
    type: 'bar',
    x: bars.map((b) => String(b.n_violated)),
    y: rates,
    width: 0.55,
    marker: { color: bars.map((b) => (b.isReference ? '#cbd5e1' : PRIMARY)) },
    text: rates.map((r) => pct(r, 0)),
    textposition: 'outside',
    cliponaxis: false,
    error_y: {
      type: 'data',
      symmetric: false,
      array: hi.map((h, i) => (h === null ? 0 : Math.max(0, h - rates[i]))),
      arrayminus: lo.map((l, i) => (l === null ? 0 : Math.max(0, rates[i] - l))),
      color: INK,
      thickness: 1.2,
      width: 5,
    },
    customdata: bars.map((b) => (b.isReference
      ? `No readiness criterion violated<br>n = ${count(b.n_episodes)}<br>success ${pct(b.success_rate)} (reference arm)`
      : `<b>${b.n_violated} criteria violated</b><br>` +
        `n = ${count(b.n_episodes)} episodes (${pct(b.share)})<br>` +
        `success ${pct(b.success_rate)}<br>` +
        `RR ${(b.rr_point || 0).toFixed(3)} [${(b.rr_ci_low || 0).toFixed(3)}, ${(b.rr_ci_high || 0).toFixed(3)}]<br>` +
        `p = ${formatP(b.p_raw)}`)),
    hovertemplate: '%{customdata}<extra></extra>',
  };

  const layout = {
    height: 320,
    bargap: 0.3,
    margin: { t: 28, b: 64 },
    xaxis: {
      title: { text: 'Readiness criteria violated at SBT start', standoff: 8 },
      tickmode: 'array',
      tickvals: bars.map((b) => String(b.n_violated)),
      ticktext: bars.map((b) => `${b.n_violated}<br><span style="font-size:10px;color:${AXIS}">n=${count(b.n_episodes)}</span>`),
      fixedrange: true,
    },
    yaxis: {
      title: { text: 'SBT success rate' },
      tickformat: '.0%',
      range: [0, 1],
      gridcolor: GRID,
      zeroline: false,
      fixedrange: true,
    },
    shapes: [{
      type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: reference, y1: reference,
      line: { color: NEUTRAL, width: 1.5, dash: 'dash' },
    }],
    annotations: [{
      xref: 'paper', x: 1, xanchor: 'right', yref: 'y', y: reference, yanchor: 'bottom',
      text: `reference ${pct(reference)} (no criterion violated)`,
      showarrow: false, font: { size: 11, color: NEUTRAL },
    }],
    showlegend: false,
  };

  return (
    <div className="insight-chart">
      <Suspense fallback={PlotFallback}>
        <Plot data={[trace]} layout={layout} height={320} />
      </Suspense>
    </div>
  );
}

/* ── Sole-criterion arms ─────────────────────────────────────────
   For episodes that violated exactly one criterion: which one, and how its
   success rate compares to the no-violation reference. */
export function SoleCriterionList({ breadth }) {
  const rows = breadth?.sole_criterion || [];
  const reference = breadth?.reference_success_rate || 0;
  if (!rows.length) return <p className="summary-empty">No single-criterion arms available.</p>;

  return (
    <div className="insight-rowlist">
      {rows.map((row) => {
        const rate = row.success_rate || 0;
        const worse = rate < reference;
        const thin = row.n_episodes < 50;
        return (
          <div key={row.constraint_id} className="insight-row">
            <div className="insight-row-head">
              <span className="insight-row-id">{row.constraint_id}</span>
              <span className="insight-row-label" title={row.label}>{row.label}</span>
              <span className={`insight-chip ${thin ? 'neutral' : worse ? 'bad' : 'good'}`}>
                RR {(row.rr_point || 0).toFixed(2)}
              </span>
            </div>
            <div className="insight-track" title={
              `n = ${count(row.n_episodes)}\nsuccess ${pct(rate)} vs reference ${pct(reference)}\n` +
              `RR ${(row.rr_point || 0).toFixed(3)} [${(row.rr_ci_low || 0).toFixed(3)}, ${(row.rr_ci_high || 0).toFixed(3)}]\n` +
              `p = ${formatP(row.p_raw)}`
            }>
              <div className="insight-track-ref" style={{ left: `${reference * 100}%` }} />
              <div className="insight-track-fill"
                   style={{
                     width: `${rate * 100}%`,
                     background: thin ? NEUTRAL : worse ? VIOLATION : SUCCESS,
                   }} />
              <span className="insight-track-value">{pct(rate)}</span>
            </div>
            <div className="insight-row-meta">
              n = {count(row.n_episodes)}{thin ? ' — too thin to read' : ''} · p = {formatP(row.p_raw)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Violation causes ────────────────────────────────────────────
   Per readiness criterion, the share of its violations that are a missing
   or incomplete reading versus a reading the criterion did not meet. */
const CAUSE_PARTS = [
  { key: 'share_undocumented', label: 'No reading in window', color: '#90a4ae' },
  { key: 'share_partial_payload', label: 'Incomplete reading', color: '#cfd8dc' },
  { key: 'share_unmet', label: 'Criterion genuinely unmet', color: VIOLATION },
];

export function CauseStackedBars({ causes, parts = CAUSE_PARTS }) {
  const rows = causes?.per_constraint || [];
  if (!rows.length) return <p className="summary-empty">No cause breakdown available.</p>;

  return (
    <div className="insight-stacked">
      <div className="insight-legend">
        {parts.map((p) => (
          <span key={p.key} className="insight-legend-item">
            <span className="insight-swatch" style={{ background: p.color }} />
            {p.label}
          </span>
        ))}
      </div>
      {rows.map((row) => (
        <div key={row.constraint_id} className="insight-row">
          <div className="insight-row-head">
            <span className="insight-row-id">{row.constraint_id}</span>
            <span className="insight-row-label" title={row.label}>{row.label}</span>
            <span className={`insight-chip ${row.share_unmet >= 0.3 ? 'bad' : 'neutral'}`}>
              {pct(row.share_unmet)} care
            </span>
          </div>
          <div className="insight-stack">
            {parts.map((p) => {
              const share = row[p.key] || 0;
              if (share <= 0) return null;
              return (
                <div key={p.key} className="insight-stack-seg"
                     style={{ width: `${share * 100}%`, background: p.color }}
                     title={`${p.label}: ${pct(share)} of ${count(row.n_violated)} violations`}>
                  {share > 0.12 && <span>{pct(share, 0)}</span>}
                </div>
              );
            })}
          </div>
          <div className="insight-row-meta">{count(row.n_violated)} violations</div>
        </div>
      ))}
    </div>
  );
}

/* ── Deviation profiles ──────────────────────────────────────────
   The most frequent combinations of readiness criteria violated together. */
export function ProfileBars({ profiles, onSelectProfile, selectedProfile }) {
  const rows = profiles?.top || [];
  if (!rows.length) return <p className="summary-empty">No deviation profiles available.</p>;
  const max = Math.max(...rows.map((r) => r.share || 0)) || 1;

  return (
    <div className="insight-rowlist">
      {rows.map((row) => {
        const isSelected = selectedProfile === row.profile;
        return (
          <button type="button" key={row.profile}
                  className={`insight-row insight-row-button${isSelected ? ' selected' : ''}`}
                  onClick={() => onSelectProfile?.(isSelected ? null : row.profile)}>
            <div className="insight-row-head">
              <span className="insight-profile-chips">
                {row.members.map((m) => (
                  <span key={m} className="insight-mini-chip">{m.replace('RC-DP-', '')}</span>
                ))}
              </span>
              <span className="insight-row-meta">{row.n_criteria} criteria</span>
            </div>
            <div className="insight-track">
              <div className="insight-track-fill"
                   style={{ width: `${((row.share || 0) / max) * 100}%`, background: PRIMARY }} />
              <span className="insight-track-value">{pct(row.share)}</span>
            </div>
            <div className="insight-row-meta">{count(row.n_episodes)} episodes</div>
          </button>
        );
      })}
    </div>
  );
}

/* ── Co-violation matrix ─────────────────────────────────────────
   Cell (row, col) = P(column criterion violated | row criterion violated). The
   matrix is asymmetric because the criteria have very different base rates. */
export function CoViolationHeatmap({ coviolation }) {
  const ids = coviolation?.ids || [];
  const matrix = coviolation?.matrix || [];
  if (!ids.length) return <p className="summary-empty">No co-violation matrix available.</p>;

  const shade = (v) => {
    // single-hue ramp on the primary blue; light = independent, dark = tracks together
    const a = 0.08 + 0.82 * Math.max(0, Math.min(1, v));
    return `rgba(25, 118, 210, ${a.toFixed(3)})`;
  };

  return (
    <div className="insight-heatmap-wrapper">
      <table className="insight-heatmap">
        <thead>
          <tr>
            <th className="insight-heatmap-corner">given violated ↓ / also violated →</th>
            {ids.map((cid) => (
              <th key={cid} title={coviolation.labels?.[cid]}>{cid.replace('RC-DP-', '')}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ids.map((rowId, r) => (
            <tr key={rowId}>
              <th scope="row" title={coviolation.labels?.[rowId]}>
                {ruleLabel(rowId)}
                <span className="insight-heatmap-n">n={count(coviolation.n_violated?.[rowId])}</span>
              </th>
              {ids.map((colId, c) => {
                const v = matrix[r]?.[c] ?? 0;
                const isDiag = r === c;
                return (
                  <td key={colId}
                      className={`insight-heatmap-cell${isDiag ? ' diag' : ''}`}
                      style={isDiag ? undefined : { background: shade(v) }}
                      title={isDiag
                        ? `${rowId} — diagonal`
                        : `P(${colId} violated | ${rowId} violated) = ${pct(v)}\n` +
                          `${coviolation.labels?.[rowId]}\n→ ${coviolation.labels?.[colId]}`}>
                    {isDiag ? '—' : pct(v, 0)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Mixed outcomes by episode count ───────────────────────────── */
export function MixedOutcomeBars({ mixed }) {
  const rows = mixed?.by_episode_count || [];
  if (!rows.length) return <p className="summary-empty">No mixed-outcome table available.</p>;

  return (
    <div className="insight-rowlist">
      {rows.map((row) => (
        <div key={row.episodes_in_stay} className="insight-row">
          <div className="insight-row-head">
            <span className="insight-row-label">
              {row.episodes_in_stay} {String(row.episodes_in_stay) === '1' ? 'episode' : 'episodes'} per stay
            </span>
            <span className={`insight-chip ${row.mixed_share >= 0.5 ? 'bad' : 'neutral'}`}>
              {pct(row.mixed_share)} mixed
            </span>
          </div>
          <div className="insight-track"
               title={`${count(row.n_mixed)} of ${count(row.n_stays)} stays contain both a failed and a successful trial`}>
            <div className="insight-track-fill"
                 style={{ width: `${(row.mixed_share || 0) * 100}%`, background: VIOLATION }} />
            <span className="insight-track-value">{count(row.n_mixed)} / {count(row.n_stays)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Violation rate by attempt index ─────────────────────────────
   One line per constraint. Buckets are weaning-attempt positions within a stay;
   the last bucket pools everything beyond it. */
export function AttemptTrendChart({ series }) {
  if (!series?.length) return <p className="summary-empty">Select at least one constraint.</p>;

  const buckets = [...new Set(series.flatMap((s) => s.buckets.map((b) => b.bucket)))].sort((a, b) => a - b);
  if (!buckets.length) return <p className="summary-empty">No attempt buckets available.</p>;

  const last = buckets[buckets.length - 1];
  const tickText = buckets.map((b) => (b === last && buckets.length > 1 ? `${b}+` : String(b)));

  const data = series.map((s, si) => {
    const color = SERIES_COLORS[si % SERIES_COLORS.length];
    return {
      type: 'scatter',
      mode: 'lines+markers',
      name: ruleLabel(s.constraint_id),
      x: s.buckets.map((b) => tickText[buckets.indexOf(b.bucket)]),
      y: s.buckets.map((b) => b.violation_rate),
      line: { color, width: 2 },
      marker: { color, size: 7, line: { color: '#fff', width: 1.5 } },
      customdata: s.buckets.map((b) => [b.n_violated, b.n_activated]),
      hovertemplate:
        '<b>%{fullData.name}</b> %{y:.1%} ' +
        '(%{customdata[0]:,} of %{customdata[1]:,})<extra></extra>',
    };
  });

  const layout = {
    height: 340,
    hovermode: 'x unified',
    margin: { t: 16, b: 64 },
    xaxis: {
      title: { text: 'Weaning attempt within the stay', standoff: 8 },
      type: 'category',
      categoryorder: 'array',
      categoryarray: tickText,
      gridcolor: GRID,
      fixedrange: true,
    },
    yaxis: {
      title: { text: 'Violation rate among activations' },
      tickformat: '.0%',
      range: [0, 1],
      gridcolor: GRID,
      zeroline: false,
      fixedrange: true,
    },
    legend: { orientation: 'h', y: -0.28, x: 0 },
  };

  return (
    <div className="insight-chart">
      <Suspense fallback={PlotFallback}>
        <Plot data={data} layout={layout} height={340} />
      </Suspense>
    </div>
  );
}
