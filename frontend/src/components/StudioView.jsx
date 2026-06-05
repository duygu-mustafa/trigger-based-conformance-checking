import { useState, useEffect } from 'react'
import RuleLibrary from './StudioView/RuleLibrary'
import RuleBuilder from './StudioView/RuleBuilder'
import AnalysisRunner from './StudioView/AnalysisRunner'

const TABS = [
  { id: 'library', label: 'Rule Library', icon: '📋' },
  { id: 'builder', label: 'Rule Builder', icon: '✏️' },
  { id: 'runner', label: 'Run Analysis', icon: '▶' },
]

export default function StudioView({ globalSummary, onOpenTimeline }) {
  const [activeTab, setActiveTab] = useState('library')
  const [rules, setRules] = useState([])
  const [activities, setActivities] = useState({})
  const [itemLabels, setItemLabels] = useState({})
  const [rulesLoading, setRulesLoading] = useState(true)
  const [apiError, setApiError] = useState(null)
  const [customRules, setCustomRules] = useState([])

  // Fetch rules and activities from the FastAPI backend on mount
  useEffect(() => {
    let cancelled = false

    async function fetchData() {
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

    fetchData()
    return () => { cancelled = true }
  }, [])

  if (apiError) {
    return (
      <div className="studio-api-error">
        <div className="studio-api-error-icon">⚠</div>
        <h3>Backend not reachable</h3>
        <p>{apiError}</p>
        <div className="studio-api-error-hint">
          <code>source .venv/bin/activate &amp;&amp; uvicorn api:app --reload --port 8000</code>
        </div>
      </div>
    )
  }

  return (
    <div className="studio-view">
      <div className="studio-header">
        <div className="studio-header-copy">
          <h2 className="studio-title">Clinician Studio</h2>
          <p className="studio-lead">
            Explore clinical guidelines visually, define custom rules, and run conformance analysis on a sample of ICU stays.
          </p>
        </div>
        <nav className="studio-tabs" role="tablist" aria-label="Studio sections">
          {TABS.map(tab => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              className={`studio-tab-btn ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span className="studio-tab-icon" aria-hidden="true">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      <div className="studio-body" role="tabpanel">
        {activeTab === 'library' && (
          <RuleLibrary rules={rules} loading={rulesLoading} />
        )}
        {activeTab === 'builder' && (
          <RuleBuilder
            activities={activities}
            itemLabels={itemLabels}
            onSaveRule={rule => setCustomRules(r => [...r, rule])}
          />
        )}
        {activeTab === 'runner' && (
          <AnalysisRunner
            globalSummary={globalSummary}
            customRules={customRules}
            onOpenTimeline={onOpenTimeline}
          />
        )}
      </div>
    </div>
  )
}
