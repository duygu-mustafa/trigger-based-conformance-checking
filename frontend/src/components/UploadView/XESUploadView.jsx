import { useState, useRef } from 'react'

function formatBytes(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export default function XESUploadView({ uploadInfo, onUploaded, onNavigate }) {
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState('idle') // idle | uploading | error
  const [error, setError] = useState(null)
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef(null)

  function pickFile(f) {
    if (!f) return
    setFile(f)
    setError(null)
  }

  async function handleUpload() {
    if (!file) return
    setStatus('uploading')
    setError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch('/api/upload_log', { method: 'POST', body: formData })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
        throw new Error(err.detail || 'Upload failed')
      }
      const data = await res.json()
      onUploaded({ ...data, name: file.name })
      setStatus('idle')
      setFile(null)
    } catch (e) {
      setError(e.message)
      setStatus('error')
    }
  }

  return (
    <div className="xes-upload-view">
      <div
        className={`xes-dropzone${dragActive ? ' active' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDragActive(true) }}
        onDragLeave={() => setDragActive(false)}
        onDrop={e => {
          e.preventDefault()
          setDragActive(false)
          pickFile(e.dataTransfer.files?.[0])
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".xes,.xes.gz"
          onChange={e => pickFile(e.target.files?.[0])}
          hidden
        />
        <div className="xes-dropzone-icon">📄</div>
        <p className="xes-dropzone-title">
          {file ? file.name : 'Drop an XES event log here, or click to browse'}
        </p>
        <p className="xes-dropzone-hint">
          {file ? formatBytes(file.size) : 'Accepts .xes and .xes.gz files'}
        </p>
        <button
          type="button"
          className="run-btn"
          onClick={e => { e.stopPropagation(); handleUpload() }}
          disabled={!file || status === 'uploading'}
        >
          {status === 'uploading' ? 'Uploading…' : 'Upload'}
        </button>
      </div>

      {error && <p className="runner-error">{error}</p>}

      {uploadInfo && (
        <div className="xes-upload-summary summary-card">
          <div className="section-header">
            <h3>{uploadInfo.name || 'Uploaded log'}</h3>
            <button type="button" className="run-btn" onClick={() => onNavigate('builder')}>
              Continue → Rule Builder
            </button>
          </div>
          <div className="runner-kpis">
            <div className="kpi-card">
              <span className="kpi-value">{uploadInfo.num_cases}</span>
              <span className="kpi-label">Cases</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-value">{uploadInfo.num_events}</span>
              <span className="kpi-label">Events</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-value">{uploadInfo.activities.length}</span>
              <span className="kpi-label">Activities</span>
            </div>
          </div>
          <div className="xes-upload-activities">
            {uploadInfo.activities.map(a => (
              <span key={a} className="xes-activity-chip">{a}</span>
            ))}
          </div>
          {uploadInfo.preview_rows?.length > 0 && (
            <div className="xes-upload-preview">
              <h4>Preview (first {uploadInfo.preview_rows.length} rows)</h4>
              <div className="xes-upload-preview-scroll">
                <table className="xes-upload-preview-table">
                  <thead>
                    <tr>
                      {uploadInfo.preview_columns.map(col => <th key={col}>{col}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {uploadInfo.preview_rows.map((row, i) => (
                      <tr key={i}>
                        {uploadInfo.preview_columns.map(col => (
                          <td key={col}>{row[col] === null || row[col] === undefined ? '' : String(row[col])}</td>
                        ))}
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
