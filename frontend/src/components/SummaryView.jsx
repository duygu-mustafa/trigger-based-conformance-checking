import React, { useMemo, useState, useEffect, useRef } from 'react';
import clockIcon from '../static/clock.svg';
import dataIcon from '../static/data.svg';
import controlFlowIcon from '../static/control_flow.svg';

const formatPercent = (ratio) => `${(Number(ratio || 0) * 100).toFixed(1)}%`;

const Histogram = ({ 
  data, 
  title, 
  unit = '', 
  color = '#64748b', 
  expectedMin = null,
  expectedMax = null,
  inverted = false
}) => {
  const [zoomRange, setZoomRange] = useState(null); // [min, max] or null
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectionStart, setSelectionStart] = useState(null);
  const [selectionEnd, setSelectionEnd] = useState(null);
  const svgRef = useRef(null);

  // Reset zoom when data changes
  useEffect(() => {
    setZoomRange(null);
  }, [data]);

  const validData = useMemo(() => (data || []).filter(v => typeof v === 'number' && !isNaN(v)), [data]);

  const initialMin = validData.length > 0 ? Math.min(...validData) : 0;
  const initialMax = validData.length > 0 ? Math.max(...validData) : 1;
  
  const binConfig = useMemo(() => {
    if (validData.length === 0 || !data || data.length === 0) return { zones: [], binsArr: [], densities: [], zMin: 0, zMax: 1 };
    
    const zones = [];
    const addZone = (start, end, count) => {
      if (typeof start !== 'number' || typeof end !== 'number' || isNaN(start) || isNaN(end) || end <= start || count <= 0) return;
      const step = (end - start) / count;
      for (let i = 0; i < count; i++) {
        zones.push({ s: start + i * step, e: start + (i + 1) * step });
      }
    };

    let dMin = zoomRange ? zoomRange[0] : initialMin;
    let dMax = zoomRange ? zoomRange[1] : initialMax;

    const bounds = [];
    if (typeof dMin === 'number' && !isNaN(dMin)) bounds.push(dMin);
    if (typeof dMax === 'number' && !isNaN(dMax)) bounds.push(dMax);
    if (expectedMin !== null && !isNaN(expectedMin)) bounds.push(expectedMin);
    if (expectedMax !== null && !isNaN(expectedMax)) bounds.push(expectedMax);

    if (bounds.length === 0) return { zones: [], binsArr: [], densities: [], zMin: 0, zMax: 1 };

    dMin = Math.min(...bounds);
    dMax = Math.max(...bounds);

    const rawRange = dMax - dMin;
    const buffer = (rawRange * 0.1) || (initialMax === initialMin ? 1 : 5);

    // Only extend if ANY threshold is tight against either data boundary
    const nearEdge = (val, edge) => Math.abs(val - edge) < rawRange * 0.05;
    
    if (!zoomRange) {
      if (expectedMin !== null && !isNaN(expectedMin)) {
        if (nearEdge(expectedMin, dMin)) dMin -= buffer;
        if (nearEdge(expectedMin, dMax)) dMax += buffer;
      }
      if (expectedMax !== null && !isNaN(expectedMax)) {
        if (nearEdge(expectedMax, dMin)) dMin -= buffer;
        if (nearEdge(expectedMax, dMax)) dMax += buffer;
      }

      // Prevent negative axis for timing/physiological values if they were originally positive
      if (initialMin >= 0 && dMin < 0) dMin = 0;
    }

    const zMin = dMin;
    const zMax = dMax;

    const limit1 = (expectedMin !== null && !isNaN(expectedMin)) ? expectedMin : zMin;
    const limit2 = (expectedMax !== null && !isNaN(expectedMax)) ? expectedMax : zMax;

    // Distribute bins: 4 for early, 12 for safe/primary, 4 for late
    let l1 = Math.min(limit1, limit2);
    let l2 = Math.max(limit1, limit2);

    // Keep l1 and l2 within [zMin, zMax]
    l1 = Math.max(zMin, Math.min(zMax, l1));
    l2 = Math.max(zMin, Math.min(zMax, l2));

    addZone(zMin, l1, 4);
    addZone(l1, l2, 12);
    addZone(l2, zMax, 4);

    // If no bins were added (e.g. range 0), add a single bin
    if (zones.length === 0) {
      const s = (typeof initialMin === 'number' && !isNaN(initialMin)) ? initialMin - 1 : -1;
      const e = (typeof initialMax === 'number' && !isNaN(initialMax)) ? initialMax + 1 : 1;
      zones.push({ s, e });
    }

    const binsArr = new Array(zones.length).fill(0);
    validData.forEach(v => {
      const idx = zones.findIndex(z => v >= z.s && v <= z.e);
      if (idx !== -1) binsArr[idx]++;
      else if (v < zones[0].s) binsArr[0]++;
      else if (v > zones[zones.length - 1].e) binsArr[zones.length - 1]++;
    });

    const densities = binsArr.map((count, i) => {
      const bWidth = zones[i].e - zones[i].s;
      return count / (bWidth || 1);
    });

    return { zones: zones || [], binsArr: binsArr || [], densities: densities || [], zMin, zMax };
  }, [validData, initialMin, initialMax, expectedMin, expectedMax, zoomRange]);

  const config = binConfig || { zones: [], binsArr: [], densities: [], zMin: 0, zMax: 1 };
  const { zones = [], binsArr = [], densities = [], zMin = 0, zMax = 1 } = config;

  if (!data || data.length === 0) return null;

  const maxDensity = densities.length > 0 ? Math.max(...densities, 0.000001) : 0.000001;
  const width = 450;
  const height = 220; // Slightly taller
  const margin = { top: 25, bottom: 35, left: 15, right: 15 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;
  const barTopPadding = 15; // Space at top of bars to see background

  const getXFromEvent = (e) => {
    const rect = svgRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left - margin.left;
    return Math.max(0, Math.min(innerW, x));
  };

  const handleMouseDown = (e) => {
    const x = getXFromEvent(e);
    setSelectionStart(x);
    setSelectionEnd(x);
    setIsSelecting(true);
  };

  const handleMouseMove = (e) => {
    if (!isSelecting) return;
    setSelectionEnd(getXFromEvent(e));
  };

  const handleMouseUp = () => {
    if (!isSelecting) return;
    setIsSelecting(false);
    
    if (Math.abs(selectionEnd - selectionStart) > 5) {
      const xMin = Math.min(selectionStart, selectionEnd);
      const xMax = Math.max(selectionStart, selectionEnd);
      const valMin = zMin + (xMin / innerW) * (zMax - zMin);
      const valMax = zMin + (xMax / innerW) * (zMax - zMin);
      setZoomRange([valMin, valMax]);
    }
  };

  const resetZoom = () => setZoomRange(null);

  return (
    <div className="forensics-histogram">
      <div className="chart-header-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <p className="chart-label">{title}</p>
        {zoomRange && (
          <button 
            onClick={resetZoom}
            style={{ 
              fontSize: '10px', 
              padding: '2px 6px', 
              background: '#f1f5f9', 
              border: '1px solid #e2e8f0',
              borderRadius: '4px',
              cursor: 'pointer',
              marginBottom: '4px'
            }}
          >
            Reset Zoom
          </button>
        )}
      </div>
      <svg 
        ref={svgRef}
        width={width} 
        height={height} 
        className="histogram-svg"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => setIsSelecting(false)}
        style={{ cursor: 'crosshair' }}
      >
        <g transform={`translate(${margin.left}, ${margin.top})`}>
          {isSelecting && (
            <rect
              x={Math.min(selectionStart, selectionEnd)}
              y={0}
              width={Math.abs(selectionEnd - selectionStart)}
              height={innerH}
              fill="rgba(59, 130, 246, 0.2)"
              stroke="#3b82f6"
              strokeDasharray="2 2"
            />
          )}

          {/* Y-axis label (ticks removed for density) */}
          <text 
            x={-margin.left + 5} y={-10} 
            fontSize="8" 
            fill="#94a3b8" 
            fontWeight="700" 
            textAnchor="start"
          >
            DENSITY
          </text>
          {/* Clinical Zone Shading - only render when thresholds are defined */}
          {(expectedMin !== null || expectedMax !== null) && (() => {
            const zRange = zMax - zMin;
            if (zRange === 0) return null;

            const xSafeStart = expectedMin !== null ? ((expectedMin - zMin) / zRange) * innerW : 0;
            const xSafeEnd = expectedMax !== null ? ((expectedMax - zMin) / zRange) * innerW : innerW;

            const safeColor = inverted ? "#ef4444" : "#22c55e";
            const dangerColor = inverted ? "#22c55e" : "#ef4444";

            return (
              <>
                {xSafeStart > 0 && <rect x={0} y={0} width={xSafeStart} height={innerH} fill={dangerColor} fillOpacity="0.12" />}
                <rect x={xSafeStart} y={0} width={Math.max(0, xSafeEnd - xSafeStart)} height={innerH} fill={safeColor} fillOpacity="0.12" />
                {xSafeEnd < innerW && <rect x={xSafeEnd} y={0} width={innerW - xSafeEnd} height={innerH} fill={dangerColor} fillOpacity="0.12" />}
              </>
            );
          })()}

          {binsArr.map((count, i) => {
            const z = zones[i];
            const density = densities[i];
            const zMin_val = zones[0].s;
            const zMax_val = zones[zones.length - 1].e;
            const zRange = zMax_val - zMin_val;
            
            const h = (density / maxDensity) * (innerH - barTopPadding);
            const x = zRange === 0 ? 0 : ((z.s - zMin_val) / zRange) * innerW;
            const w = zRange === 0 ? innerW : ((z.e - z.s) / zRange) * innerW;
            const y = innerH - h;
            
            return (
              <rect
                key={i}
                x={x + 1}
                y={y}
                width={Math.max(1, w - 2)}
                height={h}
                fill={color}
                fillOpacity={0.8}
                rx="1"
              >
                <title>{`Range: ${(z.s || 0).toFixed(1)}-${(z.e || 0).toFixed(1)}${unit}\nCount: ${count}`}</title>
              </rect>
            );
          })}
        </g>

        {/* X-Axis Ticks & Labels */}
        {zones.length > 0 && [0, 0.25, 0.5, 0.75, 1].map((p) => {
          const zMin_val = zones[0].s ?? 0;
          const zMax_val = zones[zones.length - 1].e ?? 1;
          const val = zMin_val + p * (zMax_val - zMin_val);
          const x = margin.left + p * innerW;
          return (
            <g key={p}>
              <line 
                x1={x} y1={height - margin.bottom} 
                x2={x} y2={height - margin.bottom + 5} 
                stroke="#e2e8f0" 
              />
              <text 
                x={x} y={height - 5} 
                textAnchor={p === 0 ? 'start' : p === 1 ? 'end' : 'middle'}
                fontSize="9" 
                fill="#94a3b8" 
                fontWeight="600"
              >
                {typeof val === 'number' && !isNaN(val) ? (val || 0).toFixed(1) : ''}{unit}
              </text>
            </g>
          );
        })}

        {/* Vertical Threshold Markers */}
        {zones.length > 0 && [expectedMin, expectedMax].map((thresh, i) => {
          if (thresh === null) return null;
          const zMin_val = zones[0].s;
          const zMax_val = zones[zones.length - 1].e;
          const zRange = zMax_val - zMin_val;
          if (zRange === 0) return null;
          const x = margin.left + ((thresh - zMin_val) / zRange) * innerW;
          if (x < margin.left || x > width - margin.right) return null;
          return (
            <line 
              key={i}
              x1={x} y1={margin.top} 
              x2={x} y2={height - margin.bottom} 
              stroke="#10b981" 
              strokeWidth="2" 
              strokeDasharray="4 2" 
            />
          );
        })}
      </svg>
    </div>
  );
};

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

const ContrastBarChart = ({ items, mode = 'violation' }) => {
  if (!items || items.length === 0) {
    return (
      <div className="bar-list">
        <p className="summary-empty">No constraints have data for this mode.</p>
      </div>
    );
  }

  const isViolation = mode === 'violation';

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

        return (
          <div key={item.constraint_id} className="contrast-row">
            <div className="contrast-info">
              <div className="icon-label-wrapper">
                {icon && <img src={icon} alt="" className="constraint-icon" />}
                <span className="bar-label" title={item.constraint_label}>{item.constraint_label}</span>
              </div>
              <div className="lift-metrics">
                <div className={`lift-tag ${isViolation ? (lift > 1.2 ? 'high-lift' : lift < 0.8 ? 'low-lift' : '') : (lift > 1.2 ? 'high-success-lift' : lift < 0.8 ? 'low-success-lift' : '')}`}>
                   {isViolation ? 'Failure Lift' : 'Success Lift'}: <strong>{(lift || 1).toFixed(2)}x</strong>
                </div>
                <div className="delta-tag">
                   {delta > 0.01 && <span className="delta-val">Δ {formatPercent(delta)}</span>}
                </div>
              </div>
            </div>
            
            <div className="dual-track-container">
              <div className="dual-track">
                 {/* Scale Grid */}
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

  // Find all unique keys across V and S deltas
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
    
    // Only invert if it's an explicit "Avoid" or "Violation" rule
    const lowerExpr = expr.trim().toLowerCase();
    const isInverted = lowerExpr.includes('violation') || lowerExpr.includes('avoid');
    
    return { min: minThresh, max: maxThresh, inverted: isInverted };
  };

  return (
    <div className="forensics-detail-content">
      <div className="detail-header">
        <div className="header-top">
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
            
            // Auto-scale FiO2 from 0-1 to 0-100 for consistency with protocol thresholds
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

const getConstraintIcon = (id) => {
  if (id.includes('-TM-')) return clockIcon;
  if (id.includes('-DP-')) return dataIcon;
  if (id.includes('-CF-') || id.includes('COMPOSITE')) return controlFlowIcon;
  return null;
};

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
        {/* Grid and Axes */}
        <g transform={`translate(${margin.left}, ${margin.top})`}>
          <rect width={plotW} height={plotH} fill="#f8fafc" />
          <line x1={0} y1={plotH} x2={plotW} y2={plotH} stroke="#cbd5e1" strokeWidth="1" />
          <line x1={0} y1={0} x2={0} y2={plotH} stroke="#cbd5e1" strokeWidth="1" />
          
          {/* Diagonal Guideline */}
          <line x1={0} y1={plotH} x2={plotW} y2={0} stroke="#e2e8f0" strokeWidth="1" strokeDasharray="4" />
          
          {/* Axis Labels */}
          {[0, 0.25, 0.5, 0.75, 1].map(v => (
            <React.Fragment key={v}>
              <text x={getX(v)} y={plotH + 15} textAnchor="middle" fontSize="10" fill="#94a3b8">{v * 100}%</text>
              <text x={-5} y={getY(v)} textAnchor="end" fontSize="10" fill="#94a3b8" alignmentBaseline="middle">{v * 100}%</text>
            </React.Fragment>
          ))}

          {/* Dots */}
          {items.filter(item => isViolation ? (item.count_success + item.count_failure) > 0 : true).map((item) => {
            const xVal = isViolation ? item.violation_rate_success : item.satisfaction_rate_success;
            const yVal = isViolation ? item.violation_rate_failure : item.satisfaction_rate_failure;
            const lift = isViolation ? item.lift_failure : item.lift_success;
            
            const x = getX(xVal || 0);
            const y = getY(yVal || 0);
            
            const color = lift > 1.2 ? (isViolation ? '#ef4444' : '#10b981') 
                        : lift < 0.8 ? (isViolation ? '#10b981' : '#ef4444') 
                        : '#64748b';

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
                  <title>{`${item.constraint_label}\nSuccess ${isViolation ? 'Violation' : 'Satisfaction'}: ${formatPercent(xVal)}\nFailure ${isViolation ? 'Violation' : 'Satisfaction'}: ${formatPercent(yVal)}\n${isViolation ? 'Failure Lift' : 'Success Lift'}: ${(lift || 1).toFixed(2)}x`}</title>
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

const SummaryView = ({ summaryData, onSelectStay }) => {
  const [query, setQuery] = useState('');
  const [sortBy, setSortBy] = useState('total_mandatory_violations');
  const [analysisMode, setAnalysisMode] = useState('violation'); // 'violation' or 'satisfaction'
  const [selectedConstraintId, setSelectedConstraintId] = useState(null);
  const [forensicsSidebarWidth, setForensicsSidebarWidth] = useState(550);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const isResizing = React.useRef(false);

  // Reset to page 1 when searching or sorting
  useEffect(() => {
    setCurrentPage(1);
  }, [query, sortBy]);

  const startResizing = (e) => {
    isResizing.current = true;
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', stopResizing);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  const stopResizing = () => {
    isResizing.current = false;
    document.removeEventListener('mousemove', handleMouseMove);
    document.removeEventListener('mouseup', stopResizing);
    document.body.style.cursor = 'default';
    document.body.style.userSelect = 'auto';
  };

  const handleMouseMove = (e) => {
    if (!isResizing.current) return;
    // Calculate new width relative to the section start
    const section = document.querySelector('.forensics-layout');
    if (section) {
      const rect = section.getBoundingClientRect();
      const newWidth = e.clientX - rect.left;
      if (newWidth > 200 && newWidth < 800) {
        setForensicsSidebarWidth(newWidth);
      }
    }
  };

  const topViolations = useMemo(
    () => {
      const all = (summaryData?.violation_frequency || [])
        .filter(v => v.count > 0)
        .sort((a, b) => b.count - a.count);
      return all;
    },
    [summaryData]
  );

  const selectedConstraint = useMemo(
    () => topViolations.find(v => v.constraint_id === selectedConstraintId) || topViolations[0],
    [topViolations, selectedConstraintId]
  );

  const allCorrelationData = useMemo(() => {
    const data = [...(summaryData?.violation_frequency || [])];
    const isViolation = analysisMode === 'violation';

    return data.sort((a, b) => {
        // Push constraints with NO data in current mode to bottom
        const aCount = isViolation ? (a.count_success + a.count_failure) : (a.count_satisfied);
        const bCount = isViolation ? (b.count_success + b.count_failure) : (b.count_satisfied);
        
        if (aCount === 0 && bCount > 0) return 1;
        if (bCount === 0 && aCount > 0) return -1;

        // Sort by significance (distance from Lift 1.0)
        const liftA = isViolation ? (a.lift_failure || 1) : (a.lift_success || 1);
        const liftB = isViolation ? (b.lift_failure || 1) : (b.lift_success || 1);

        return Math.abs(liftB - 1) - Math.abs(liftA - 1);
      });
  }, [summaryData, analysisMode]);

  const topUnmetReadinessCriteria = useMemo(
    () => (summaryData?.readiness_bottlenecks || []).slice(0, 7),
    [summaryData]
  );

  const allFilteredStays = useMemo(() => {
    const rows = [...(summaryData?.stay_summaries || [])];
    const normalizedQuery = query.trim().toLowerCase();

    const filtered = normalizedQuery
      ? rows.filter(row => String(row.stay_id).toLowerCase().includes(normalizedQuery))
      : rows;

    filtered.sort((a, b) => {
      if (sortBy === 'stay_id') return String(a.stay_id).localeCompare(String(b.stay_id));
      if (sortBy === 'overall_outcome') return String(a.overall_outcome).localeCompare(String(b.overall_outcome));
      return Number(b[sortBy] || 0) - Number(a[sortBy] || 0);
    });

    return filtered;
  }, [summaryData, query, sortBy]);

  const totalResults = allFilteredStays.length;
  const totalPages = Math.ceil(totalResults / pageSize);
  const stayRows = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return allFilteredStays.slice(start, start + pageSize);
  }, [allFilteredStays, currentPage, pageSize]);

  const outcomeStats = summaryData?.conformance_vs_outcome || {};
  const successStats = outcomeStats.success || {};
  const failureStats = outcomeStats.failure || {};

  return (
    <div className="summary-view">
      <div className="summary-metrics-grid">
        <section className="summary-card metric-card">
          <h3>Total Stays</h3>
          <p className="metric-value">{summaryData?.total_stays ?? 0}</p>
        </section>
        <section className="summary-card metric-card">
          <h3>Total Episodes</h3>
          <p className="metric-value">{summaryData?.total_episodes ?? 0}</p>
        </section>
        <section className="summary-card metric-card">
          <h3>Avg Violations (SBT Success)</h3>
          <p className="metric-value">{Number(successStats.avg_mandatory_violations || 0).toFixed(2)}</p>
          <p className="metric-subtext">n={successStats.episodes || 0}</p>
        </section>
        <section className="summary-card metric-card">
          <h3>Avg Violations (SBT Failure)</h3>
          <p className="metric-value">{Number(failureStats.avg_mandatory_violations || 0).toFixed(2)}</p>
          <p className="metric-subtext">n={failureStats.episodes || 0}</p>
        </section>
      </div>

      <section className="summary-card forensics-explorer">
        <div className="section-header">
          <div className="title-group">
            <h3>Violation Forensics Explorer</h3>
            <p className="header-subtitle">Deep-dive into the magnitudes and timing of rule breaches</p>
          </div>
        </div>
        <div className="forensics-layout">
          <div className="forensics-master" style={{ width: forensicsSidebarWidth, flex: 'none' }}>
            <div className="master-header">
              <h4>Most Frequent {analysisMode === 'violation' ? 'Violations' : 'Satisfactions'}</h4>
              <span className="header-hint">Rate</span>
            </div>
            <div className="forensics-list">
              {topViolations.slice(0, 15).map(v => {
                const rate = analysisMode === 'violation' ? v.episode_share : (v.count_satisfied / (summaryData?.total_episodes || 1));
                return (
                  <div 
                    key={v.constraint_id} 
                    className={`forensics-row ${selectedConstraint?.constraint_id === v.constraint_id ? 'active' : ''}`}
                    onClick={() => setSelectedConstraintId(v.constraint_id)}
                  >
                    <div className="row-bar-bg" style={{ 
                      width: `${rate * 100}%`,
                      backgroundColor: '#94a3b8',
                    }} />
                    <div className="row-content">
                      <div className="row-main">
                        <img src={getConstraintIcon(v.constraint_id)} alt="" className="row-icon" />
                        <span className="row-label" title={v.constraint_label}>{v.constraint_label}</span>
                      </div>
                      <div className="row-meta">
                        <span className="row-percent">{formatPercent(rate)}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          
          <div className="forensics-resizer" onMouseDown={startResizing} />

          <div className="forensics-detail">
            <ConstraintDetailView constraint={selectedConstraint} itemLabels={summaryData?.item_labels} />
          </div>
        </div>
      </section>

      <section className="summary-card correlation-deep-dive">
        <div className="section-header">
          <div className="title-group">
            <h3>SBT Outcome Correlation Analysis</h3>
            <p className="header-subtitle">Understanding which constraints drive trial {analysisMode === 'violation' ? 'failure' : 'success'}</p>
          </div>
          <div className="tab-switcher">
            <button 
              className={`tab-btn ${analysisMode === 'violation' ? 'active' : ''}`} 
              onClick={() => setAnalysisMode('violation')}
            >
              Violation Analysis
            </button>
            <button 
              className={`tab-btn ${analysisMode === 'satisfaction' ? 'active' : ''}`} 
              onClick={() => setAnalysisMode('satisfaction')}
            >
              Satisfaction Analysis
            </button>
          </div>
        </div>
        <div className="correlation-layout">
          <div className="correlation-plot-area">
            <h4>{analysisMode === 'violation' ? 'Outcome Distribution (Success vs. Failure)' : 'Outcome Distribution (Failure vs. Success)'}</h4>
            <OutcomeScatterPlot items={allCorrelationData} mode={analysisMode} />
          </div>
          <div className="correlation-list-area">
            <h4>All Constraints Ranked by {analysisMode === 'violation' ? 'Failure' : 'Success'} Lift</h4>
            <div className="scrollable-lift-list">
              <ContrastBarChart items={allCorrelationData} mode={analysisMode} />
            </div>
          </div>
        </div>
      </section>

      <section className="summary-card">
        <div className="table-header-row">
          <h3>Stay Explorer</h3>
          <div className="table-controls">
            <input
              className="summary-input"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search stay ID..."
            />
            <select
              className="summary-select"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
            >
              <option value="total_mandatory_violations">Sort: Total Violations</option>
              <option value="avg_mandatory_violations">Sort: Avg Violations</option>
              <option value="episodes">Sort: Episode Count</option>
              <option value="overall_outcome">Sort: Overall Outcome</option>
              <option value="stay_id">Sort: Stay ID</option>
            </select>
          </div>
        </div>

        <div className="summary-table-wrapper">
          <table className="summary-table">
            <thead>
              <tr>
                <th>Stay ID</th>
                <th>Outcome</th>
                <th>Episodes</th>
                <th>Total Violations</th>
                <th>Avg Violations</th>
                <th>Unique Violated Constraints</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {stayRows.map((row) => (
                <tr key={row.stay_id}>
                  <td>{row.stay_id}</td>
                  <td>{row.overall_outcome}</td>
                  <td>{row.episodes}</td>
                  <td>{row.total_mandatory_violations}</td>
                  <td>{Number(row.avg_mandatory_violations || 0).toFixed(2)}</td>
                  <td>{row.violated_constraints_count}</td>
                  <td>
                    <button
                      className="open-stay-button"
                      onClick={() => onSelectStay?.(String(row.stay_id))}
                    >
                      Open Timeline
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {stayRows.length === 0 ? (
            <p className="summary-empty">No stays match the current filter.</p>
          ) : null}
        </div>

        {/* Pagination Controls */}
        {totalResults > 0 && (
          <div className="table-pagination">
            <div className="pagination-info">
              Showing <strong>{((currentPage - 1) * pageSize) + 1}</strong> to <strong>{Math.min(currentPage * pageSize, totalResults)}</strong> of <strong>{totalResults}</strong> stays
            </div>
            <div className="pagination-controls">
              <div className="page-size-selector">
                <label>Rows per page:</label>
                <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>
                  <option value={10}>10</option>
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </div>
              <button 
                className="pag-btn" 
                disabled={currentPage === 1} 
                onClick={() => setCurrentPage(prev => prev - 1)}
              >
                Previous
              </button>
              <span className="page-num">Page <strong>{currentPage}</strong> of {totalPages}</span>
              <button 
                className="pag-btn" 
                disabled={currentPage === totalPages} 
                onClick={() => setCurrentPage(prev => prev + 1)}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
};

export default SummaryView;
