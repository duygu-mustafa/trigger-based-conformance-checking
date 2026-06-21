import { useState, useEffect } from 'react'
import './App.css'
import Sidebar from './components/Sidebar'
import SummaryView from './components/SummaryView'
import TimelineDrawer from './components/TimelineDrawer'
import RuleLibrary from './components/StudioView/RuleLibrary'
import RuleBuilder from './components/StudioView/RuleBuilder'
import AnalysisRunner from './components/StudioView/AnalysisRunner'

const PAGE_META = {
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
  'results-frequencies': {
    eyebrow: 'Results',
    title: 'Violation Frequencies',
    lead: 'Ranked violations with timing histograms and episode-level drill-down. Based on the full patient cohort.',
  },
  'results-statistics': {
    eyebrow: 'Results',
    title: 'Statistical Analysis',
    lead: 'Formal associations between process adherence and weaning outcome: OR, RR, 95% CI, and p-values.',
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
  const [activePage, setActivePage] = useState('library')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

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

  // Load case manifest
  useEffect(() => {
    fetch('/data/manifest.json')
      .then(r => r.json())
      .then(d => setCaseIds(d.cases))
      .catch(err => console.error('Failed to load manifest:', err))
  }, [])

  // Load static summary
  useEffect(() => {
    fetch('/data/summary.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(d => { setSummaryData(d); setSummaryLoading(false) })
      .catch(err => { setSummaryError(err.message); setSummaryLoading(false) })
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

  const meta = PAGE_META[activePage] || PAGE_META['library']

  const mergedActivities = {
    ...activities,
    custom: customEventTypes.map(et => et.name),
    all: [...(activities.all || []), ...customEventTypes.map(et => et.name)],
  }

  function renderContent() {
    if (activePage === 'library') {
      if (apiError) return <ApiErrorState error={apiError} />
      return <RuleLibrary rules={rules} loading={rulesLoading} />
    }

    if (activePage === 'builder') {
      if (apiError) return <ApiErrorState error={apiError} />
      return (
        <RuleBuilder
          activities={mergedActivities}
          itemLabels={itemLabels}
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
      )
    }

    if (activePage === 'runner') {
      if (apiError) return <ApiErrorState error={apiError} />
      return (
        <AnalysisRunner
          customRules={customRules}
          onOpenTimeline={openTimeline}
        />
      )
    }

    if (activePage.startsWith('results-')) {
      const section = activePage.replace('results-', '')
      if (summaryLoading) return <div className="loading-spinner">Loading results…</div>
      if (summaryError) return <div className="error-message">{summaryError}</div>
      return (
        <SummaryView
          summaryData={summaryData}
          section={section}
          onSelectStay={openTimeline}
        />
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
        onNavigate={setActivePage}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(c => !c)}
      />

      <div className="app-main">
        <header className="page-header">
          <div className="page-header-eyebrow">{meta.eyebrow}</div>
          <h1>{meta.title}</h1>
          <p className="page-header-lead">{meta.lead}</p>
        </header>

        <main className="page-content">
          {renderContent()}
        </main>
      </div>
    </div>
  )
}
