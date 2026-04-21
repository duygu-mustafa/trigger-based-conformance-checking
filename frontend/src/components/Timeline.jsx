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

  const measurements = events.filter(e => !['InvasiveVentilationStarted', 'SBTStarted', 'SBTCompleted', 'SBTFailed', 'Intubation', 'Extubation', 'InvasiveVentilationEnded'].includes(e.activity));

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

  const parseViolationIds = (value) => {
    if (!value || typeof value !== 'string') return [];
    return value.split(';').map(v => v.trim()).filter(Boolean);
  };

  const parseCompositeInterventions = (value) => {
    if (!value || typeof value !== 'string') return [];
    return value.split(';').map(v => v.trim()).filter(Boolean);
  };

  const interventionLabel = (activity) => {
    const labels = {
      Bronchodilator_Admin: 'Bronchodilator administration',
      Diuretic_Admin: 'Diuretic administration',
      AfterloadReduction_Admin: 'Afterload reduction therapy',
      ElectrolyteBG_Test: 'Electrolyte and blood gas labs',
      ElectrolyteCorrection_Admin: 'Electrolyte replacement',
      HormonalLab_Test: 'Cortisol/thyroid labs',
      HormonalReplacement_Admin: 'Hormonal replacement therapy',
    };
    return labels[activity] || activity;
  };

  const latestItemBefore = (itemIds, ts, lookbackHours = 24) => {
    if (!ts) return null;
    const end = new Date(ts).getTime();
    const start = end - lookbackHours * 60 * 60 * 1000;
    const idSet = new Set(itemIds.map(id => String(id)));
    const matches = events
      .filter((e) => {
        const t = new Date(e.timestamp).getTime();
        if (Number.isNaN(t) || t > end || t < start) return false;
        if (e.itemid == null) return false;
        return idSet.has(String(e.itemid));
      })
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
    return matches[0] || null;
  };

  const getConstraintDefinition = (cid) => {
    if (!constraint_definitions) return null;
    if (constraint_definitions[cid]) return constraint_definitions[cid];
    return null;
  };

  const getEpisodeOutcomeStatus = (episode) => {
    const outcome = String(episode?.sbt_outcome || '').toLowerCase();
    if (outcome.includes('success')) return 'success';
    if (outcome.includes('failure')) return 'failure';
    return 'neutral';
  };

  const formatMeasurement = (event, suffix = '') => {
    if (!event) return 'N/A';
    const raw = event.value_num ?? event.value_raw;
    const unit = event.unit ? ` ${event.unit}` : '';
    return `${raw}${unit}${suffix}`;
  };

  const getViolationDetail = (cid, episode) => {
    const def = getConstraintDefinition(cid);
    if (!def) return null;

    if (cid === 'INT-COMPOSITE-01') {
      const interventions = parseCompositeInterventions(episode.composite_interventions);
      const readable = interventions.map(interventionLabel);
      return {
        actual: readable.length > 0
          ? `Detected: ${readable.join(', ')}`
          : (episode.composite_note || 'No qualifying post-failure intervention found in this window'),
        expected: 'At least one qualifying intervention/test within 24h after SBT failure',
      };
    }

    if (cid === 'RC-DP-01') {
      const ratio = latestItemBefore(['pao2fio2ratio'], episode.sbt_start, 24);
      const spo2 = latestItemBefore([220277], episode.sbt_start, 24);
      const fio2 = latestItemBefore(['fio2_bg'], episode.sbt_start, 24);
      const peep = latestItemBefore(['peep_vent'], episode.sbt_start, 24);
      const actual = ratio
        ? `PaO2/FiO2=${formatMeasurement(ratio)}`
        : `SpO2=${formatMeasurement(spo2)}, FiO2=${formatMeasurement(fio2)}, PEEP=${formatMeasurement(peep)}`;
      return { actual, expected: 'PaO2/FiO2 >= 150 OR (SpO2 >= 90 AND FiO2 <= 0.40 AND PEEP <= 5)', observedAt: ratio?.timestamp || spo2?.timestamp || fio2?.timestamp || peep?.timestamp || null };
    }
    if (cid === 'RC-DP-02') {
      const latest = latestItemBefore(['ph_bg'], episode.sbt_start, 24);
      return { actual: formatMeasurement(latest), expected: 'Arterial pH > 7.25', observedAt: latest?.timestamp || null };
    }
    if (cid === 'RC-DP-03') {
      const latest = latestItemBefore(['hemoglobin_bg'], episode.sbt_start, 24);
      return { actual: formatMeasurement(latest), expected: 'Hemoglobin >= 7 g/dL', observedAt: latest?.timestamp || null };
    }
    if (cid === 'RC-DP-04') {
      const latest = latestItemBefore([223762], episode.sbt_start, 24);
      return { actual: formatMeasurement(latest), expected: 'Core temperature <= 38 C', observedAt: latest?.timestamp || null };
    }
    if (cid === 'RC-DP-05') {
      const latest = latestItemBefore(['norepinephrine_equiv'], episode.sbt_start, 24);
      return { actual: formatMeasurement(latest), expected: 'Norepinephrine-equivalent dose <= 0.1 mcg/kg/min', observedAt: latest?.timestamp || null };
    }
    if (cid === 'RC-DP-06') {
      const cam = latestItemBefore([228302], episode.sbt_start, 24);
      const sas = latestItemBefore([223753], episode.sbt_start, 24);
      return {
        actual: `CAM-ICU LOC=${formatMeasurement(cam)}, SAS=${formatMeasurement(sas)}`,
        expected: "CAM-ICU LOC = 'Yes' OR SAS in [3, 4]",
        observedAt: cam?.timestamp || sas?.timestamp || null,
      };
    }
    if (cid === 'RC-DP-07') {
      const latest = latestItemBefore([224686], episode.sbt_start, 24);
      return { actual: formatMeasurement(latest), expected: 'Spontaneous tidal volume > 0 mL', observedAt: latest?.timestamp || null };
    }
    if (cid === 'RC-TM-02') {
      const sortedStarts = conformance
        .filter(ep => ep.sbt_start)
        .sort((a, b) => new Date(a.sbt_start).getTime() - new Date(b.sbt_start).getTime());
      const idx = sortedStarts.findIndex(ep => ep.episode_index === episode.episode_index);
      if (idx <= 0) return { actual: 'No prior SBT start', expected: 'At least 24h after prior failed SBT' };
      const prev = sortedStarts[idx - 1];
      const deltaH = (new Date(episode.sbt_start).getTime() - new Date(prev.sbt_start).getTime()) / (1000 * 60 * 60);
      return { actual: `${deltaH.toFixed(1)}h`, expected: 'At least 24h after prior failed SBT' };
    }
    if (cid === 'RC-TM-03') {
      const actualH = episode.sbt_start ? getHours(episode.sbt_start) - getHours(episode.episode_start) : null;
      return { actual: typeof actualH === 'number' ? `${actualH.toFixed(1)}h` : 'No SBT start', expected: 'SBT should occur within 72h of ventilation start' };
    }
    if (cid === 'SBT-CF-01') {
      const hasCompletion = !!findNext(events.filter(e => e.activity === 'SBTCompleted'), episode.sbt_start || episode.episode_start);
      return { actual: hasCompletion ? 'SBTCompleted found' : 'No SBTCompleted found', expected: 'Each SBTStarted must have a corresponding SBTCompleted event' };
    }
    if (cid === 'SBT-DP-01') {
      let durationMin = null;
      if (episode.sbt_start && episode.sbt_end) {
        const durationMs = new Date(episode.sbt_end).getTime() - new Date(episode.sbt_start).getTime();
        durationMin = durationMs / (1000 * 60);
      }
      return {
        actual: durationMin != null ? `${durationMin.toFixed(1)} min` : 'No measurable SBT duration',
        expected: 'SBT duration should be between 30 and 120 min for valid success',
      };
    }
    if (cid === 'SBT-DP-06') {
      const ventHours = episode.sbt_start ? (new Date(episode.sbt_start).getTime() - new Date(episode.episode_start).getTime()) / (1000 * 60 * 60) : null;
      const ventMode = latestItemBefore([223848], episode.sbt_start || episode.episode_end, 24);
      const modeValue = (ventMode?.value_raw ?? ventMode?.value_num ?? 'N/A');
      return {
        actual: `Vent duration=${ventHours != null ? `${ventHours.toFixed(1)}h` : 'N/A'}, mode=${modeValue}`,
        expected: 'If vent duration > 24h, mode should include PSV',
        observedAt: ventMode?.timestamp || null,
      };
    }
    if (cid === 'SBT-TM-01') {
      let durationH = null;
      if (episode.sbt_start && episode.sbt_end) {
        const durationMs = new Date(episode.sbt_end).getTime() - new Date(episode.sbt_start).getTime();
        durationH = durationMs / (1000 * 60 * 60);
      }
      return {
        actual: durationH != null ? `${durationH.toFixed(2)}h` : 'No completion timestamp found',
        expected: 'SBTCompleted should be recorded within 3h of SBTStarted',
      };
    }

    return {
      actual: 'Not available',
      expected: def.activation_condition || def.target_condition || def.rationale || 'See rule definition',
    };
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
            <line x1={paddingLeft} y1={paddingTop - 10} x2={width - paddingRight} y2={paddingTop - 10} stroke="#94a3b8" strokeWidth="2" />
            {[0, 24, 48, 72, 96, 120, 144, 168, 192, 216, 240, 480, 720].map(h => {
              const time = minTime + h * 60 * 60 * 1000;
              if (time > maxTime) return null;
              const x = getX(time);
              return (
                <g key={h}>
                  <line x1={x} y1={paddingTop - 15} x2={x} y2={paddingTop - 5} stroke="#94a3b8" strokeWidth="2" />
                  <text x={x} y={paddingTop - 25} textAnchor="middle" fill="#64748b" fontSize="11" fontWeight="bold">{h}h</text>
                </g>
              );
            })}

            {/* Episodes */}
            {conformance.map((episode, i) => {
              const y = paddingTop + 10 + i * rowHeight;
              const xStart = getX(episode.episode_start);
              const xEnd = getX(episode.episode_end);
              const sbtX = episode.sbt_start ? getX(episode.sbt_start) : null;
              const sbtEndX = episode.sbt_end ? getX(episode.sbt_end) : null;
              const isViolated = episode.num_mandatory_violations > 0;
              const isSelected = selectedEpisode?.episode_index === episode.episode_index;
              const outcomeStatus = getEpisodeOutcomeStatus(episode);
              const rowFill = outcomeStatus === 'success'
                ? (isSelected ? '#b7e4c7' : '#d8f3dc')
                : outcomeStatus === 'failure'
                  ? (isSelected ? '#fecaca' : '#fee2e2')
                  : (isSelected ? '#e2e8f0' : '#f1f5f9');

              // Invasive Ventilation Bar (from episode start to SBT start or episode end)
              const ventEndX = sbtX || xEnd;

              return (
                <g key={`episode-${i}`} onClick={() => setSelectedEpisode(episode)} style={{ cursor: 'pointer' }}>
                  {/* Row Background Window */}
                  <rect x={paddingLeft} y={y} width={chartWidth + paddingRight} height={rowHeight - 15} fill={rowFill} rx={6} opacity={1} />

                  {/* Row Divider */}
                  <line x1={paddingLeft} y1={y + rowHeight - 10} x2={width - paddingRight} y2={y + rowHeight - 10} stroke="#cbd5e1" strokeDasharray="4 4" />
                  <text x={paddingLeft - 15} y={y + 45} textAnchor="end" fill={isSelected ? "#0f172a" : "#64748b"} fontSize="12" fontWeight={isSelected ? "bold" : "normal"}>Ep {episode.episode_index}</text>

                  {/* Invasive Ventilation Bar */}
                  <rect
                    x={xStart}
                    y={y + 15}
                    width={Math.max(4, ventEndX - xStart)}
                    height={25}
                    fill="#e91e63"
                    opacity={0.6}
                    rx={4}
                    onMouseEnter={() => setHoveredEvent({ activity: 'Invasive Ventilation', value: `Full Support for ${((new Date(episode.sbt_start || episode.episode_end) - new Date(episode.episode_start)) / (1000 * 60 * 60)).toFixed(1)}h` })}
                    onMouseLeave={() => setHoveredEvent(null)}
                  />

                  {/* SBT Bar */}
                  {sbtX && sbtEndX && (
                    <rect
                      x={sbtX}
                      y={y + 15}
                      width={Math.max(30, sbtEndX - sbtX)}
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

              <h4 style={{ color: '#b91c1c', borderBottom: '1px solid #dbe4ef', paddingBottom: '5px' }}>Violations</h4>
              {selectedEpisode.mandatory_violated_constraints ? (
                <div className="violation-list">
                  {parseViolationIds(selectedEpisode.mandatory_violated_constraints).map(cid => {
                    if (cid === 'INT-COMPOSITE-01') return null;
                    const detail = getViolationDetail(cid, selectedEpisode);
                    const def = getConstraintDefinition(cid);
                    return (
                      <div key={cid} style={{ marginBottom: '10px', padding: '8px', background: '#eef4fb', border: '1px solid #d8e4f1', borderRadius: '4px' }}>
                        <div style={{ color: '#b91c1c', fontWeight: 'bold', fontSize: '12px' }}>{cid}: {def?.label || 'Unknown rule'}</div>
                        {detail ? (
                          <div style={{ fontSize: '11px', marginTop: '4px' }}>
                            <div><span style={{ color: '#64748b' }}>Current:</span> {detail.actual}</div>
                            <div><span style={{ color: '#64748b' }}>Expected:</span> {detail.expected}</div>
                            {detail.observedAt && <div><span style={{ color: '#64748b' }}>Observed at:</span> {detail.observedAt}</div>}
                          </div>
                        ) : <div style={{ fontSize: '11px', marginTop: '4px', color: '#64748b' }}>No details available.</div>}
                      </div>
                    );
                  })}
                </div>
              ) : <p>None</p>}

              {(() => {
                const compositeRuleId = 'INT-COMPOSITE-01';
                const satisfied = parseViolationIds(selectedEpisode.mandatory_satisfied_constraints).includes(compositeRuleId);
                const violated = parseViolationIds(selectedEpisode.mandatory_violated_constraints).includes(compositeRuleId);
                if (!satisfied && !violated) return null;

                const interventions = parseCompositeInterventions(selectedEpisode.composite_interventions);
                const readableInterventions = interventions.map(interventionLabel);

                return (
                  <div style={{ marginTop: '14px' }}>
                    <h4 style={{ color: '#1d4ed8', borderBottom: '1px solid #dbe4ef', paddingBottom: '5px' }}>Composite Failure Intervention Check</h4>
                    <div style={{ marginBottom: '10px', padding: '8px', background: '#eef4fb', border: '1px solid #d8e4f1', borderRadius: '4px' }}>
                      <div style={{ color: '#1d4ed8', fontWeight: 'bold', fontSize: '12px' }}>
                        {compositeRuleId}: {getConstraintDefinition(compositeRuleId)?.label || 'At least one failure intervention must occur after SBT failure'}
                      </div>
                      <div style={{ fontSize: '11px', marginTop: '4px' }}>
                        <div>
                          <span style={{ color: '#64748b' }}>Status:</span> {satisfied ? 'Satisfied' : 'Violated'}
                        </div>
                        <div>
                          <span style={{ color: '#64748b' }}>Expected:</span> At least one qualifying intervention/test within 24h after SBT failure
                        </div>
                        <div>
                          <span style={{ color: '#64748b' }}>Satisfied by:</span>{' '}
                          {readableInterventions.length > 0 ? readableInterventions.join(', ') : 'None recorded'}
                        </div>
                        {!satisfied && selectedEpisode.composite_note && (
                          <div>
                            <span style={{ color: '#64748b' }}>Detail:</span> {selectedEpisode.composite_note}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })()}

              {(() => {
                const satisfiedIds = [
                  ...parseViolationIds(selectedEpisode.mandatory_satisfied_constraints),
                  ...parseViolationIds(selectedEpisode.info_satisfied_constraints),
                ].filter(cid => cid !== 'INT-COMPOSITE-01');
                const uniqueSatisfiedIds = [...new Set(satisfiedIds)];
                if (uniqueSatisfiedIds.length === 0) return null;

                return (
                  <div style={{ marginTop: '14px' }}>
                    <h4 style={{ color: '#15803d', borderBottom: '1px solid #dbe4ef', paddingBottom: '5px' }}>Satisfied Constraints</h4>
                    <div className="violation-list">
                      {uniqueSatisfiedIds.map(cid => {
                        const detail = getViolationDetail(cid, selectedEpisode);
                        const def = getConstraintDefinition(cid);
                        return (
                          <div key={cid} style={{ marginBottom: '10px', padding: '8px', background: '#effaf2', border: '1px solid #ccebd4', borderRadius: '4px' }}>
                            <div style={{ color: '#15803d', fontWeight: 'bold', fontSize: '12px' }}>{cid}: {def?.label || 'Unknown rule'}</div>
                            {detail ? (
                              <div style={{ fontSize: '11px', marginTop: '4px' }}>
                                <div><span style={{ color: '#64748b' }}>Current:</span> {detail.actual}</div>
                                <div><span style={{ color: '#64748b' }}>Expected:</span> {detail.expected}</div>
                                {detail.observedAt && <div><span style={{ color: '#64748b' }}>Observed at:</span> {detail.observedAt}</div>}
                              </div>
                            ) : <div style={{ fontSize: '11px', marginTop: '4px', color: '#64748b' }}>No details available.</div>}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })()}
            </div>
          ) : (
            <div style={{ textAlign: 'center', color: '#64748b', marginTop: '40px' }}>Select an episode to view details</div>
          )}
        </div>
      </div>

      <div className="legend" style={{ marginTop: '20px', display: 'flex', gap: '20px', justifyContent: 'center' }}>
        <div className="legend-item"><div className="legend-color" style={{ background: '#e91e63' }}></div><span>Invasive Ventilation (Full Support)</span></div>
        <div className="legend-item"><div className="legend-color" style={{ background: '#2196f3' }}></div><span>SBT Trial</span></div>
        <div className="legend-item"><div className="legend-color" style={{ background: '#ffeb3b' }}></div><span>Measurement</span></div>
        <div className="legend-item"><div className="legend-color" style={{ background: '#4caf50' }}></div><span>Conforming</span></div>
        <div className="legend-item"><div className="legend-color" style={{ background: '#ff5722' }}></div><span>Violation</span></div>
      </div>
    </div>
  );
};

export default Timeline;
