import { useState, useEffect } from 'react'
import './App.css'
import Timeline from './components/Timeline'
import SummaryView from './components/SummaryView'
import RulesOverview from './components/RulesOverview'
import StudioView from './components/StudioView'
import infoIcon from './static/info.png'

const VIEW_META = {
  summary: {
    eyebrow: 'Population overview',
    description: 'Scan aggregate conformance, outcome correlations, and stay-level filters before opening a timeline.',
  },
  timeline: {
    eyebrow: 'Case investigation',
    description: 'Inspect a single stay with event timing, episode outcomes, and measurement context.',
  },
  rules: {
    eyebrow: 'Rules reference',
    description: 'Reference the declarative guideline set and supporting definitions used by the analysis views.',
  },
  studio: {
    eyebrow: 'Clinician Studio',
    description: 'Explore rules visually, define custom rules, and run on-demand conformance analysis.',
  },
}

function App() {
  const [activeView, setActiveView] = useState('summary')
  const [caseIds, setCaseIds] = useState([])
  const [caseId, setCaseId] = useState('')
  const [hasInitializedSelection, setHasInitializedSelection] = useState(false)
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
      })
      .catch(err => {
        console.error("Failed to load manifest:", err)
        setError("Could not load case manifest. Make sure you've run the conformance script.")
      })
  }, [])

  useEffect(() => {
    if (hasInitializedSelection || caseIds.length === 0) return

    const params = new URLSearchParams(window.location.search)
    const requestedCaseId = params.get('caseId')
    const preferredDefault = '35616431'
    const defaultCaseId = caseIds.includes(preferredDefault) ? preferredDefault : caseIds[0]
    const initialCaseId = requestedCaseId && caseIds.includes(requestedCaseId)
      ? requestedCaseId
      : defaultCaseId

    setCaseId(initialCaseId)
    setActiveView(requestedCaseId && caseIds.includes(requestedCaseId) ? 'timeline' : 'summary')
    setHasInitializedSelection(true)
  }, [caseIds, hasInitializedSelection])

  useEffect(() => {
    if (!caseId || activeView !== 'timeline') return

    const url = new URL(window.location.href)
    url.searchParams.set('caseId', caseId)
    window.history.replaceState({}, '', `${url.pathname}?${url.searchParams.toString()}${url.hash}`)
  }, [activeView, caseId])

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
          <div className="header-copy">
            <span className="app-eyebrow">ICU weaning analysis workspace</span>
            <h1>Weaning Guideline Conformance Report</h1>
            <p className="app-lead">
              {VIEW_META[activeView].description}
            </p>
          </div>
          <div className="view-toggle" role="tablist" aria-label="Dashboard views">
            <button
              type="button"
              className={activeView === 'summary' ? 'view-tab active' : 'view-tab'}
              onClick={() => setActiveView('summary')}
            >
              Global Summary
            </button>
            <button
              type="button"
              className={activeView === 'timeline' ? 'view-tab active' : 'view-tab'}
              onClick={() => setActiveView('timeline')}
            >
              Patient Timeline
            </button>
            <button
              type="button"
              className={activeView === 'studio' ? 'view-tab view-tab--studio active' : 'view-tab view-tab--studio'}
              onClick={() => setActiveView('studio')}
            >
              Clinician Studio
            </button>
          </div>
        </div>
        <div className="header-meta-row">
          {activeView === 'timeline' ? (
            <div className="case-selector">
              <label htmlFor="case-select">Timeline case</label>
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
          ) : <div />}
          <button
            type="button"
            className={activeView === 'rules' ? 'info-chip active' : 'info-chip'}
            onClick={() => setActiveView('rules')}
            aria-label="Open rules reference"
          >
            <img src={infoIcon} alt="" aria-hidden="true" className="info-chip-icon" />
            Rules reference
          </button>
        </div>
      </header>

      <main className={`visualization-area${activeView === 'studio' ? ' visualization-area--studio' : ''}`}>
        {activeView === 'studio' ? (
          <StudioView
            globalSummary={summaryData}
            onOpenTimeline={openTimelineForStay}
          />
        ) : activeView === 'rules' ? (
          summaryLoading ? (
            <div className="loading-spinner">Loading rules reference...</div>
          ) : summaryError ? (
            <div className="error-message">{summaryError}</div>
          ) : (
            <RulesOverview summaryData={summaryData} />
          )
        ) : activeView === 'summary' ? (
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
