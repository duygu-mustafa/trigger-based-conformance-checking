import { useState, useMemo } from 'react'
import DeclareVisualizer from './DeclareVisualizer'

const CATEGORIES = [
  { key: 'all', label: 'All rules' },
  { key: 'readiness', label: 'Readiness' },
  { key: 'sbt_execution', label: 'SBT Execution' },
  { key: 'failure_correction', label: 'Failure Correction' },
]

const CATEGORY_LABELS = {
  readiness: 'Readiness Assessment',
  sbt_execution: 'SBT Execution',
  failure_correction: 'Failure Correction',
  other: 'Other',
}

const TEMPLATE_GROUPS = {
  positive: ['EXISTENCE', 'RESPONSE', 'PRECEDENCE', 'SUCCESSION', 'CO_EXISTENCE',
    'RESPONDED_EXISTENCE', 'CHAIN_RESPONSE', 'CHAIN_PRECEDENCE', 'CHAIN_SUCCESSION',
    'ALTERNATE_RESPONSE', 'ALTERNATE_PRECEDENCE', 'ALTERNATE_SUCCESSION', 'INIT', 'END', 'EXACTLY'],
  negative: ['ABSENCE', 'NOT_CO_EXISTENCE', 'NOT_RESPONSE', 'NOT_CHAIN_RESPONSE',
    'NOT_PRECEDENCE', 'NOT_CHAIN_PRECEDENCE', 'NOT_RESPONDED_EXISTENCE',
    'NOT_SUCCESSION', 'NOT_CHAIN_SUCCESSION'],
}

function severityColor(value) {
  if (value >= 0.85) return 'var(--color-violation)'
  if (value >= 0.65) return '#e8a020'
  return 'var(--color-success)'
}

function SeverityBar({ label, value }) {
  return (
    <div className="severity-bar-row">
      <span className="severity-bar-label">{label}</span>
      <div className="severity-bar-track">
        <div
          className="severity-bar-fill"
          style={{ width: `${Math.round(value * 100)}%`, background: severityColor(value) }}
        />
      </div>
      <span className="severity-bar-value">{Math.round(value * 100)}%</span>
    </div>
  )
}

function ConditionChip({ chip }) {
  if (chip.text) {
    return <span className="condition-chip condition-chip--plain">{chip.text}</span>
  }
  return (
    <span className="condition-chip">
      <span className="chip-label">{chip.item_label}</span>
      <span className="chip-op">{chip.operator}</span>
      <span className="chip-val">{chip.value}</span>
    </span>
  )
}

function TimeWindow({ time_condition }) {
  const { min_hours, max_hours } = time_condition || {}
  if (!min_hours && !max_hours) return null
  const parts = []
  if (min_hours != null) parts.push(`min ${min_hours}h`)
  if (max_hours != null) parts.push(`max ${max_hours}h`)
  return (
    <span className="time-window-chip">
      <svg width="12" height="12" viewBox="0 0 12 12" className="time-icon" aria-hidden="true">
        <circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" strokeWidth="1.4"/>
        <line x1="6" y1="3" x2="6" y2="6.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
        <line x1="6" y1="6.5" x2="8.5" y2="8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
      </svg>
      {parts.join(' · ')}
    </span>
  )
}

function RuleCard({ rule }) {
  const [expanded, setExpanded] = useState(false)
  const isNegative = TEMPLATE_GROUPS.negative.includes(rule.template)

  return (
    <div className={`rule-card ${isNegative ? 'rule-card--negative' : ''} ${expanded ? 'rule-card--expanded' : ''}`}>
      <button
        className="rule-card-header"
        onClick={() => setExpanded(e => !e)}
        aria-expanded={expanded}
      >
        <div className="rule-card-meta">
          <span className="rule-id-badge">{rule.id}</span>
          <span className={`rule-category-badge rule-category-badge--${rule.category}`}>
            {CATEGORY_LABELS[rule.category] || rule.category}
          </span>
        </div>
        <div className="rule-card-diagram-wrap">
          <DeclareVisualizer
            template={rule.template}
            activation={rule.activation}
            target={rule.target}
            compact={true}
          />
        </div>
        <div className="rule-card-title-area">
          <h3 className="rule-card-label">{rule.label}</h3>
          <span className="rule-template-badge">{rule.template_label}</span>
        </div>
        <span className="rule-card-chevron" aria-hidden="true">
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {expanded && (
        <div className="rule-card-body">
          <div className="rule-card-visualizer">
            <DeclareVisualizer
              template={rule.template}
              activation={rule.activation}
              target={rule.target}
              compact={false}
            />
          </div>

          <div className="rule-card-details">
            {/* Conditions */}
            {(rule.activation_conditions?.length > 0 || rule.correlation_conditions?.length > 0) && (
              <div className="rule-detail-section">
                <h4 className="rule-detail-heading">Data Conditions</h4>
                {rule.activation_conditions?.length > 0 && (
                  <div className="condition-group">
                    <span className="condition-group-label">On activation:</span>
                    <div className="condition-chips">
                      {rule.activation_conditions.map((chip, i) => (
                        <span key={i}>
                          {i > 0 && <span className="logic-op">{rule.activation_logic}</span>}
                          <ConditionChip chip={chip} />
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {rule.correlation_conditions?.length > 0 && (
                  <div className="condition-group">
                    <span className="condition-group-label">On target:</span>
                    <div className="condition-chips">
                      {rule.correlation_conditions.map((chip, i) => (
                        <span key={i}>
                          {i > 0 && <span className="logic-op">{rule.correlation_logic}</span>}
                          <ConditionChip chip={chip} />
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Time window */}
            {(rule.time_condition?.min_hours || rule.time_condition?.max_hours) && (
              <div className="rule-detail-section">
                <h4 className="rule-detail-heading">Time Window</h4>
                <TimeWindow time_condition={rule.time_condition} />
              </div>
            )}

            {/* Rationale */}
            {rule.rationale && (
              <div className="rule-detail-section">
                <h4 className="rule-detail-heading">Clinical rationale</h4>
                <p className="rule-rationale">{rule.rationale}</p>
              </div>
            )}

            {/* Severity */}
            <div className="rule-detail-section">
              <h4 className="rule-detail-heading">Rule weight</h4>
              <SeverityBar label="Clinical consequence" value={rule.severity?.clinical_consequence ?? 0} />
              <SeverityBar label="Hard requirement" value={rule.severity?.must_not_vs_should ?? 0} />
              <SeverityBar label="Detection risk" value={rule.severity?.unnoticed_frequency ?? 0} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function RuleLibrary({ rules = [], loading = false }) {
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')
  const [expandAll, setExpandAll] = useState(false)

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return rules.filter(r => {
      if (category !== 'all' && r.category !== category) return false
      if (!q) return true
      return (
        r.id.toLowerCase().includes(q) ||
        r.label.toLowerCase().includes(q) ||
        r.rationale?.toLowerCase().includes(q) ||
        r.template?.toLowerCase().includes(q) ||
        r.template_label?.toLowerCase().includes(q)
      )
    })
  }, [rules, search, category])

  if (loading) {
    return <div className="studio-loading">Loading rules from server…</div>
  }

  return (
    <div className="rule-library">
      <div className="rule-library-toolbar">
        <div className="studio-search-wrap">
          <svg className="studio-search-icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="6.5" cy="6.5" r="5" fill="none" stroke="currentColor" strokeWidth="1.6"/>
            <line x1="10.2" y1="10.2" x2="14" y2="14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
          </svg>
          <input
            className="studio-search"
            type="search"
            placeholder="Search rules…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            aria-label="Search rules"
          />
        </div>
        <div className="studio-tab-group" role="tablist">
          {CATEGORIES.map(cat => (
            <button
              key={cat.key}
              role="tab"
              aria-selected={category === cat.key}
              className={`studio-tab ${category === cat.key ? 'active' : ''}`}
              onClick={() => setCategory(cat.key)}
            >
              {cat.label}
              {cat.key !== 'all' && (
                <span className="tab-count">
                  {rules.filter(r => r.category === cat.key).length}
                </span>
              )}
            </button>
          ))}
        </div>
        <div className="rule-library-actions">
          <span className="rule-count-label">{filtered.length} rule{filtered.length !== 1 ? 's' : ''}</span>
          <button className="studio-ghost-btn" onClick={() => setExpandAll(e => !e)}>
            {expandAll ? 'Collapse all' : 'Expand all'}
          </button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="studio-empty">No rules match your search.</div>
      ) : (
        <div className="rule-card-list">
          {filtered.map(rule => (
            <RuleCard key={rule.id} rule={rule} forceExpanded={expandAll} />
          ))}
        </div>
      )}
    </div>
  )
}
