import React, { useState } from 'react';

const Timeline = ({ data }) => {
  const { events, conformance, constraint_definitions } = data;
  const [hoveredEvent, setHoveredEvent] = useState(null);
  const [selectedEpisode, setSelectedEpisode] = useState(null);
  
  if (!events || events.length === 0) return <div>No event data</div>;

  const timestamps = events.map(e => new Date(e.timestamp).getTime());
  const minTime = Math.min(...timestamps);
  const maxTime = Math.max(...timestamps);
  const duration = maxTime - minTime;

  const width = 1200;
  const rowHeight = 100;
  const paddingLeft = 100;
  const paddingRight = 150; // Increased to prevent label clipping
  const paddingTop = 40;
  const chartWidth = width - paddingLeft - paddingRight;

  const getX = (timestamp) => {
    const time = new Date(timestamp).getTime();
    return paddingLeft + ((time - minTime) / duration) * chartWidth;
  };

  const getHours = (timestamp) => {
    const time = new Date(timestamp).getTime();
    return (time - minTime) / (1000 * 60 * 60);
  };

  const measurements = events.filter(e => !['InvasiveVentilationStarted', 'SBTStarted', 'SBTCompleted', 'SBTFailed', 'SBTStopped', 'Intubation', 'Extubation', 'InvasiveVentilationEnded'].includes(e.activity));

  const findNext = (list, startTime) => {
    const start = new Date(startTime).getTime();
    return list.find(e => new Date(e.timestamp).getTime() > start);
  };

  const findLatestBefore = (activity, ts) => {
    const targetTime = new Date(ts).getTime();
    const matches = events.filter(e => e.activity === activity && new Date(e.timestamp).getTime() <= targetTime);
    if (matches.length === 0) return null;
    return matches.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())[0];
  };

  const getSBTDuration = (sbtStart) => {
    const end = findNext(events.filter(e => ['SBTCompleted', 'SBTFailed', 'SBTStopped'].includes(e.activity)), sbtStart);
    if (!end) return null;
    return new Date(end.timestamp).getTime() - new Date(sbtStart).getTime();
  };

  const getViolationDetail = (cid, episode) => {
    const def = constraint_definitions[cid];
    if (!def) return null;

    if (cid === 'RC-DP-04') {
        const latest = findLatestBefore('temperature_c', episode.sbt_start);
        return { actual: latest ? `${latest.value_num}°C` : 'N/A', expected: '<= 38°C' };
    }
    if (cid === 'RC-DP-03') {
        const latest = findLatestBefore('hemoglobin', episode.sbt_start);
        return { actual: latest ? `${latest.value_num} g/dL` : 'N/A', expected: '>= 7 g/dL' };
    }
    if (cid === 'RC-TM-03') {
        const actualH = episode.sbt_start ? getHours(episode.sbt_start) - getHours(episode.episode_start) : 'N/A';
        return { actual: typeof actualH === 'number' ? `${actualH.toFixed(1)}h` : 'No SBT', expected: '48h - 72h after ventilation start' };
    }
    return null;
  };

  return (
    <div className="timeline-container">
      <div className="tooltip-area">
        {hoveredEvent ? (
          <div className="tooltip-content">
            <strong>{hoveredEvent.label || hoveredEvent.activity}</strong>: {hoveredEvent.value}
          </div>
        ) : (
          <div className="tooltip-placeholder">Hover over bars for details • Click an episode for report</div>
        )}
      </div>

      <div className="main-layout">
        <div className="chart-area">
          <svg viewBox={`0 0 ${width} ${paddingTop + rowHeight * (conformance.length + 1)}`} className="timeline-svg">
            {/* Time Axis */}
            <line x1={paddingLeft} y1={paddingTop - 10} x2={width - paddingRight} y2={paddingTop - 10} stroke="#555" strokeWidth="2" />
            {[0, 24, 48, 72, 96, 120, 144, 168, 192, 216, 240, 480, 720].map(h => {
              const time = minTime + h * 60 * 60 * 1000;
              if (time > maxTime) return null;
              const x = getX(time);
              return (
                <g key={h}>
                  <line x1={x} y1={paddingTop - 15} x2={x} y2={paddingTop - 5} stroke="#555" strokeWidth="2" />
                  <text x={x} y={paddingTop - 25} textAnchor="middle" fill="#888" fontSize="11" fontWeight="bold">{h}h</text>
                </g>
              );
            })}

            {/* Episodes */}
            {conformance.map((episode, i) => {
              const y = paddingTop + 10 + i * rowHeight;
              const xStart = getX(episode.episode_start);
              const xEnd = getX(episode.episode_end);
              const sbtX = episode.sbt_start ? getX(episode.sbt_start) : null;
              const isViolated = episode.num_mandatory_violations > 0;
              const isSelected = selectedEpisode?.episode_index === episode.episode_index;
              
              // Invasive Ventilation Bar (from episode start to SBT start or episode end)
              const ventEndX = sbtX || xEnd;

              return (
                <g key={`episode-${i}`} onClick={() => setSelectedEpisode(episode)} style={{ cursor: 'pointer' }}>
                  {/* Row Background Window */}
                  <rect x={paddingLeft} y={y} width={chartWidth + paddingRight} height={rowHeight - 15} fill="#111" rx={6} opacity={0.3} />
                  
                  {/* Row Divider */}
                  <line x1={paddingLeft} y1={y + rowHeight - 10} x2={width - paddingRight} y2={y + rowHeight - 10} stroke="#333" strokeDasharray="4 4" />
                  <text x={paddingLeft - 15} y={y + 45} textAnchor="end" fill={isSelected ? "#fff" : "#888"} fontSize="12" fontWeight={isSelected ? "bold" : "normal"}>Ep {episode.episode_index}</text>

                  {/* Invasive Ventilation Bar */}
                  <rect
                    x={xStart}
                    y={y + 15}
                    width={Math.max(4, ventEndX - xStart)}
                    height={25}
                    fill="#e91e63"
                    opacity={0.6}
                    rx={4}
                    onMouseEnter={() => setHoveredEvent({ activity: 'Invasive Ventilation', value: `Full Support for ${((new Date(episode.sbt_start || episode.episode_end) - new Date(episode.episode_start)) / (1000*60*60)).toFixed(1)}h` })}
                    onMouseLeave={() => setHoveredEvent(null)}
                  />
                  
                  {/* SBT Bar */}
                  {sbtX && (
                    <rect
                      x={sbtX}
                      y={y + 15}
                      width={Math.max(30, (getSBTDuration(episode.sbt_start) / duration) * chartWidth || 30)}
                      height={25}
                      fill="#2196f3"
                      rx={4}
                      onMouseEnter={() => setHoveredEvent({ 
                        activity: 'SBT Attempt', 
                        value: `${episode.sbt_outcome} at ${getHours(episode.sbt_start).toFixed(1)}h` 
                      })}
                      onMouseLeave={() => setHoveredEvent(null)}
                    />
                  )}

                  {/* Conformance Indicators */}
                  <g>
                    <circle cx={xStart + 15} cy={y + 60} r={7} fill={isViolated ? "#ff5722" : "#4caf50"} />
                    {isViolated && (
                      <text x={xStart + 30} y={y + 65} fill="#ff5722" fontSize="11" fontWeight="bold">
                        {episode.num_mandatory_violations} violations
                      </text>
                    )}
                    
                    {/* Target Window visual aid */}
                    {episode.mandatory_violated_constraints.includes('RC-TM-03') && (
                      <rect 
                        x={getX(episode.episode_start) + (48 * 60 * 60 * 1000 / duration) * chartWidth} 
                        y={y + 50} 
                        width={(24 * 60 * 60 * 1000 / duration) * chartWidth} 
                        height={6} 
                        fill="#4caf50" 
                        opacity={0.4} 
                        rx={3}
                      />
                    )}
                  </g>
                </g>
              );
            })}

            {/* Measurements as markers */}
            {measurements.map((m, i) => {
              const x = getX(m.timestamp);
              return (
                <circle
                  key={`meas-${i}`}
                  cx={x}
                  cy={paddingTop + 5}
                  r={3}
                  fill="#ffeb3b"
                  opacity={0.6}
                  onMouseEnter={() => setHoveredEvent({ 
                    activity: m.activity, 
                    value: `${m.value_num || m.value_raw} ${m.unit || ''}` 
                  })}
                  onMouseLeave={() => setHoveredEvent(null)}
                />
              );
            })}
          </svg>
        </div>

        {/* Sidebar */}
        <div className="details-sidebar">
          {selectedEpisode ? (
            <div>
              <h3>Episode {selectedEpisode.episode_index}</h3>
              <p><strong>Outcome:</strong> {selectedEpisode.sbt_outcome}</p>
              
              <h4 style={{ color: '#ff5722', borderBottom: '1px solid #444', paddingBottom: '5px' }}>Violations</h4>
              {selectedEpisode.mandatory_violated_constraints ? (
                <div className="violation-list">
                  {selectedEpisode.mandatory_violated_constraints.split(';').map(cid => {
                    const detail = getViolationDetail(cid, selectedEpisode);
                    return (
                      <div key={cid} style={{ marginBottom: '10px', padding: '8px', background: '#2a2a2a', borderRadius: '4px' }}>
                        <div style={{ color: '#ff5722', fontWeight: 'bold', fontSize: '12px' }}>{cid}: {constraint_definitions[cid]?.label}</div>
                        {detail && (
                          <div style={{ fontSize: '11px', marginTop: '4px' }}>
                            <span style={{ color: '#888' }}>Value:</span> {detail.actual} | <span style={{ color: '#888' }}>Target:</span> {detail.expected}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : <p>None</p>}
            </div>
          ) : (
            <div style={{ textAlign: 'center', color: '#666', marginTop: '40px' }}>Select an episode to view details</div>
          )}
        </div>
      </div>

      <div className="legend" style={{ marginTop: '20px', display: 'flex', gap: '20px', justifyContent: 'center' }}>
        <div className="legend-item"><div className="legend-color" style={{background: '#e91e63'}}></div><span>Invasive Ventilation (Full Support)</span></div>
        <div className="legend-item"><div className="legend-color" style={{background: '#2196f3'}}></div><span>SBT Trial</span></div>
        <div className="legend-item"><div className="legend-color" style={{background: '#ffeb3b'}}></div><span>Measurement</span></div>
        <div className="legend-item"><div className="legend-color" style={{background: '#4caf50'}}></div><span>Conforming</span></div>
        <div className="legend-item"><div className="legend-color" style={{background: '#ff5722'}}></div><span>Violation</span></div>
      </div>
    </div>
  );
};

export default Timeline;
