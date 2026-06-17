import { useState, useEffect, useRef } from 'react'

const SAMPLE_PRESETS = [10, 25, 50, 100, 200]

function KpiCard({ label, value, sub }) {
  return (
    <div className="kpi-card">
      <span className="kpi-value">{value}</span>
      <span className="kpi-label">{label}</span>
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  )
}

function ViolationBar({ label, share, maxShare }) {
  const w = maxShare > 0 ? (share / maxShare) * 100 : 0
  return (
    <div className="vbar-row">
      <span className="vbar-label" title={label}>{label}</span>
      <div className="vbar-tracks">
        <div className="vbar-track vbar-track--run" title={`${(share * 100).toFixed(1)}%`}>
          <div className="vbar-fill vbar-fill--run" style={{ width: `${w}%` }} />
        </div>
      </div>
      <span className="vbar-val vbar-val--run">{(share * 100).toFixed(0)}%</span>
    </div>
  )
}

export default function AnalysisRunner({ customRules = [], onOpenTimeline }) {
  const [sampleSize, setSampleSize] = useState(50)
  const [seed, setSeed] = useState(42)
  const [triggerEvent, setTriggerEvent] = useState('InvasiveVentilationStarted')
  const [includePredefined, setIncludePredefined] = useState(true)
  const [includeCustom, setIncludeCustom] = useState(true)
  const [jobId, setJobId] = useState(null)
  const [jobState, setJobState] = useState(null)
  const pollRef = useRef(null)

  const savedRules = (() => {
    try { return JSON.parse(localStorage.getItem('studio_custom_rules') || '[]') }
    catch { return [] }
  })()
  const allCustomRules = [...customRules, ...savedRules]

  async function startRun() {
    setJobState({ status: 'running', progress: 0, total: sampleSize, done: 0, result: null, error: null })
    setJobId(null)

    const body = {
      sample_size: sampleSize,
      seed,
      trigger_event: triggerEvent,
      include_predefined: includePredefined,
      custom_rules: includeCustom ? allCustomRules.map(r => ({
        id: r.id,
        label: r.label,
        template: r.template,
        activation: r.activation,
        target: r.target || null,
        min_gap_hours: r.min_gap_hours || null,
        max_gap_hours: r.max_gap_hours || null,
        activation_conditions: r.activation_conditions || [],
        activation_logic: r.activation_logic || 'AND',
        correlation_conditions: r.correlation_conditions || [],
        correlation_logic: r.correlation_logic || 'AND',
        activation_condition_expr: r.activation_condition_expr || null,
        correlation_condition_expr: r.correlation_condition_expr || null,
        rationale: r.rationale || '',
      })) : [],
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
  const maxRunShare = Math.max(...runViolations.map(v => v.episode_share || 0), 0.01)

  const topRunViolations = [...runViolations]
    .sort((a, b) => (b.episode_share || 0) - (a.episode_share || 0))
    .slice(0, 15)

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
          <h3 className="runner-results-title">Run Results — n={sampleSize}</h3>

          <div className="kpi-cards" style={{ display: 'flex', gap: '1rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            <KpiCard label="Episodes analysed" value={runEpisodes} />
            <KpiCard
              label="Top violation"
              value={runViolations.length > 0 ? `${(runViolations[0].episode_share * 100).toFixed(0)}%` : '—'}
              sub={runViolations[0]?.constraint_label || runViolations[0]?.constraint_id}
            />
            <KpiCard
              label="Constraints checked"
              value={runViolations.length > 0 ? runViolations.length : '—'}
            />
          </div>

          {topRunViolations.length > 0 && (
            <div className="vbar-section">
              <h4 className="runner-section-heading">Violation Frequencies — This Run</h4>
              <div className="vbar-list">
                {topRunViolations.map(row => (
                  <ViolationBar
                    key={row.constraint_id}
                    label={row.constraint_label || row.constraint_id}
                    share={row.episode_share || 0}
                    maxShare={maxRunShare}
                  />
                ))}
              </div>
            </div>
          )}

          {result.stay_summaries?.length > 0 && (
            <div className="run-stays-section">
              <h4 className="run-stays-title">Episodes in this run</h4>
              <div className="run-stays-table-wrap">
                <table className="run-stays-table">
                  <thead>
                    <tr>
                      <th>Stay ID</th>
                      <th>Outcome</th>
                      <th>Episodes</th>
                      <th>Violations</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.stay_summaries.slice(0, 50).map(stay => (
                      <tr key={stay.stay_id}>
                        <td className="stay-id-cell">{stay.stay_id}</td>
                        <td>
                          <span className={`outcome-badge outcome-badge--${String(stay.overall_outcome || '').toLowerCase().replace(/\s/g, '-')}`}>
                            {stay.overall_outcome || '—'}
                          </span>
                        </td>
                        <td>{stay.episodes ?? '—'}</td>
                        <td>{stay.total_mandatory_violations ?? '—'}</td>
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
            </div>
          )}
        </div>
      )}
    </div>
  )
}
