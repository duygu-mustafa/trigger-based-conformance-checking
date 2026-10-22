import { useState, useEffect, useRef, lazy, Suspense } from 'react'
import './App.css'
import Sidebar from './components/Sidebar'
import SummaryView from './components/SummaryView'
import TimelineDrawer from './components/TimelineDrawer'
import RuleLibrary from './components/StudioView/RuleLibrary'
import RuleBuilder from './components/StudioView/RuleBuilder'
import AnalysisRunner from './components/StudioView/AnalysisRunner'
import XESUploadView from './components/UploadView/XESUploadView'
import { loadRules, rulesKey } from './datasetRules'

// The story pulls in Plotly; only fetch it when the page opens.
const StoryView = lazy(() => import('./components/StoryView'))

const BUILTIN_DATASET = { kind: 'builtin', id: 'builtin', name: 'ICU Weaning (built-in)' }

// Pages that need the 198 MB summary.json; it is fetched on first visit only.
const SUMMARY_PAGES = ['results-patients']

const storyChapterFromHash = () => {
  const m = /^#story\/(\d+)/.exec(window.location.hash || '')
  return m ? Number(m[1]) : null
}

const PAGE_META = {
  story: {
    eyebrow: 'Results',
    title: 'Case Study',
  },
  upload: {
    eyebrow: 'Configure',
    title: 'Upload Log',
    lead: 'Upload an XES event log to define and run Declare conformance rules independently of the ICU weaning pipeline.',
  },
  library: {
    eyebrow: 'Configure',
    title: 'Rule Library',
    lead: 'Explore the clinical guideline ruleset. Each rule is a Declare constraint evaluated against patient episodes.',
  },
  builder: {
    eyebrow: 'Configure',
    title: 'Rule Builder',
    lead: 'Define custom conformance rules with a step-by-step wizard and preview them visually before saving.',
  },
  runner: {
    eyebrow: 'Analyze',
    title: 'Run Analysis',
    lead: 'Configure and run conformance checking on a sample of ICU stays. Results appear on this page after the run completes.',
  },
  'results-patients': {
    eyebrow: 'Results',
    title: 'Patient Explorer',
    lead: 'Browse, filter, and sort stays by violation profile. Open any patient timeline with one click.',
  },
}

function ApiErrorState({ error }) {
  return (
    <div className="api-error-state">
      <div className="api-error-icon">⚠</div>
      <h3>Backend not reachable</h3>
      <p>{error}</p>
      <div className="api-error-hint">
        <code>source .venv/bin/activate &amp;&amp; uvicorn api:app --reload --port 8000</code>
      </div>
    </div>
  )
}

export default function App() {
  // The defense story is the landing page for the built-in dataset.
  const [activePage, setActivePage] = useState(() => {
    if ((window.location.hash || '').startsWith('#story')) return 'story'
    return (localStorage.getItem('studio_active_dataset') || 'builtin') === 'builtin' ? 'story' : 'library'
  })
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [returnChapter, setReturnChapter] = useState(null)

  // Drill-down selection, shared by the story chapter and the page so it
  // survives opening a timeline.
  const [drillSel, setDrillSel] = useState({ ruleId: 'RC-DP-01', group: 'unmet' })
  const [drilldownData, setDrilldownData] = useState(null)
  const [drilldownError, setDrilldownError] = useState(null)
  const drilldownRequested = useRef(false)
  // Chapter 2 rule selection and its distributions (frequency_detail.json)
  const [freqRule, setFreqRule] = useState('RC-DP-01')
  const [frequencyDetail, setFrequencyDetail] = useState(null)
  const summaryRequested = useRef(false)

  // Timeline drawer
  const [drawerStayId, setDrawerStayId] = useState(null)
  const [drawerCaseData, setDrawerCaseData] = useState(null)
  const [drawerLoading, setDrawerLoading] = useState(false)

  // Case list
  const [caseIds, setCaseIds] = useState([])

  // Static summary data (global baseline)
  const [summaryData, setSummaryData] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [summaryError, setSummaryError] = useState(null)

  // Case-study insight tables (static, exported by case_study/10)
  const [insightsData, setInsightsData] = useState(null)
  const [insightsLoading, setInsightsLoading] = useState(true)
  const [insightsError, setInsightsError] = useState(null)

  // Studio API data
  const [rules, setRules] = useState([])
  const [activities, setActivities] = useState({})
  const [itemLabels, setItemLabels] = useState({})
  const [rulesLoading, setRulesLoading] = useState(true)
  const [apiError, setApiError] = useState(null)
  const [customRules, setCustomRules] = useState([])
  const [customEventTypes, setCustomEventTypes] = useState(() => {
    try { return JSON.parse(localStorage.getItem('studio_custom_event_types') || '[]') }
    catch { return [] }
  })
  const [customDataConditions, setCustomDataConditions] = useState(() => {
    try { return JSON.parse(localStorage.getItem('studio_custom_data_conditions') || '[]') }
    catch { return [] }
  })

  // Uploaded XES logs + active-dataset selection (global selector)
  const [datasets, setDatasets] = useState(() => {
    try { return JSON.parse(localStorage.getItem('studio_datasets') || '[]') }
    catch { return [] }
  })
  const [activeDatasetId, setActiveDatasetId] = useState(
    () => localStorage.getItem('studio_active_dataset') || 'builtin'
  )
  const activeDataset =
    activeDatasetId === 'builtin'
      ? BUILTIN_DATASET
      : datasets.find(d => d.id === activeDatasetId) || BUILTIN_DATASET

  function selectDataset(id) {
    setActiveDatasetId(id)
    localStorage.setItem('studio_active_dataset', id)
  }

  function handleUploaded(info) {
    setDatasets(prev => {
      const next = [...prev.filter(d => d.id !== info.upload_id), {
        kind: 'upload',
        id: info.upload_id,
        name: info.name || `Log ${prev.length + 1}`,
        num_cases: info.num_cases,
        num_events: info.num_events,
        activities: info.activities,
        dataAttributes: Object.fromEntries((info.data_attributes || []).map(a => [a.key, a.label])),
        preview_columns: info.preview_columns,
        preview_rows: info.preview_rows,
      }]
      localStorage.setItem('studio_datasets', JSON.stringify(next))
      return next
    })
    selectDataset(info.upload_id)
  }

  function handleDeleteDataset(id) {
    fetch(`/api/upload_log/${id}`, { method: 'DELETE' }).catch(() => {})
    setDatasets(prev => {
      const next = prev.filter(d => d.id !== id)
      localStorage.setItem('studio_datasets', JSON.stringify(next))
      return next
    })
    localStorage.removeItem(rulesKey(id))
    if (activeDatasetId === id) selectDataset('builtin')
  }

  // Per-dataset custom rules — reload when the active dataset changes
  useEffect(() => {
    setCustomRules(loadRules(activeDatasetId))
  }, [activeDatasetId])

  // Builtin-only pages: bounce away when an uploaded dataset is active
  useEffect(() => {
    if (activeDatasetId === 'builtin') return
    if (activePage === 'library' || activePage === 'story' || activePage.startsWith('results-')) {
      setActivePage('runner')
    }
  }, [activeDatasetId, activePage])

  // Keep #story/N only while the story is open
  useEffect(() => {
    if (activePage !== 'story' && (window.location.hash || '').startsWith('#story')) {
      window.history.replaceState(null, '', window.location.pathname + window.location.search)
    }
  }, [activePage])

  // Load case manifest
  useEffect(() => {
    fetch('/data/manifest.json')
      .then(r => r.json())
      .then(d => setCaseIds(d.cases))
      .catch(err => console.error('Failed to load manifest:', err))
  }, [])

  // Load static summary (large) the first time a page needs it
  useEffect(() => {
    if (!SUMMARY_PAGES.includes(activePage) || summaryRequested.current) return
    summaryRequested.current = true
    fetch('/data/summary.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(d => { setSummaryData(d); setSummaryLoading(false) })
      .catch(err => { setSummaryError(err.message); setSummaryLoading(false) })
  }, [activePage])

  // Load the drill-down and per-rule distributions the first time the story opens
  useEffect(() => {
    if (activePage !== 'story' || drilldownRequested.current) return
    drilldownRequested.current = true
    fetch('/data/drilldown.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setDrilldownData)
      .catch(err => setDrilldownError(err.message))
    fetch('/data/frequency_detail.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setFrequencyDetail)
      .catch(err => console.error('Failed to load frequency_detail.json:', err))
  }, [activePage])

  // Load case-study insights
  useEffect(() => {
    fetch('/data/insights.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(d => { setInsightsData(d); setInsightsLoading(false) })
      .catch(err => { setInsightsError(err.message); setInsightsLoading(false) })
  }, [])

  // Load Studio API data
  useEffect(() => {
    let cancelled = false
    async function fetchStudioData() {
      try {
        const [rulesRes, activitiesRes, labelsRes] = await Promise.all([
          fetch('/api/rules'),
          fetch('/api/activities'),
          fetch('/api/item_labels'),
        ])
        if (!rulesRes.ok || !activitiesRes.ok || !labelsRes.ok) {
          throw new Error(
            'Could not reach the backend API. ' +
            'Make sure the server is running: uvicorn api:app --port 8000'
          )
        }
        const [rulesData, activitiesData, labelsData] = await Promise.all([
          rulesRes.json(),
          activitiesRes.json(),
          labelsRes.json(),
        ])
        if (!cancelled) {
          setRules(rulesData)
          setActivities(activitiesData)
          setItemLabels(labelsData)
          setRulesLoading(false)
        }
      } catch (err) {
        if (!cancelled) {
          setApiError(err.message)
          setRulesLoading(false)
        }
      }
    }
    fetchStudioData()
    return () => { cancelled = true }
  }, [])

  // Load timeline drawer case data when stayId changes
  useEffect(() => {
    if (!drawerStayId) return
    setDrawerLoading(true)
    setDrawerCaseData(null)
    fetch(`/data/case_${drawerStayId}.json`)
      .then(r => r.ok ? r.json() : fetch(`/api/case/${drawerStayId}`).then(r2 => r2.ok ? r2.json() : null))
      .then(d => { setDrawerCaseData(d); setDrawerLoading(false) })
      .catch(() => setDrawerLoading(false))
  }, [drawerStayId])

  const openTimeline = (stayId) => {
    setDrawerStayId(String(stayId))
  }

  // Story → explorer page and back, returning to the same chapter
  const goExplore = (page) => {
    setReturnChapter(storyChapterFromHash())
    setActivePage(page)
  }

  const backToStory = () => {
    if (returnChapter) window.history.replaceState(null, '', `#story/${returnChapter}`)
    setReturnChapter(null)
    setActivePage('story')
  }

  // Sidebar navigation drops the pending "back to chapter" link
  const navigate = (page) => {
    setReturnChapter(null)
    setActivePage(page)
  }

  const meta = PAGE_META[activePage] || PAGE_META['library']

  const mergedActivities = {
    ...activities,
    custom: customEventTypes.map(et => et.name),
    all: [...(activities.all || []), ...customEventTypes.map(et => et.name)],
  }

  const isUpload = activeDataset.kind === 'upload'
  const builderActivities = isUpload ? { all: activeDataset.activities || [] } : mergedActivities

  function renderContent() {
    if (activePage === 'upload') {
      return (
        <XESUploadView
          uploadInfo={isUpload ? activeDataset : null}
          onUploaded={handleUploaded}
          onNavigate={setActivePage}
        />
      )
    }

    if (activePage === 'library') {
      if (apiError) return <ApiErrorState error={apiError} />
      return <RuleLibrary rules={rules} loading={rulesLoading} />
    }

    if (activePage === 'runner') {
      if (apiError) return <ApiErrorState error={apiError} />
      return (
        <AnalysisRunner
          customRules={customRules}
          predefinedRuleCount={rules.length}
          onOpenTimeline={openTimeline}
          uploadInfo={isUpload ? activeDataset : null}
          datasetId={activeDatasetId}
          onUploadStale={isUpload ? () => handleDeleteDataset(activeDataset.id) : undefined}
        />
      )
    }

    if (activePage === 'story') {
      if (insightsLoading) return <div className="loading-spinner">Loading case study…</div>
      if (insightsError) {
        return (
          <div className="error-message">
            Could not load <code>/data/insights.json</code> ({insightsError}). Generate it with{' '}
            <code>python case_study/10_frontend_insights.py</code>.
          </div>
        )
      }
      return (
        <Suspense fallback={<p className="summary-empty">Loading story…</p>}>
          <StoryView
            insights={insightsData}
            drilldown={drilldownData}
            drilldownError={drilldownError}
            drillSel={drillSel}
            onDrillChange={setDrillSel}
            frequencyDetail={frequencyDetail}
            freqRule={freqRule}
            onFreqRule={setFreqRule}
            onOpenTimeline={openTimeline}
            onExplore={goExplore}
          />
        </Suspense>
      )
    }

    if (activePage.startsWith('results-')) {
      const section = activePage.replace('results-', '')
      const returnBar = returnChapter && (
        <div className="story-return">
          <button type="button" className="story-btn" onClick={backToStory}>
            ← Back to chapter {returnChapter}
          </button>
        </div>
      )
      if (summaryLoading) return <>{returnBar}<div className="loading-spinner">Loading results…</div></>
      if (summaryError) return <>{returnBar}<div className="error-message">{summaryError}</div></>
      return (
        <>
          {returnBar}
          <SummaryView
            summaryData={summaryData}
            section={section}
            onSelectStay={openTimeline}
          />
        </>
      )
    }

    return null
  }

  if (drawerStayId) {
    return (
      <TimelineDrawer
        stayId={drawerStayId}
        caseData={drawerCaseData}
        caseIds={caseIds}
        loading={drawerLoading}
        onClose={() => setDrawerStayId(null)}
        onChangeStay={openTimeline}
      />
    )
  }

  return (
    <div className="app-shell">
      <Sidebar
        activePage={activePage}
        onNavigate={navigate}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(c => !c)}
        datasets={datasets}
        activeDatasetId={activeDatasetId}
        onSelectDataset={selectDataset}
        onDeleteDataset={handleDeleteDataset}
      />

      <div className="app-main">
        <header className="page-header">
          <div className="page-header-eyebrow">{meta.eyebrow}</div>
          <h1>{meta.title}</h1>
          {meta.lead && <p className="page-header-lead">{meta.lead}</p>}
        </header>

        <main className="page-content">
          {activePage === 'builder' && apiError
            ? <ApiErrorState error={apiError} />
            : <div style={activePage !== 'builder' ? { display: 'none' } : undefined}>
                <RuleBuilder
                  activities={builderActivities}
                  datasetId={activeDatasetId}
                  itemLabels={isUpload ? (activeDataset.dataAttributes || {}) : itemLabels}
                  dataConditionsEnabled={true}
                  eventBuilderEnabled={!isUpload}
                  onSaveRule={rule => setCustomRules(r => [...r, rule])}
                  customEventTypes={customEventTypes}
                  onSaveCustomEvent={et => {
                    const eventWithId = et.id ? et : { ...et, id: `CET-${Date.now()}` }
                    const updated = et.id
                      ? customEventTypes.map(e => e.id === et.id ? eventWithId : e)
                      : [...customEventTypes, eventWithId]
                    setCustomEventTypes(updated)
                    localStorage.setItem('studio_custom_event_types', JSON.stringify(updated))
                  }}
                  onDeleteCustomEvent={id => {
                    const updated = customEventTypes.filter(e => e.id !== id)
                    setCustomEventTypes(updated)
                    localStorage.setItem('studio_custom_event_types', JSON.stringify(updated))
                  }}
                  customDataConditions={customDataConditions}
                  onSaveCustomDataCondition={cond => {
                    const condWithId = cond.id ? cond : { ...cond, id: `CDC-${Date.now()}` }
                    const updated = cond.id
                      ? customDataConditions.map(c => c.id === cond.id ? condWithId : c)
                      : [...customDataConditions, condWithId]
                    setCustomDataConditions(updated)
                    localStorage.setItem('studio_custom_data_conditions', JSON.stringify(updated))
                  }}
                  onDeleteCustomDataCondition={id => {
                    const updated = customDataConditions.filter(c => c.id !== id)
                    setCustomDataConditions(updated)
                    localStorage.setItem('studio_custom_data_conditions', JSON.stringify(updated))
                  }}
                />
              </div>
          }
          {activePage !== 'builder' && renderContent()}
        </main>
      </div>
    </div>
  )
}
