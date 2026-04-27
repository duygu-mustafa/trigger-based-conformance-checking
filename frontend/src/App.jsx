import { useState, useEffect } from 'react'
import './App.css'
import Timeline from './components/Timeline'
import SummaryView from './components/SummaryView'

function App() {
  const [activeView, setActiveView] = useState('timeline')
  const [caseIds, setCaseIds] = useState([])
  const [caseId, setCaseId] = useState('')
  const [caseData, setCaseData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [summaryData, setSummaryData] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [summaryError, setSummaryError] = useState(null)
  const [error, setError] = useState(null)

  // 1. Load the manifest on mount
  useEffect(() => {
    fetch('/data/manifest.json')
      .then(res => res.json())
      .then(data => {
        setCaseIds(data.cases)
        if (data.cases.length > 0) {
          // Prefer 35616431 as default if it exists
          const preferredDefault = '35616431'
          if (data.cases.includes(preferredDefault)) {
            setCaseId(preferredDefault)
          } else {
            setCaseId(data.cases[0])
          }
        }
      })
      .catch(err => {
        console.error("Failed to load manifest:", err)
        setError("Could not load case manifest. Make sure you've run the conformance script.")
      })
  }, [])

  useEffect(() => {
    fetch('/data/summary.json')
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(data => {
        setSummaryData(data)
        setSummaryLoading(false)
      })
      .catch(err => {
        console.error('Failed to load summary data:', err)
        setSummaryError('Could not load summary.json. Run derive/generate_summary.py first.')
        setSummaryLoading(false)
      })
  }, [])

  // 2. Load the specific case data when caseId changes
  useEffect(() => {
    if (!caseId) return

    setLoading(true)
    setCaseData(null)

    fetch(`/data/case_${caseId}.json`)
      .then(res => res.json())
      .then(data => {
        setCaseData(data)
        setLoading(false)
      })
      .catch(err => {
        console.error("Failed to load case data:", err)
        setError(`Failed to load data for case ${caseId}`)
        setLoading(false)
      })
  }, [caseId])

  if (error) return <div className="error-message">{error}</div>

  const openTimelineForStay = (stayId) => {
    if (caseIds.includes(stayId)) {
      setCaseId(stayId)
      setActiveView('timeline')
    }
  }

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-title-row">
          <h1>Weaning Guideline Conformance Report</h1>
          <div className="view-toggle" role="tablist" aria-label="Dashboard views">
            <button
              type="button"
              className={activeView === 'timeline' ? 'view-tab active' : 'view-tab'}
              onClick={() => setActiveView('timeline')}
            >
              Patient Timeline
            </button>
            <button
              type="button"
              className={activeView === 'summary' ? 'view-tab active' : 'view-tab'}
              onClick={() => setActiveView('summary')}
            >
              Global Summary
            </button>
          </div>
        </div>
        {activeView === 'timeline' ? (
          <div className="case-selector">
            <label htmlFor="case-select">Timeline Case: </label>
            <select
              id="case-select"
              value={caseId}
              onChange={(e) => setCaseId(e.target.value)}
            >
              {caseIds.map(id => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          </div>
        ) : null}
      </header>

      <main className="visualization-area">
        {activeView === 'summary' ? (
          summaryLoading ? (
            <div className="loading-spinner">Loading global summary...</div>
          ) : summaryError ? (
            <div className="error-message">{summaryError}</div>
          ) : (
            <SummaryView summaryData={summaryData} onSelectStay={openTimelineForStay} />
          )
        ) : loading ? (
          <div className="loading-spinner">Loading case {caseId}...</div>
        ) : (
          <Timeline data={caseData} />
        )}
      </main>
    </div>
  )
}

export default App
