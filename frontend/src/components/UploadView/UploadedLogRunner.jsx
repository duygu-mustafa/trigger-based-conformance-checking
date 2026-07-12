import { useState } from 'react'
import GenericResults from './GenericResults'
import { loadRules } from '../../datasetRules'

const SAMPLE_PRESETS = [10, 25, 50, 100, 200]

function resultKey(datasetId) {
  return `upload_runner_result_${datasetId}`
}

function loadPersistedResult(datasetId) {
  try {
    const saved = sessionStorage.getItem(resultKey(datasetId))
    return saved ? JSON.parse(saved) : null
  } catch { return null }
}

export default function UploadedLogRunner({ uploadInfo, datasetId, onStale }) {
  const persisted = loadPersistedResult(datasetId)
  const [status, setStatus] = useState(persisted ? 'done' : 'idle') // idle | running | done | error
  const [error, setError] = useState(null)
  const [summary, setSummary] = useState(persisted)
  const [sampleAll, setSampleAll] = useState(true)
  const [sampleSize, setSampleSize] = useState(50)
  const [seed, setSeed] = useState(42)
  const [triggerEvent, setTriggerEvent] = useState('')

  const savedRules = loadRules(datasetId ?? uploadInfo.upload_id ?? uploadInfo.id)
  const activities = uploadInfo.activities || []

  async function runAnalysis() {
    setStatus('running')
    setError(null)
    const custom_rules = savedRules.map(r => ({
      id: r.id,
      label: r.label,
      template: r.template,
      activation: r.activation,
      target: r.target || null,
      min_gap_hours: r.min_gap_hours || null,
      max_gap_hours: r.max_gap_hours || null,
      activation_condition_expr: r.activation_condition_expr || null,
      correlation_condition_expr: r.correlation_condition_expr || null,
      rationale: r.rationale || '',
    }))
    try {
      const res = await fetch('/api/run_uploaded', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          upload_id: uploadInfo.id ?? uploadInfo.upload_id,
          custom_rules,
          sample_size: sampleAll ? null : sampleSize,
          seed,
          trigger_event: triggerEvent || null,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Run failed' }))
        if (res.status === 404) onStale?.()
        throw new Error(err.detail || 'Run failed')
      }
      const data = await res.json()
      setSummary(data)
      setStatus('done')
      try { sessionStorage.setItem(resultKey(datasetId), JSON.stringify(data)) } catch {}
    } catch (e) {
      setError(e.message)
      setStatus('error')
    }
  }

  return (
    <div className="analysis-runner">
      <div className="runner-config">
        <h3 className="runner-config-title">Run conformance on uploaded log</h3>
        <p className="xes-upload-lead">
          {uploadInfo.num_cases} cases · {uploadInfo.num_events} events · {savedRules.length} rule(s) defined
        </p>

        <div className="runner-config-row">
          <div className="runner-field">
            <label className="field-label">Sample size</label>
            <div className="sample-presets">
              <button
                type="button"
                className={`sample-preset-btn ${sampleAll ? 'active' : ''}`}
                onClick={() => setSampleAll(true)}
              >All ({uploadInfo.num_cases})</button>
              {SAMPLE_PRESETS.map(n => (
                <button
                  key={n}
                  type="button"
                  className={`sample-preset-btn ${!sampleAll && sampleSize === n ? 'active' : ''}`}
                  onClick={() => { setSampleAll(false); setSampleSize(n) }}
                >{n}</button>
              ))}
              <input
                className="studio-input sample-custom-input"
                type="number" min="1" max={uploadInfo.num_cases} step="1"
                value={sampleSize}
                onChange={e => { setSampleAll(false); setSampleSize(Math.max(1, parseInt(e.target.value) || 1)) }}
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
              disabled={sampleAll}
            />
          </div>

          <div className="runner-field">
            <label className="field-label">Trigger event (split into episodes)</label>
            <select
              className="studio-input"
              value={triggerEvent}
              onChange={e => setTriggerEvent(e.target.value)}
            >
              <option value="">Whole trace (no split)</option>
              {activities.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
        </div>

        <div className="runner-actions">
          <button
            className="run-btn"
            type="button"
            onClick={runAnalysis}
            disabled={status === 'running' || savedRules.length === 0}
          >
            {status === 'running' ? 'Running…' : 'Run analysis'}
          </button>
        </div>
        {savedRules.length === 0 && (
          <p className="runner-empty">Define at least one rule in the Rule Builder first.</p>
        )}
        {status === 'error' && (
          <p className="runner-error">
            {error}{onStale && error?.includes('Re-upload') ? ' The server restarted and lost this log; go to Upload to re-add it.' : ''}
          </p>
        )}
      </div>

      {status === 'done' && summary && <GenericResults summary={summary} />}
    </div>
  )
}
