import React, { useMemo, useState, useEffect, useRef } from 'react';

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

          <text 
            x={-margin.left + 5} y={-10} 
            fontSize="8" 
            fill="#94a3b8" 
            fontWeight="700" 
            textAnchor="start"
          >
            DENSITY
          </text>
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

export default Histogram;
