import { useState, useEffect, useRef } from 'react'
import { getConstraintIcon, formatPercent } from '../SummaryView/utils'
import StatsDeepDive from '../SummaryView/StatsDeepDive'
import ContrastBarChart from '../SummaryView/ContrastBarChart'
import OutcomeScatterPlot from '../SummaryView/OutcomeScatterPlot'
import ConstraintDetailView from '../SummaryView/ConstraintDetailView'
import UploadedLogRunner from '../UploadView/UploadedLogRunner'
import { rulesKey } from '../../datasetRules'

const SAMPLE_PRESETS = [10, 25, 50, 100, 200]
const RESULT_TABS = ['Frequencies', 'Statistics', 'Patients']

function KpiCard({ label, value, sub }) {
  return (
    <div className="kpi-card">
      <span className="kpi-value">{value}</span>
      <span className="kpi-label">{label}</span>
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  )
}

function RunConstraintRow({ item, selected, onSelect }) {
  const icon = getConstraintIcon(item.constraint_id)
  const pct = ((item.episode_share || 0) * 100).toFixed(1)
  const cls = item.rule_class || 'neutral'

  return (
    <div
      className={`run-constraint-row ${selected ? 'run-constraint-row--selected' : ''}`}
      onClick={() => onSelect(item.constraint_id)}
    >
      <div className="run-constraint-row-top">
        {icon && <img className="run-constraint-icon" src={icon} alt="" />}
        <span className="run-constraint-label">{item.constraint_label || item.constraint_id}</span>
        <span className={`run-constraint-class run-constraint-class--${cls}`}>{cls}</span>
      </div>
      <div className="run-constraint-bar-wrap">
        <div className="run-constraint-bar-track">
          <div className="run-constraint-bar-viol" style={{ width: `${((item.violation_rate_failure || 0) * 100).toFixed(1)}%` }} title={`Failure: ${((item.violation_rate_failure || 0) * 100).toFixed(1)}%`} />
          <div className="run-constraint-bar-succ" style={{ width: `${((item.violation_rate_success || 0) * 100).toFixed(1)}%` }} title={`Success: ${((item.violation_rate_success || 0) * 100).toFixed(1)}%`} />
        </div>
        <span className="run-constraint-pct">{pct}%</span>
      </div>
    </div>
  )
}

function loadPersistedResult() {
  try {
    const saved = sessionStorage.getItem('analysis_runner_result')
    return saved ? JSON.parse(saved) : null
  } catch { return null }
}

export default function AnalysisRunner({ customRules = [], onOpenTimeline, uploadInfo = null, datasetId = 'builtin', onUploadStale }) {
  if (uploadInfo) {
    return <UploadedLogRunner uploadInfo={uploadInfo} datasetId={datasetId} onStale={onUploadStale} />
  }

  const [sampleSize, setSampleSize] = useState(() => {
    try { return JSON.parse(localStorage.getItem('analysis_runner_sample_size') || '50') } catch { return 50 }
  })
  const [seed, setSeed] = useState(42)
  const [triggerEvent, setTriggerEvent] = useState('InvasiveVentilationStarted')
  const [episodeWindowHours, setEpisodeWindowHours] = useState('')
  const [episodeEndEvent, setEpisodeEndEvent] = useState('')
  const [includePredefined, setIncludePredefined] = useState(true)
  const [includeCustom, setIncludeCustom] = useState(true)
  const [jobId, setJobId] = useState(null)
  const [jobState, setJobState] = useState(loadPersistedResult)
  const [activeTab, setActiveTab] = useState('Frequencies')
  const [selectedConstraintId, setSelectedConstraintId] = useState(null)
  const [analysisMode, setAnalysisMode] = useState('violation')
  const [itemLabels, setItemLabels] = useState({})
  const pollRef = useRef(null)

  useEffect(() => {
    fetch('/api/item_labels').then(r => r.ok ? r.json() : {}).then(setItemLabels).catch(() => {})
  }, [])

  useEffect(() => {
    if (jobState?.status === 'done' && jobState?.result) {
      sessionStorage.setItem('analysis_runner_result', JSON.stringify(jobState))
    }
  }, [jobState?.status])

  const savedRules = (() => {
    try { return JSON.parse(localStorage.getItem(rulesKey(datasetId)) || '[]') }
    catch { return [] }
  })()
  const allCustomRules = [...new Map([...customRules, ...savedRules].map(r => [r.id, r])).values()]

  const savedEventTypes = (() => {
    try { return JSON.parse(localStorage.getItem('studio_custom_event_types') || '[]') }
    catch { return [] }
  })()

  const savedDataConditions = (() => {
    try { return JSON.parse(localStorage.getItem('studio_custom_data_conditions') || '[]') }
    catch { return [] }
  })()

  // Deduplicate data items by (source_table, itemid) across all saved conditions
  const customDataItems = (() => {
    const byTable = {}
    for (const cond of savedDataConditions) {
      for (const item of (cond.data_items || [])) {
        const key = item.source_table
        if (!byTable[key]) byTable[key] = new Set()
        byTable[key].add(item.itemid)
      }
    }
    return Object.entries(byTable).map(([source_table, ids]) => ({
      source_table,
      itemids: [...ids],
    }))
  })()

  async function startRun() {
    localStorage.setItem('analysis_runner_sample_size', JSON.stringify(sampleSize))
    sessionStorage.removeItem('analysis_runner_result')
    setJobState({ status: 'running', progress: 0, total: sampleSize, done: 0, result: null, error: null })
    setJobId(null)
    setSelectedConstraintId(null)
    setActiveTab('Frequencies')

    const body = {
      sample_size: sampleSize,
      seed,
      trigger_event: triggerEvent,
      episode_window_hours: episodeWindowHours === '' ? null : parseFloat(episodeWindowHours),
      episode_end_event: episodeEndEvent || null,
      include_predefined: includePredefined,
      custom_rules: includeCustom ? allCustomRules.map(r => ({
        id: r.id,
        label: r.label,
        template: r.template,
        activation: r.activation,
        target: r.target || null,
        min_gap_hours: r.min_gap_hours || null,
        max_gap_hours: r.max_gap_hours || null,
        target_selection: r.target_selection || 'any',
        activation_conditions: r.activation_conditions || [],
        activation_logic: r.activation_logic || 'AND',
        correlation_conditions: r.correlation_conditions || [],
        correlation_logic: r.correlation_logic || 'AND',
        activation_condition_expr: r.activation_condition_expr || null,
        correlation_condition_expr: r.correlation_condition_expr || null,
        rationale: r.rationale || '',
      })) : [],
      custom_event_types: savedEventTypes.map(et => ({
        name: et.name,
        kind: et.kind || 'table',
        source_table: et.source_table || null,
        itemids: et.itemids || [],
        value_filter: et.value_filter || null,
        sql: et.sql || null,
      })),
      custom_data_items: customDataItems,
    }

    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
      setJobState(s => ({ ...s, status: 'error', error: err.detail || String(err) }))
      return
    }
    const { job_id } = await res.json()
    setJobId(job_id)
  }

  useEffect(() => {
    if (!jobId) return
    pollRef.current = setInterval(async () => {
      const res = await fetch(`/api/jobs/${jobId}`)
      if (!res.ok) return
      const data = await res.json()
      setJobState(data)
      if (data.status === 'done' || data.status === 'error' || data.status === 'cancelled') {
        clearInterval(pollRef.current)
      }
    }, 2000)
    return () => clearInterval(pollRef.current)
  }, [jobId])

  async function cancelRun() {
    if (!jobId) return
    await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' })
    setJobState(s => ({ ...s, status: 'cancelling' }))
  }

  const isRunning = jobState?.status === 'running' || jobState?.status === 'cancelling'
  const isDone = jobState?.status === 'done'
  const hasError = jobState?.status === 'error'
  const result = jobState?.result

  const runViolations = result?.violation_frequency || []
  const runEpisodes = result?.total_episodes ?? '—'
  const successEps = result?.conformance_vs_outcome?.success?.episodes ?? 0
  const failureEps = result?.conformance_vs_outcome?.failure?.episodes ?? 0
  const noSbtAttemptEps = result?.conformance_vs_outcome?.no_sbt_attempt?.episodes ?? 0

  const topViolations = [...runViolations]
    .sort((a, b) => (b.episode_share || 0) - (a.episode_share || 0))
    .slice(0, 20)

  const selectedConstraint = runViolations.find(v => v.constraint_id === selectedConstraintId) || runViolations[0] || null

  const progress = isRunning
    ? (jobState.total > 0 ? Math.round((jobState.done / jobState.total) * 100) : 0)
    : isDone ? 100 : 0

  return (
    <div className="analysis-runner">
      <div className="runner-config">
        <h3 className="runner-config-title">Configure analysis run</h3>

        <div className="runner-config-row">
          <div className="runner-field">
            <label className="field-label">Sample size</label>
            <div className="sample-presets">
              {SAMPLE_PRESETS.map(n => (
                <button
                  key={n}
                  type="button"
                  className={`sample-preset-btn ${sampleSize === n ? 'active' : ''}`}
                  onClick={() => setSampleSize(n)}
                >{n}</button>
              ))}
              <input
                className="studio-input sample-custom-input"
                type="number" min="1" max="2000" step="1"
                value={sampleSize}
                onChange={e => setSampleSize(Math.max(1, parseInt(e.target.value) || 1))}
                aria-label="Custom sample size"
              />
            </div>
          </div>

          <div className="runner-field">
            <label className="field-label">Random seed</label>
            <input
              className="studio-input"
              type="number" min="0" step="1"
              value={seed}
              onChange={e => setSeed(parseInt(e.target.value) || 0)}
            />
          </div>

          <div className="runner-field">
            <label className="field-label">Trigger event</label>
            <select
              className="studio-input"
              value={triggerEvent}
              onChange={e => setTriggerEvent(e.target.value)}
            >
              <option value="InvasiveVentilationStarted">Invasive Ventilation Started</option>
              <option value="SBTStarted">SBT Started</option>
              <option value="SBTCompleted">SBT Completed</option>
              <option value="SBTFailed">SBT Failed</option>
              <option value="SBTSucceeded">SBT Succeeded</option>
            </select>
          </div>

          <div className="runner-field">
            <label className="field-label">Episode window (hours)</label>
            <input
              className="studio-input"
              type="number"
              min="0"
              step="1"
              placeholder="unbounded"
              value={episodeWindowHours}
              onChange={e => setEpisodeWindowHours(e.target.value)}
            />
          </div>

          <div className="runner-field">
            <label className="field-label">Episode end event</label>
            <select
              className="studio-input"
              value={episodeEndEvent}
              onChange={e => setEpisodeEndEvent(e.target.value)}
            >
              <option value="">None</option>
              <option value="InvasiveVentilationEnded">Invasive Ventilation Ended</option>
              <option value="SBTStarted">SBT Started</option>
              <option value="SBTCompleted">SBT Completed</option>
              <option value="SBTFailed">SBT Failed</option>
              <option value="SBTSucceeded">SBT Succeeded</option>
            </select>
          </div>
        </div>

        <div className="runner-rules-toggle">
          <label className={`rules-toggle-card ${includePredefined ? 'active' : ''}`}>
            <input type="checkbox" checked={includePredefined} onChange={e => setIncludePredefined(e.target.checked)} />
            <span className="toggle-card-title">Predefined rules</span>
            <span className="toggle-card-count">28 clinical rules</span>
          </label>
          <label className={`rules-toggle-card ${includeCustom ? 'active' : ''}`}>
            <input
              type="checkbox"
              checked={includeCustom}
              onChange={e => setIncludeCustom(e.target.checked)}
              disabled={allCustomRules.length === 0}
            />
            <span className="toggle-card-title">My custom rules</span>
            <span className="toggle-card-count">
              {allCustomRules.length === 0 ? 'None saved yet' : `${allCustomRules.length} rule(s)`}
            </span>
          </label>
          <div className="rules-toggle-card rules-toggle-card--info">
            <span className="toggle-card-title">Custom event types</span>
            <span className="toggle-card-count">
              {savedEventTypes.length === 0 ? 'None defined' : `${savedEventTypes.length} type(s) — always included`}
            </span>
          </div>
        </div>

        <div className="runner-actions">
          {!isRunning ? (
            <button
              className="run-btn"
              type="button"
              onClick={startRun}
              disabled={!includePredefined && allCustomRules.length === 0}
            >
              Run analysis
            </button>
          ) : (
            <button className="cancel-btn" type="button" onClick={cancelRun}>Cancel</button>
          )}
        </div>

        {(isRunning || isDone) && (
          <div className="runner-progress">
            <div className="progress-bar-track">
              <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
            </div>
            <p className="progress-label">
              {isDone
                ? `Done — ${runEpisodes} episodes analysed`
                : `Analysing stays… ${jobState?.done ?? 0} / ${jobState?.total ?? sampleSize}`}
            </p>
            {jobState?.warnings?.length > 0 && (
              <div className="runner-warnings">
                {jobState.warnings.map((w, i) => <p key={i} className="runner-warning">⚠ {w}</p>)}
              </div>
            )}
          </div>
        )}

        {hasError && (
          <div className="runner-error">
            <strong>Error:</strong> {jobState.error}
            {jobState.traceback && (
              <details className="error-traceback">
                <summary>Details</summary>
                <pre>{jobState.traceback}</pre>
              </details>
            )}
          </div>
        )}
      </div>

      {isDone && result && (
        <div className="runner-results">
          <div className="runner-results-header">
            <h3 className="runner-results-title">Run Results — n={sampleSize}</h3>
            <div className="runner-kpis">
              <KpiCard label="Episodes" value={runEpisodes} />
              <KpiCard label="Success" value={successEps} />
              <KpiCard label="Failure" value={failureEps} />
              <KpiCard label="No SBT" value={noSbtAttemptEps} />
              <KpiCard
                label="Top violation"
                value={topViolations.length > 0 ? formatPercent(topViolations[0].episode_share || 0) : '—'}
                sub={topViolations[0]?.constraint_label}
              />
              <KpiCard label="Rules checked" value={runViolations.length || '—'} />
            </div>
          </div>

          <div className="runner-tabs">
            {RESULT_TABS.map(tab => (
              <button
                key={tab}
                type="button"
                className={`runner-tab-btn ${activeTab === tab ? 'active' : ''}`}
                onClick={() => setActiveTab(tab)}
              >{tab}</button>
            ))}
          </div>

          {activeTab === 'Frequencies' && (
            <div className="runner-frequencies">
              <div className="runner-freq-legend">
                <span className="runner-freq-legend-item runner-freq-legend-item--fail">Failure violation rate</span>
                <span className="runner-freq-legend-item runner-freq-legend-item--succ">Success violation rate</span>
              </div>
              <div className="runner-freq-split">
                <div className="runner-freq-list">
                  {topViolations.length === 0 && (
                    <p className="runner-empty">No violations recorded in this run.</p>
                  )}
                  {topViolations.map(item => (
                    <RunConstraintRow
                      key={item.constraint_id}
                      item={item}
                      selected={(selectedConstraintId ?? selectedConstraint?.constraint_id) === item.constraint_id}
                      onSelect={id => setSelectedConstraintId(id === selectedConstraintId ? null : id)}
                    />
                  ))}
                </div>
                {selectedConstraint && (
                  <div className="runner-freq-detail">
                    <ConstraintDetailView
                      constraint={selectedConstraint}
                      itemLabels={itemLabels}
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'Statistics' && (
            <div className="runner-statistics">
              <StatsDeepDive summaryData={result} />

              {runViolations.length > 0 && (
                <div className="runner-correlation-section">
                  <div className="runner-mode-toggle">
                    <button
                      type="button"
                      className={`runner-mode-btn ${analysisMode === 'violation' ? 'active' : ''}`}
                      onClick={() => setAnalysisMode('violation')}
                    >Violations</button>
                    <button
                      type="button"
                      className={`runner-mode-btn ${analysisMode === 'satisfaction' ? 'active' : ''}`}
                      onClick={() => setAnalysisMode('satisfaction')}
                    >Satisfactions</button>
                  </div>
                  <div className="runner-charts-row">
                    <div className="runner-chart-panel">
                      <OutcomeScatterPlot items={runViolations} mode={analysisMode} />
                    </div>
                    <div className="runner-chart-panel runner-chart-panel--bars">
                      <ContrastBarChart items={runViolations} mode={analysisMode} />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'Patients' && (
            <div className="run-stays-section">
              {result.stay_summaries?.length === 0 && (
                <p className="runner-empty">No stay summaries available.</p>
              )}
              {result.stay_summaries?.length > 0 && (
                <div className="run-stays-table-wrap">
                  <table className="run-stays-table">
                    <thead>
                      <tr>
                        <th>Stay ID</th>
                        <th>Outcome</th>
                        <th>Episodes</th>
                        <th>Violations</th>
                        <th>Avg / episode</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.stay_summaries.slice(0, 100).map(stay => (
                        <tr key={stay.stay_id}>
                          <td className="stay-id-cell">{stay.stay_id}</td>
                          <td>
                            <span className={`outcome-badge outcome-badge--${String(stay.overall_outcome || '').toLowerCase().replace(/\s/g, '-')}`}>
                              {stay.overall_outcome || '—'}
                            </span>
                          </td>
                          <td>{stay.episodes ?? '—'}</td>
                          <td>{stay.total_mandatory_violations ?? '—'}</td>
                          <td>{stay.avg_mandatory_violations != null ? stay.avg_mandatory_violations.toFixed(1) : '—'}</td>
                          <td>
                            <button
                              type="button"
                              className="open-timeline-btn"
                              onClick={() => onOpenTimeline?.(String(stay.stay_id))}
                            >
                              View timeline
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
