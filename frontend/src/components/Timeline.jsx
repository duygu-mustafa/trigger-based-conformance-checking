import React, { useState } from 'react';
import clockIcon from '../static/clock.svg';
import controlFlowIcon from '../static/control_flow.svg';
import dataIcon from '../static/data.svg';

const getConstraintIcon = (cid) => {
  if (cid.includes('-DP-')) return dataIcon;
  if (cid.includes('-TM-')) return clockIcon;
  if (cid.includes('-CF-') || cid.includes('COMPOSITE')) return controlFlowIcon;
  return controlFlowIcon;
};

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

  const totalHours = duration / (1000 * 60 * 60);
  // Calculate optimal step to maintain ~80px spacing between labels
  const possibleSteps = [6, 12, 24, 48, 72, 96, 168];
  const idealStep = (80 * totalHours) / chartWidth;
  const tickStep = possibleSteps.find(s => s >= idealStep) || 168;

  const formatAxisTick = (hours) => {
    if (hours === 0) return '0h';
    if (totalHours < 72) return `${hours}h`;

    if (hours >= 168) {
      const weeks = hours / 168;
      return Number.isInteger(weeks) ? `${weeks}w` : `${weeks.toFixed(1)}w`;
    }

    const days = hours / 24;
    return Number.isInteger(days) ? `${days}d` : `${days.toFixed(1)}d`;
  };

  const timeTicks = [];
  for (let h = 0; h <= totalHours; h += tickStep) {
    timeTicks.push(h);
  }
  // Always include the last hour if it's not already there and there's space
  const lastTick = timeTicks[timeTicks.length - 1];
  if (totalHours - lastTick > tickStep / 2) {
    timeTicks.push(Math.round(totalHours));
  }

  const getX = (timestamp) => {
    const time = new Date(timestamp).getTime();
    return paddingLeft + ((time - minTime) / duration) * chartWidth;
  };

  const getHours = (timestamp) => {
    const time = new Date(timestamp).getTime();
    return (time - minTime) / (1000 * 60 * 60);
  };

  const highlightedMeasurementSeries = [
    {
      id: 'respiratory-rate',
      label: 'Respiratory Rate',
      color: 'var(--color-meas)',
      activities: ['Respiratory Rate'],
    },
    {
      id: 'heart-rate',
      label: 'Heart Rate',
      color: '#1d4ed8',
      activities: ['Heart Rate'],
    },
  ];

  const respiratoryRateThresholdBands = [
    { min: 0, max: 8, color: 'rgba(239, 68, 68, 0.18)', label: 'Danger' },
    { min: 8, max: 12, color: 'rgba(245, 158, 11, 0.18)', label: 'Transition' },
    { min: 12, max: 22, color: 'rgba(34, 197, 94, 0.18)', label: 'Sweet Spot' },
    { min: 22, max: 30, color: 'rgba(245, 158, 11, 0.18)', label: 'Transition' },
    { min: 30, max: Number.POSITIVE_INFINITY, color: 'rgba(239, 68, 68, 0.18)', label: 'Danger' },
  ];

  const heartRateThresholdBands = [
    { min: 0, max: 50, color: 'rgba(239, 68, 68, 0.18)', label: 'Danger' },
    { min: 50, max: 60, color: 'rgba(245, 158, 11, 0.18)', label: 'Transition' },
    { min: 60, max: 100, color: 'rgba(34, 197, 94, 0.18)', label: 'Sweet Spot' },
    { min: 100, max: 120, color: 'rgba(245, 158, 11, 0.18)', label: 'Transition' },
    { min: 120, max: Number.POSITIVE_INFINITY, color: 'rgba(239, 68, 68, 0.18)', label: 'Danger' },
  ];

  const highlightedMeasurementRows = highlightedMeasurementSeries.map((series) => {
    const points = events
      .filter((event) => series.activities.includes(event.activity))
      .map((event) => {
        const numericValue = Number(event.value_num ?? event.value_raw);
        if (!Number.isFinite(numericValue)) return null;
        return { ...event, numericValue };
      })
      .filter(Boolean)
      .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

    const values = points.map(point => point.numericValue);
    const observedMaxValue = values.length > 0 ? Math.max(...values) : 45;
    const domainMin = 0;
    const domainMax = series.id === 'respiratory-rate'
      ? Math.max(45, observedMaxValue)
      : series.id === 'heart-rate'
        ? Math.max(180, observedMaxValue)
      : (values.length > 0 ? observedMaxValue : 1);

    const thresholdBands = series.id === 'respiratory-rate'
      ? respiratoryRateThresholdBands
      : series.id === 'heart-rate'
        ? heartRateThresholdBands
      : [];

    return { ...series, points, domainMin, domainMax, thresholdBands };
  });

  const measurementRowCount = highlightedMeasurementRows.length;

  const getMeasurementY = (value, minValue, maxValue, top, bottom) => {
    if (minValue == null || maxValue == null) return (top + bottom) / 2;
    if (minValue === maxValue) return (top + bottom) / 2;

    const ratio = (value - minValue) / (maxValue - minValue);
    return bottom - (ratio * (bottom - top));
  };

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

  const getMeasurementSeriesColor = (series) => {
    if (series.id === 'respiratory-rate') return '#000000';
    return series.color;
  };

  const getMeasurementSeriesLabelLines = (series) => {
    if (series.id === 'respiratory-rate') return ['Respiratory', 'Rate'];
    if (series.id === 'heart-rate') return ['Heart', 'Rate'];
    return [series.label];
  };

  const parseViolationIds = (value) => {
    if (!value || typeof value !== 'string') return [];
    return value.split(';').map(v => v.trim()).filter(Boolean);
  };

  const parseCompositeInterventions = (value) => {
    if (!value || typeof value !== 'string') return [];
    return value.split(';').map(v => v.trim()).filter(Boolean);
  };

  const getVacuousDetail = (cid, episode) => {
    const detail = getViolationDetail(cid, episode);
    const actualText = detail?.actual;

    const hasAnyObservedValue = (() => {
      if (!actualText || typeof actualText !== 'string') return false;
      const parts = actualText.split(',').map(p => p.trim()).filter(Boolean);
      if (parts.length === 0) return false;

      const values = parts.map((part) => {
        const eqIdx = part.indexOf('=');
        return (eqIdx >= 0 ? part.slice(eqIdx + 1) : part).trim().toLowerCase();
      });

      return values.some((value) => value !== 'n/a' && value !== 'not available');
    })();

    return {
      actual: hasAnyObservedValue ? actualText : 'No data in the observation window',
      expected: detail?.expected || 'See rule definition',
      observedAt: detail?.observedAt || null,
    };
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

  const getStatusBadgeStyle = (status) => {
    if (status === 'Violated') {
      return {
        color: 'var(--color-error-text)',
        background: 'var(--color-violation-bg)',
        border: '1px solid var(--color-violation-bg-hover)',
      };
    }
    if (status === 'Satisfied') {
      return {
        color: 'var(--color-satisfied-text)',
        background: 'var(--color-success-bg)',
        border: '1px solid var(--color-success-bg-hover)',
      };
    }
    return {
      color: 'var(--color-accent)',
      background: 'var(--color-neutral-bg)',
      border: '1px solid var(--color-border-light)',
    };
  };

  const renderStatusBadge = (status) => {
    const style = getStatusBadgeStyle(status);
    return (
      <span
        style={{
          ...style,
          borderRadius: '999px',
          padding: '2px 8px',
          fontSize: '10px',
          fontWeight: '700',
          textTransform: 'uppercase',
          letterSpacing: '0.02em',
          whiteSpace: 'nowrap',
        }}
      >
        {status}
      </span>
    );
  };

  const formatMeasurement = (event, suffix = '') => {
    if (!event) return 'N/A';
    const raw = event.value_num ?? event.value_raw;
    const unit = event.unit ? ` ${event.unit}` : '';
    return raw == null ? 'N/A' : `${raw}${unit}${suffix}`;
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
      return { actual, expected: 'PaO2/FiO2 >= 150 OR (SpO2 >= 90% AND FiO2 <= 40% AND PEEP <= 5)', observedAt: ratio?.timestamp || spo2?.timestamp || fio2?.timestamp || peep?.timestamp || null };
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
        actual: `RASS LOC=${formatMeasurement(cam)}, SAS=${formatMeasurement(sas)}`,
        expected: "RASS LOC = 'No' OR SAS in [3, 4]",
        observedAt: cam?.timestamp || sas?.timestamp || null,
      };
    }
    if (cid === 'RC-DP-07') {
      const latest = latestItemBefore([224686], episode.sbt_start, 24);
      return { actual: formatMeasurement(latest), expected: 'Spontaneous tidal volume > 0 mL', observedAt: latest?.timestamp || null };
    }
    if (cid === 'SBT-TM-01' || cid === 'SBT-TM-01-early' || cid === 'SBT-TM-01-late') {
      const expected = {
        'SBT-TM-01': 'Next SBT on the calendar day after the failed SBT',
        'SBT-TM-01-early': 'Next SBT not on the same calendar day as the failed SBT',
        'SBT-TM-01-late': 'Next SBT no later than the calendar day after the failed SBT',
      }[cid];
      const failure = findNext(events.filter(e => e.activity === 'SBTFailed'), episode.sbt_start || episode.episode_start);
      if (!failure) return { actual: 'No SBT failure in this episode', expected };
      const nextStart = findNext(events.filter(e => e.activity === 'SBTStarted'), failure.timestamp);
      if (!nextStart) return { actual: 'No later SBT start', expected, observedAt: failure.timestamp };
      const dayOf = (ts) => Date.UTC(...String(ts).slice(0, 10).split('-').map((v, i) => Number(v) - (i === 1 ? 1 : 0)));
      const dayDiff = Math.round((dayOf(nextStart.timestamp) - dayOf(failure.timestamp)) / (24 * 60 * 60 * 1000));
      return {
        actual: dayDiff === 0 ? 'Next SBT on the same calendar day' : `Next SBT ${dayDiff} calendar day(s) later`,
        expected,
        observedAt: nextStart.timestamp,
      };
    }
    if (cid === 'SBT-TM-02') {
      // The checker measures hours_since_stay_start from the first event of the evaluation trace (the episode start).
      const actualH = episode.sbt_start ? getHours(episode.sbt_start) - getHours(episode.episode_start) : null;
      return {
        actual: typeof actualH === 'number' ? `SBT ${actualH.toFixed(1)}h after episode start` : 'No SBT start',
        expected: 'SBT within 72h of stay start',
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
            {hoveredEvent.timestamps && (
              <div style={{ fontSize: '12px', marginTop: '2px', color: 'var(--color-text-muted)' }}>{hoveredEvent.timestamps}</div>
            )}
          </div>
        ) : (
          <div className="tooltip-placeholder">Hover over bars or measurements for details • Click an episode for report</div>
        )}
      </div>

      <div className="main-layout">
        <div className="chart-area">
          <div className="chart-sticky-header">
            <svg viewBox={`0 0 ${width} ${paddingTop + rowHeight * measurementRowCount + 20}`} className="timeline-svg timeline-svg-pinned">
              <rect
                x={0}
                y={0}
                width={width}
                height={paddingTop + rowHeight * measurementRowCount + 20}
                fill="var(--color-bg-card)"
              />

              {/* Time Axis */}
              <line x1={paddingLeft} y1={paddingTop - 10} x2={width - paddingRight} y2={paddingTop - 10} stroke="var(--color-text-muted)" strokeWidth="2" />
              {timeTicks.map(h => {
                const time = minTime + h * 60 * 60 * 1000;
                if (time > maxTime) return null;
                const x = getX(time);
                return (
                  <g key={h}>
                    <line x1={x} y1={paddingTop - 15} x2={x} y2={paddingTop - 5} stroke="var(--color-text-muted)" strokeWidth="2" />
                    <text x={x} y={paddingTop - 25} textAnchor="middle" fill="var(--color-text-muted)" fontSize="11" fontWeight="bold">{formatAxisTick(h)}</text>
                  </g>
                );
              })}

              {/* Highlighted Measurements */}
              {highlightedMeasurementRows.map((series, seriesIndex) => {
                const y = paddingTop + 10 + seriesIndex * rowHeight;
                const rowTop = y + 18;
                const rowBottom = y + rowHeight - 24;
                const path = series.points
                  .map((point, pointIndex) => {
                    const x = getX(point.timestamp);
                    const pointY = getMeasurementY(point.numericValue, series.domainMin, series.domainMax, rowTop, rowBottom);
                    return `${pointIndex === 0 ? 'M' : 'L'} ${x} ${pointY}`;
                  })
                  .join(' ');

                return (
                  <g key={series.id}>
                    <rect x={paddingLeft} y={y} width={chartWidth + paddingRight} height={rowHeight - 15} fill="var(--color-neutral-bg)" rx={6} opacity={1} />

                    {series.thresholdBands.map((band, bandIndex) => {
                      const clampedMin = Math.max(series.domainMin, band.min);
                      const clampedMax = Number.isFinite(band.max)
                        ? Math.min(series.domainMax, band.max)
                        : series.domainMax;

                      if (clampedMax <= clampedMin) return null;

                      const yTop = getMeasurementY(clampedMax, series.domainMin, series.domainMax, rowTop, rowBottom);
                      const yBottom = getMeasurementY(clampedMin, series.domainMin, series.domainMax, rowTop, rowBottom);

                      return (
                        <rect
                          key={`${series.id}-band-${bandIndex}`}
                          x={paddingLeft}
                          y={yTop}
                          width={chartWidth + paddingRight}
                          height={Math.max(1, yBottom - yTop)}
                          fill={band.color}
                          pointerEvents="none"
                        />
                      );
                    })}

                    <line x1={paddingLeft} y1={y + rowHeight - 10} x2={width} y2={y + rowHeight - 10} stroke="var(--color-border)" strokeDasharray="4 4" />
                    <text x={paddingLeft - 15} y={y + 38} textAnchor="end" fill="var(--color-text-main)" fontSize="12" fontWeight="bold">
                      {getMeasurementSeriesLabelLines(series).map((line, lineIndex) => (
                        <tspan key={`${series.id}-label-${lineIndex}`} x={paddingLeft - 15} dy={lineIndex === 0 ? '0' : '14'}>{line}</tspan>
                      ))}
                    </text>

                    {series.points.length > 0 ? (
                      <>
                        {series.points.length > 1 && (
                          <path d={path} fill="none" stroke={getMeasurementSeriesColor(series)} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.85" />
                        )}
                        {series.points.map((point, pointIndex) => {
                          const x = getX(point.timestamp);
                          const pointY = getMeasurementY(point.numericValue, series.domainMin, series.domainMax, rowTop, rowBottom);
                          return (
                            <circle
                              key={`${series.id}-${point.timestamp}-${pointIndex}`}
                              cx={x}
                              cy={pointY}
                              r={2}
                              fill={getMeasurementSeriesColor(series)}
                              stroke="var(--color-bg-card)"
                              strokeWidth="1"
                              className="event-marker"
                              onMouseEnter={() => setHoveredEvent({
                                label: series.label,
                                value: formatMeasurement(point),
                                timestamps: new Date(point.timestamp).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
                              })}
                              onMouseLeave={() => setHoveredEvent(null)}
                            />
                          );
                        })}
                      </>
                    ) : (
                      <text x={(paddingLeft + width - paddingRight) / 2} y={y + 54} textAnchor="middle" fill="var(--color-text-muted)" fontSize="11">
                        {`No ${series.label.toLowerCase()} measurements`}
                      </text>
                    )}
                  </g>
                );
              })}

              {/* Episode Boundary Guidelines (Header) */}
              {conformance.map((episode, i) => {
                const xStart = getX(episode.episode_start);
                const xEnd = getX(episode.episode_end);
                return (
                  <g key={`guide-pinned-${i}`} style={{ pointerEvents: 'none' }}>
                    <line
                      x1={xStart} y1={paddingTop - 10} x2={xStart} y2={paddingTop + rowHeight * measurementRowCount + 20}
                      stroke="var(--color-text-muted)" strokeDasharray="4 4" opacity={0.15}
                    />
                    <line
                      x1={xEnd} y1={paddingTop - 10} x2={xEnd} y2={paddingTop + rowHeight * measurementRowCount + 20}
                      stroke="var(--color-text-muted)" strokeDasharray="4 4" opacity={0.15}
                    />
                  </g>
                );
              })}
            </svg>
          </div>

          <svg viewBox={`0 0 ${width} ${paddingTop + rowHeight * (conformance.length + 1)}`} className="timeline-svg timeline-svg-body">
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
                ? (isSelected ? 'var(--color-success-bg-hover)' : 'var(--color-success-bg)')
                : outcomeStatus === 'failure'
                  ? (isSelected ? 'var(--color-violation-bg-hover)' : 'var(--color-violation-bg)')
                  : (isSelected ? 'var(--color-neutral-bg-hover)' : 'var(--color-neutral-bg)');

              const ventEndX = sbtX || xEnd;

              return (
                <g key={`episode-${i}`} onClick={() => setSelectedEpisode(episode)} style={{ cursor: 'pointer' }}>
                  <rect x={paddingLeft} y={y} width={chartWidth + paddingRight} height={rowHeight - 15} fill={rowFill} rx={6} opacity={1} />

                  <line x1={paddingLeft} y1={y + rowHeight - 10} x2={width - paddingRight} y2={y + rowHeight - 10} stroke="var(--color-border)" strokeDasharray="4 4" />
                  <text x={paddingLeft - 15} y={y + 45} textAnchor="end" fill={isSelected ? 'var(--color-text-main)' : 'var(--color-text-muted)'} fontSize="12" fontWeight={isSelected ? 'bold' : 'normal'}>Ep {episode.episode_index}</text>

                  <rect
                    x={xStart}
                    y={y + 15}
                    width={Math.max(2, ventEndX - xStart)}
                    height={25}
                    fill="var(--color-vent)"
                    opacity={0.6}
                    rx={4}
                    onMouseEnter={() => {
                      const ventEnd = episode.sbt_start || episode.episode_end;
                      const durationH = ((new Date(ventEnd) - new Date(episode.episode_start)) / (1000 * 60 * 60)).toFixed(1);
                      const fmt = (ts) => new Date(ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                      setHoveredEvent({
                        activity: 'Invasive Ventilation',
                        value: `Full Support for ${durationH}h`,
                        timestamps: `${fmt(episode.episode_start)} → ${fmt(ventEnd)}`,
                      });
                    }}
                    onMouseLeave={() => setHoveredEvent(null)}
                  />

                  {sbtX && sbtEndX && (
                    <rect
                      x={sbtX}
                      y={y + 15}
                      width={Math.max(6, sbtEndX - sbtX)}
                      height={25}
                      fill="var(--color-sbt)"
                      rx={4}
                      onMouseEnter={() => {
                        const durationMin = ((new Date(episode.sbt_end) - new Date(episode.sbt_start)) / (1000 * 60)).toFixed(0);
                        const fmt = (ts) => new Date(ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                        setHoveredEvent({
                          activity: 'SBT Attempt',
                          value: `${episode.sbt_outcome} — ${durationMin} min`,
                          timestamps: `${fmt(episode.sbt_start)} → ${fmt(episode.sbt_end)}`,
                        });
                      }}
                      onMouseLeave={() => setHoveredEvent(null)}
                    />
                  )}

                  <g>
                    <circle cx={xStart + 15} cy={y + 60} r={7} fill={isViolated ? 'var(--color-violation)' : 'var(--color-success)'} />
                    {isViolated && (
                      <text x={xStart + 30} y={y + 65} fill="var(--color-violation)" fontSize="11" fontWeight="bold">
                        {episode.num_mandatory_violations} violations
                      </text>
                    )}

                  </g>
                </g>
              );
            })}

            {/* Episode Boundary Guidelines (Above bars) */}
            {conformance.map((episode, i) => {
              const xStart = getX(episode.episode_start);
              const xEnd = getX(episode.episode_end);
              return (
                <g key={`guide-${i}`} style={{ pointerEvents: 'none' }}>
                  <line
                    x1={xStart} y1={0} x2={xStart} y2={paddingTop + rowHeight * conformance.length}
                    stroke="var(--color-text-muted)" strokeDasharray="4 4" opacity={0.15}
                  />
                  <line
                    x1={xEnd} y1={0} x2={xEnd} y2={paddingTop + rowHeight * conformance.length}
                    stroke="var(--color-text-muted)" strokeDasharray="4 4" opacity={0.15}
                  />
                </g>
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

              <h4 style={{ color: 'var(--color-error-text)', paddingBottom: '5px' }}>Violations</h4>
              {selectedEpisode.mandatory_violated_constraints ? (
                <div className="violation-list">
                  {parseViolationIds(selectedEpisode.mandatory_violated_constraints).map(cid => {
                    if (cid === 'INT-COMPOSITE-01') return null;
                    const detail = getViolationDetail(cid, selectedEpisode);
                    const def = getConstraintDefinition(cid);
                    return (
                      <div key={cid} style={{ marginBottom: '10px', padding: '8px', background: '#ffffff', border: '1px solid var(--color-border-light)', borderRadius: '4px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-error-text)', fontWeight: 'bold', fontSize: '12px' }}>
                            <img src={getConstraintIcon(cid)} alt="constraint icon" style={{ width: '20px', height: '20px', opacity: 0.8 }} />
                            <span>{cid}: {def?.label || 'Unknown rule'}</span>
                          </div>
                          {renderStatusBadge('Violated')}
                        </div>
                        {detail ? (
                          <div style={{ fontSize: '11px', marginTop: '4px' }}>
                            <div><span style={{ color: 'var(--color-text-muted)' }}>Current:</span> {detail.actual}</div>
                            <div><span style={{ color: 'var(--color-text-muted)' }}>Expected:</span> {detail.expected}</div>
                            {detail.observedAt && <div><span style={{ color: 'var(--color-text-muted)' }}>Observed at:</span> {detail.observedAt}</div>}
                          </div>
                        ) : <div style={{ fontSize: '11px', marginTop: '4px', color: 'var(--color-text-muted)' }}>No details available.</div>}
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
                    <h4 style={{ color: 'var(--color-accent)', paddingBottom: '5px' }}>Composite Failure Intervention Check</h4>
                    <div style={{ marginBottom: '10px', padding: '8px', background: '#ffffff', border: '1px solid var(--color-border-light)', borderRadius: '4px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-accent)', fontWeight: 'bold', fontSize: '12px' }}>
                          <img src={getConstraintIcon(compositeRuleId)} alt="constraint icon" style={{ width: '20px', height: '20px', opacity: 0.8 }} />
                          <span>{compositeRuleId}: {getConstraintDefinition(compositeRuleId)?.label || 'At least one failure intervention must occur after SBT failure'}</span>
                        </div>
                        {renderStatusBadge(satisfied ? 'Satisfied' : 'Violated')}
                      </div>
                      <div style={{ fontSize: '11px', marginTop: '4px' }}>
                        <div>
                          <span style={{ color: 'var(--color-text-muted)' }}>Status:</span> {satisfied ? 'Satisfied' : 'Violated'}
                        </div>
                        <div>
                          <span style={{ color: 'var(--color-text-muted)' }}>Expected:</span> At least one qualifying intervention/test within 24h after SBT failure
                        </div>
                        <div>
                          <span style={{ color: 'var(--color-text-muted)' }}>Satisfied by:</span>{' '}
                          {readableInterventions.length > 0 ? readableInterventions.join(', ') : 'None recorded'}
                        </div>
                        {!satisfied && selectedEpisode.composite_note && (
                          <div>
                            <span style={{ color: 'var(--color-text-muted)' }}>Detail:</span> {selectedEpisode.composite_note}
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
                    <h4 style={{ color: 'var(--color-satisfied-text)', paddingBottom: '5px' }}>Satisfied Constraints</h4>
                    <div className="violation-list">
                      {uniqueSatisfiedIds.map(cid => {
                        const detail = getViolationDetail(cid, selectedEpisode);
                        const def = getConstraintDefinition(cid);
                        return (
                          <div key={cid} style={{ marginBottom: '10px', padding: '8px', background: '#ffffff', border: '1px solid var(--color-border-light)', borderRadius: '4px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-satisfied-text)', fontWeight: 'bold', fontSize: '12px' }}>
                                <img src={getConstraintIcon(cid)} alt="constraint icon" style={{ width: '20px', height: '20px', opacity: 0.8 }} />
                                <span>{cid}: {def?.label || 'Unknown rule'}</span>
                              </div>
                              {renderStatusBadge('Satisfied')}
                            </div>
                            {detail ? (
                              <div style={{ fontSize: '11px', marginTop: '4px' }}>
                                <div><span style={{ color: 'var(--color-text-muted)' }}>Current:</span> {detail.actual}</div>
                                <div><span style={{ color: 'var(--color-text-muted)' }}>Expected:</span> {detail.expected}</div>
                                {detail.observedAt && <div><span style={{ color: 'var(--color-text-muted)' }}>Observed at:</span> {detail.observedAt}</div>}
                              </div>
                            ) : <div style={{ fontSize: '11px', marginTop: '4px', color: 'var(--color-text-muted)' }}>No details available.</div>}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })()}

              {(() => {
                const vacuousIds = [
                  ...parseViolationIds(selectedEpisode.mandatory_vacuous_constraints),
                  ...parseViolationIds(selectedEpisode.info_vacuous_constraints),
                ].filter(cid => cid !== 'INT-COMPOSITE-01');
                const uniqueVacuousIds = [...new Set(vacuousIds)];
                if (uniqueVacuousIds.length === 0) return null;

                return (
                  <div style={{ marginTop: '14px' }}>
                    <h4 style={{ color: 'var(--color-accent)', paddingBottom: '5px' }}>Vacuously Satisfied (No Data in Window)</h4>
                    <div className="violation-list">
                      {uniqueVacuousIds.map(cid => {
                        const detail = getVacuousDetail(cid, selectedEpisode);
                        const def = getConstraintDefinition(cid);
                        return (
                          <div key={cid} style={{ marginBottom: '10px', padding: '8px', background: '#ffffff', border: '1px solid var(--color-border-light)', borderRadius: '4px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-accent)', fontWeight: 'bold', fontSize: '12px' }}>
                                <img src={getConstraintIcon(cid)} alt="constraint icon" style={{ width: '20px', height: '20px', opacity: 0.8 }} />
                                <span>{cid}: {def?.label || 'Unknown rule'}</span>
                              </div>
                              {renderStatusBadge('Vacuous')}
                            </div>
                            <div style={{ fontSize: '11px', marginTop: '4px' }}>
                              <div><span style={{ color: 'var(--color-text-muted)' }}>Status:</span> Vacuous</div>
                              <div><span style={{ color: 'var(--color-text-muted)' }}>Current:</span> {detail.actual}</div>
                              <div><span style={{ color: 'var(--color-text-muted)' }}>Expected:</span> {detail.expected}</div>
                              {detail.observedAt && <div><span style={{ color: 'var(--color-text-muted)' }}>Observed at:</span> {detail.observedAt}</div>}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })()}
            </div>
          ) : (
            <div style={{ textAlign: 'center', color: 'var(--color-text-muted)', marginTop: '40px' }}>Select an episode to view details</div>
          )}
        </div>
      </div>

      <div className="legend" style={{ marginTop: '20px', display: 'flex', gap: '20px', justifyContent: 'center' }}>
        <div className="legend-item"><div className="legend-color" style={{ background: 'var(--color-vent)' }}></div><span>Invasive Ventilation</span></div>
        <div className="legend-item"><div className="legend-color" style={{ background: 'var(--color-sbt)' }}></div><span>SBT Trial</span></div>
        <div className="legend-item"><div className="legend-color" style={{ background: 'var(--color-success)' }}></div><span>Expected SBT Start Window</span></div>
        <div className="legend-item"><div className="legend-color" style={{ background: 'var(--color-violation)' }}></div><span>Violation</span></div>
        {highlightedMeasurementRows.map(series => (
          <div key={series.id} className="legend-item"><div className="legend-color" style={{ background: getMeasurementSeriesColor(series) }}></div><span>{series.label}</span></div>
        ))}
      </div>
    </div>
  );
};

export default Timeline;
