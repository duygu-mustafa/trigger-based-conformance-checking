import { useState, useEffect } from 'react'
import './App.css'
import Timeline from './components/Timeline'
function App() {
  const [caseIds, setCaseIds] = useState([])
  const [caseId, setCaseId] = useState('')
  const [caseData, setCaseData] = useState(null)
  const [loading, setLoading] = useState(true)
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

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Weaning Guideline Conformance Report</h1>
        <div className="case-selector">
          <label htmlFor="case-select">Select Case: </label>
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
      </header>

      <main className="visualization-area">
        {loading ? (
          <div className="loading-spinner">Loading case {caseId}...</div>
        ) : (
          <Timeline data={caseData} />
        )}
      </main>
    </div>
  )
}

export default App
