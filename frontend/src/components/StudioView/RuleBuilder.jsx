import { useState, useEffect } from 'react'
import DeclareVisualizer from './DeclareVisualizer'
import CustomEventModal from './CustomEventModal'
import DataConditionModal from './DataConditionModal'
import { FormulaBuilder, tokensToExpr, treeToTokens, emptyCondToken, migrateFlat, validateTokensOptional, validateTokens } from './ConditionTree'
import { UilPen } from '@iconscout/react-unicons'

// Templates offered to clinicians, grouped for usability
const TEMPLATE_OPTIONS = [
  {
    group: 'Sequence rules',
    items: [
      { id: 'RESPONSE', label: 'Must follow', description: 'After [A] occurs, [B] must eventually happen', icon: '→' },
      { id: 'ALTERNATE_RESPONSE', label: 'Alternate follow', description: 'Each time [A] occurs, [B] must follow before [A] recurs', icon: '→*' },
      { id: 'CHAIN_RESPONSE', label: 'Immediate follow', description: 'After [A], [B] must occur immediately next', icon: '→!' },
      { id: 'PRECEDENCE', label: 'Must precede', description: '[B] can only occur if [A] happened before', icon: '←' },
      { id: 'ALTERNATE_PRECEDENCE', label: 'Alternate precede', description: 'Each time [B] occurs, it must be preceded by [A] with no other [B] in between', icon: '*←' },
      { id: 'CHAIN_PRECEDENCE', label: 'Immediate precede', description: '[B] must be immediately preceded by [A]', icon: '!←' },
      { id: 'SUCCESSION', label: 'Mutual sequence', description: '[A] occurs if and only if it is followed by [B]', icon: '⇆' },
      { id: 'ALTERNATE_SUCCESSION', label: 'Alternate mutual sequence', description: '[A] and [B] alternate: each [A] is followed by [B] and each [B] is preceded by [A]', icon: '⇆*' },
      { id: 'CHAIN_SUCCESSION', label: 'Immediate mutual sequence', description: '[A] and [B] must occur immediately one after the other', icon: '⇆!' },
    ],
  },
  {
    group: 'Existence rules',
    items: [
      { id: 'INIT', label: 'Must be first', description: '[A] must be the first event in the episode', icon: '⊳' },
      { id: 'END', label: 'Must be last', description: '[A] must be the last event in the episode', icon: '⊲' },
      { id: 'EXISTENCE', label: 'Must occur', description: '[A] must happen at least once in the episode', icon: '≥1' },
      { id: 'AT_MOST_ONE', label: 'At most once', description: '[A] must occur at most once in the episode', icon: '0..1' },
      { id: 'ABSENCE', label: 'Must not occur', description: '[A] must never happen in this episode', icon: '⊘' },
      { id: 'CO_EXISTENCE', label: 'Co-occur', description: '[A] and [B] must either both occur or both be absent', icon: '↔' },
      { id: 'RESPONDED_EXISTENCE', label: 'Implies existence', description: 'If [A] occurs, [B] must also occur (any order)', icon: '∃' },
    ],
  },
  {
    group: 'Prohibition rules',
    items: [
      { id: 'NOT_CO_EXISTENCE', label: 'Cannot co-occur', description: '[A] and [B] cannot both happen in the same episode', icon: '✕' },
      { id: 'NOT_RESPONSE', label: 'Must not follow', description: 'After [A], [B] must NOT occur', icon: '⊘→' },
      { id: 'NOT_SUCCESSION', label: 'Sequence forbidden', description: '[A] followed by [B] is forbidden', icon: '⊘⇆' },
      { id: 'NOT_CHAIN_SUCCESSION', label: 'No immediate mutual sequence', description: '[A] and [B] cannot occur immediately one after the other', icon: '⊘⇆!' },
    ],
  },
]

const UNARY_TEMPLATES = ['EXISTENCE', 'ABSENCE', 'AT_MOST_ONE', 'INIT', 'END']

const TEMPLATE_MAP = Object.fromEntries(
  TEMPLATE_OPTIONS.flatMap(g => g.items.map(t => [t.id, t]))
)

const STEPS = [
  { id: 'template', label: 'Rule type' },
  { id: 'activities', label: 'Activities' },
  { id: 'time', label: 'Time window' },
  { id: 'conditions', label: 'Data conditions' },
  { id: 'metadata', label: 'Details' },
]

function StepIndicator({ steps, currentStep }) {
  const currentIdx = steps.findIndex(s => s.id === currentStep)
  return (
    <div className="step-indicator" role="list">
      {steps.map((step, idx) => {
        const state = idx < currentIdx ? 'done' : idx === currentIdx ? 'active' : 'pending'
        return (
          <div key={step.id} className={`step-dot step-dot--${state}`} role="listitem">
            <div className="step-dot-circle">
              {state === 'done' ? '✓' : idx + 1}
            </div>
            <span className="step-dot-label">{step.label}</span>
            {idx < steps.length - 1 && <div className={`step-connector ${state === 'done' ? 'done' : ''}`} />}
          </div>
        )
      })}
    </div>
  )
}

export default function RuleBuilder({ activities = {}, itemLabels = {}, onSaveRule, customEventTypes = [], onSaveCustomEvent, onDeleteCustomEvent, customDataConditions = [], onSaveCustomDataCondition, onDeleteCustomDataCondition }) {
  const [step, setStep] = useState('template')
  const [showEventModal, setShowEventModal] = useState(false)
  const [showConditionModal, setShowConditionModal] = useState(false)
  const [editingRuleId, setEditingRuleId] = useState(null)
  const [rule, setRule] = useState({
    template: '',
    activation: '',
    target: '',
    min_gap_hours: '',
    max_gap_hours: '',
    activation_tokens: [emptyCondToken()],
    correlation_tokens: [emptyCondToken()],
    label: '',
    rationale: '',
    severity: { clinical_consequence: 0.7, must_not_vs_should: 0.7 },
  })
  const [condError, setCondError] = useState('')
  const [saveCondOpen, setSaveCondOpen] = useState(null) // 'activation' | 'correlation' | null
  const [saveCondName, setSaveCondName] = useState('')
  const [savedRules, setSavedRules] = useState(() => {
    try {
      const raw = JSON.parse(localStorage.getItem('studio_custom_rules') || '[]')
      return raw.map(r => {
        const actTree = r.activation_condition_tree ?? migrateFlat(r.activation_conditions, r.activation_logic)
        const corrTree = r.correlation_condition_tree ?? migrateFlat(r.correlation_conditions, r.correlation_logic)
        return {
          ...r,
          activation_tokens: r.activation_tokens || treeToTokens(actTree),
          correlation_tokens: r.correlation_tokens || treeToTokens(corrTree),
        }
      })
    }
    catch { return [] }
  })

  const isUnary = UNARY_TEMPLATES.includes(rule.template)
  const allActivities = activities.all || []

  // Build item options list from itemLabels (hide internal/derived ids)
  const baseItemOptions = Object.entries(itemLabels)
    .filter(([key]) => !key.startsWith('derived_') && !['sbt_status', 'sbt_outcome'].includes(key))
    .map(([key, label]) => ({ key, label: label.split('#')[0].trim() }))
    .sort((a, b) => a.label.localeCompare(b.label))
  const customItems = customDataConditions
    .flatMap(c => c.data_items || [])
    .filter((it, i, arr) => arr.findIndex(x => x.itemid === it.itemid) === i)
    .filter(it => !itemLabels[String(it.itemid)])
    .map(it => ({ key: String(it.itemid), label: it.label }))
  const itemOptions = [...baseItemOptions, ...customItems]

  function updateRule(patch) {
    setRule(r => ({ ...r, ...patch }))
  }

  function canAdvance() {
    switch (step) {
      case 'template': return !!rule.template
      case 'activities': return !!rule.activation && (isUnary || !!rule.target)
      default: return true
    }
  }

  function nextStep() {
    if (step === 'conditions') {
      const err = validateTokensOptional(rule.activation_tokens)
        || (!isUnary ? validateTokensOptional(rule.correlation_tokens) : null)
        || null
      if (err) { setCondError(err); return }
      setCondError('')
    }
    const idx = STEPS.findIndex(s => s.id === step)
    if (idx < STEPS.length - 1) setStep(STEPS[idx + 1].id)
  }

  function prevStep() {
    const idx = STEPS.findIndex(s => s.id === step)
    if (idx > 0) setStep(STEPS[idx - 1].id)
  }

  function saveRule() {
    const err = validateTokensOptional(rule.activation_tokens)
      || (!isUnary ? validateTokensOptional(rule.correlation_tokens) : null)
      || null
    if (err) { setCondError(err); setStep('conditions'); return }
    setCondError('')
    const activationExpr = tokensToExpr(rule.activation_tokens)
    const correlationExpr = tokensToExpr(rule.correlation_tokens)
    const toSave = {
      ...rule,
      id: editingRuleId || `CUSTOM-${Date.now()}`,
      label: rule.label || `${rule.template}: ${rule.activation}${rule.target ? ` → ${rule.target}` : ''}`,
      min_gap_hours: rule.min_gap_hours ? parseFloat(rule.min_gap_hours) : undefined,
      max_gap_hours: rule.max_gap_hours ? parseFloat(rule.max_gap_hours) : undefined,
      activation_condition_expr: activationExpr || undefined,
      correlation_condition_expr: correlationExpr || undefined,
      category: 'custom',
    }
    const updated = editingRuleId
      ? savedRules.map(r => r.id === editingRuleId ? toSave : r)
      : [...savedRules, toSave]
    setSavedRules(updated)
    localStorage.setItem('studio_custom_rules', JSON.stringify(updated))
    onSaveRule?.(toSave)
    setEditingRuleId(null)
    setRule({
      template: '', activation: '', target: '',
      min_gap_hours: '', max_gap_hours: '',
      activation_tokens: [emptyCondToken()],
      correlation_tokens: [emptyCondToken()],
      label: '', rationale: '',
      severity: { clinical_consequence: 0.7, must_not_vs_should: 0.7 },
    })
    setStep('template')
  }

  function deleteCustomRule(id) {
    if (editingRuleId === id) cancelEdit()
    const updated = savedRules.filter(r => r.id !== id)
    setSavedRules(updated)
    localStorage.setItem('studio_custom_rules', JSON.stringify(updated))
  }

  function editRule(r) {
    setEditingRuleId(r.id)
    setRule({
      template: r.template,
      activation: r.activation,
      target: r.target,
      min_gap_hours: r.min_gap_hours ?? '',
      max_gap_hours: r.max_gap_hours ?? '',
      activation_tokens: r.activation_tokens || treeToTokens(r.activation_condition_tree ?? null),
      correlation_tokens: r.correlation_tokens || treeToTokens(r.correlation_condition_tree ?? null),
      label: r.label ?? '',
      rationale: r.rationale ?? '',
      severity: r.severity ?? { clinical_consequence: 0.7, must_not_vs_should: 0.7 },
    })
    setStep('activities')
  }

  function saveConditionInline(which) {
    if (!saveCondName.trim()) return
    const tokens = which === 'activation' ? rule.activation_tokens : rule.correlation_tokens
    const err = validateTokens(tokens)
    if (err) { setCondError(err); return }
    const expression = tokensToExpr(tokens)
    onSaveCustomDataCondition?.({ name: saveCondName.trim(), tokens, expression, data_items: [] })
    setSaveCondOpen(null); setSaveCondName(''); setCondError('')
  }

  function resetStep() {
    switch (step) {
      case 'template': updateRule({ template: '' }); break
      case 'activities': updateRule({ activation: '', target: '' }); break
      case 'time': updateRule({ min_gap_hours: '', max_gap_hours: '' }); break
      case 'conditions': updateRule({ activation_tokens: [emptyCondToken()], correlation_tokens: [emptyCondToken()] }); setCondError(''); break
      case 'metadata': updateRule({ label: '', rationale: '', severity: { clinical_consequence: 0.7, must_not_vs_should: 0.7 } }); break
    }
  }

  function cancelEdit() {
    setEditingRuleId(null)
    setRule({
      template: '', activation: '', target: '',
      min_gap_hours: '', max_gap_hours: '',
      activation_tokens: [emptyCondToken()],
      correlation_tokens: [emptyCondToken()],
      label: '', rationale: '',
      severity: { clinical_consequence: 0.7, must_not_vs_should: 0.7 },
    })
    setStep('template')
  }

  return (
    <div className="rule-builder">
      <div className="rule-builder-main">
        {/* Left: wizard */}
        <div className="rule-builder-wizard">
          <StepIndicator steps={STEPS} currentStep={step} />

          {rule.template && step !== 'template' && (
            <div className="selected-rule-banner">
              <span className="selected-rule-icon">{TEMPLATE_MAP[rule.template]?.icon}</span>
              <div className="selected-rule-info">
                <span className="selected-rule-name">{TEMPLATE_MAP[rule.template]?.label}</span>
                <span className="selected-rule-description">{TEMPLATE_MAP[rule.template]?.description}</span>
              </div>
              <span className="selected-rule-id">{rule.template}</span>
            </div>
          )}

          <div className="wizard-content">
            {/* Step 1: Template */}
            {step === 'template' && (
              <div className="wizard-step">
                <h3 className="wizard-step-title">What kind of rule do you want to define?</h3>
                {TEMPLATE_OPTIONS.map(group => (
                  <div key={group.group} className="template-group">
                    <h4 className="template-group-label">{group.group}</h4>
                    <div className="template-grid">
                      {group.items.map(t => (
                        <button
                          key={t.id}
                          type="button"
                          className={`template-card ${rule.template === t.id ? 'selected' : ''}`}
                          onClick={() => { updateRule({ template: t.id }); nextStep() }}
                        >
                          <span className="template-card-icon">{t.icon}</span>
                          <span className="template-card-name">{t.label}</span>
                          <span className="rule-template-badge">{t.id}</span>
                          <span className="template-card-desc">{t.description}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Step 2: Activities */}
            {step === 'activities' && (
              <div className="wizard-step">
                <h3 className="wizard-step-title">Which clinical events are involved?</h3>
                <div className="field-group">
                  <label className="field-label">Activation event [A]</label>
                  <select
                    className="studio-select"
                    value={rule.activation}
                    onChange={e => updateRule({ activation: e.target.value })}
                  >
                    <option value="">Select event…</option>
                    {['Ventilation events', ...Object.keys(activities)].includes('ventilation') && null}
                    {activities.ventilation?.length > 0 && (
                      <optgroup label="Ventilation events">
                        {activities.ventilation.map(a => <option key={a} value={a}>{a}</option>)}
                      </optgroup>
                    )}
                    {activities.sbt?.length > 0 && (
                      <optgroup label="SBT events">
                        {activities.sbt.map(a => <option key={a} value={a}>{a}</option>)}
                      </optgroup>
                    )}
                    {activities.assessment?.length > 0 && (
                      <optgroup label="Assessment events">
                        {activities.assessment.map(a => <option key={a} value={a}>{a}</option>)}
                      </optgroup>
                    )}
                    {activities.interventions?.length > 0 && (
                      <optgroup label="Interventions">
                        {activities.interventions.map(a => <option key={a} value={a}>{a}</option>)}
                      </optgroup>
                    )}
                    {activities.custom?.length > 0 && (
                      <optgroup label="Custom events">
                        {activities.custom.map(a => <option key={a} value={a}>{a}</option>)}
                      </optgroup>
                    )}
                    {allActivities.length === 0 && (
                      <option disabled>No activities loaded</option>
                    )}
                  </select>
                </div>
                {!isUnary && (
                  <div className="field-group">
                    <label className="field-label">Target event [B]</label>
                    <select
                      className="studio-select"
                      value={rule.target}
                      onChange={e => updateRule({ target: e.target.value })}
                    >
                      <option value="">Select event…</option>
                      {activities.ventilation?.length > 0 && (
                        <optgroup label="Ventilation events">
                          {activities.ventilation.map(a => <option key={a} value={a}>{a}</option>)}
                        </optgroup>
                      )}
                      {activities.sbt?.length > 0 && (
                        <optgroup label="SBT events">
                          {activities.sbt.map(a => <option key={a} value={a}>{a}</option>)}
                        </optgroup>
                      )}
                      {activities.assessment?.length > 0 && (
                        <optgroup label="Assessment events">
                          {activities.assessment.map(a => <option key={a} value={a}>{a}</option>)}
                        </optgroup>
                      )}
                      {activities.interventions?.length > 0 && (
                        <optgroup label="Interventions">
                          {activities.interventions.map(a => <option key={a} value={a}>{a}</option>)}
                        </optgroup>
                      )}
                      {activities.custom?.length > 0 && (
                        <optgroup label="Custom events">
                          {activities.custom.map(a => <option key={a} value={a}>{a}</option>)}
                        </optgroup>
                      )}
                    </select>
                  </div>
                )}
                <div className="define-event-trigger">
                  <span className="define-event-trigger-text">Can't find the event you're looking for?</span>
                  <button type="button" className="define-event-link" onClick={() => setShowEventModal(true)}>
                    Define it here
                  </button>
                </div>
              </div>
            )}

            {/* Step 3: Time */}
            {step === 'time' && (
              <div className="wizard-step">
                <h3 className="wizard-step-title">Is there a time constraint?</h3>
                <p className="wizard-step-hint">Leave blank for no time limit.</p>
                <div className="time-inputs">
                  <div className="field-group">
                    <label className="field-label">Minimum gap (hours)</label>
                    <input
                      className="studio-input"
                      type="number" min="0" step="0.5"
                      placeholder="e.g. 0"
                      value={rule.min_gap_hours}
                      onChange={e => updateRule({ min_gap_hours: e.target.value })}
                    />
                  </div>
                  <div className="field-group">
                    <label className="field-label">Maximum gap (hours)</label>
                    <input
                      className="studio-input"
                      type="number" min="0" step="0.5"
                      placeholder="e.g. 24"
                      value={rule.max_gap_hours}
                      onChange={e => updateRule({ max_gap_hours: e.target.value })}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Step 4: Data conditions */}
            {step === 'conditions' && (
              <div className="wizard-step">
                <h3 className="wizard-step-title">Add data conditions (optional)</h3>
                <p className="wizard-step-hint">
                  Specify clinical measurements that must meet thresholds. Use groups to nest AND/OR/NOT logic.
                </p>

                <div className="condition-section">
                  <div className="condition-section-header">
                    <h4>Conditions on activation event</h4>
                    <div className="condition-section-actions">
                      {customDataConditions.length > 0 && (
                        <select
                          className="studio-select studio-select--inline"
                          value=""
                          onChange={e => {
                            const cond = customDataConditions.find(c => c.id === e.target.value)
                            if (cond) updateRule({ activation_tokens: cond.tokens || treeToTokens(cond.tree) })
                          }}
                        >
                          <option value="">Load saved…</option>
                          {customDataConditions.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                      )}
                      <button type="button" className="define-event-link" onClick={() => setShowConditionModal(true)}>
                        Manage data conditions
                      </button>
                    </div>
                  </div>
                  <FormulaBuilder
                    tokens={rule.activation_tokens}
                    onChange={tokens => { setCondError(''); updateRule({ activation_tokens: tokens }) }}
                    itemOptions={itemOptions}
                    customDataConditions={customDataConditions}
                  />
                  {tokensToExpr(rule.activation_tokens) && (
                    saveCondOpen === 'activation' ? (
                      <div className="save-cond-inline">
                        <input
                          className="studio-input save-cond-name-input"
                          placeholder="Condition name…"
                          value={saveCondName}
                          onChange={e => setSaveCondName(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter') saveConditionInline('activation'); if (e.key === 'Escape') setSaveCondOpen(null) }}
                          autoFocus
                        />
                        <button type="button" className="btn-primary btn-sm" onClick={() => saveConditionInline('activation')} disabled={!saveCondName.trim()}>Save</button>
                        <button type="button" className="btn-secondary btn-sm" onClick={() => setSaveCondOpen(null)}>Cancel</button>
                      </div>
                    ) : (
                      <button type="button" className="save-cond-trigger" onClick={() => { setSaveCondOpen('activation'); setSaveCondName('') }}>
                        Save as reusable condition
                      </button>
                    )
                  )}
                </div>

                {!isUnary && (
                  <div className="condition-section">
                    <div className="condition-section-header">
                      <h4>Conditions on target event</h4>
                      <div className="condition-section-actions">
                        {customDataConditions.length > 0 && (
                          <select
                            className="studio-select studio-select--inline"
                            value=""
                            onChange={e => {
                              const cond = customDataConditions.find(c => c.id === e.target.value)
                              if (cond) updateRule({ correlation_tokens: cond.tokens || treeToTokens(cond.tree) })
                            }}
                          >
                            <option value="">Load saved…</option>
                            {customDataConditions.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                          </select>
                        )}
                        <button type="button" className="define-event-link" onClick={() => setShowConditionModal(true)}>
                          Manage data conditions
                        </button>
                      </div>
                    </div>
                    <FormulaBuilder
                      tokens={rule.correlation_tokens}
                      onChange={tokens => { setCondError(''); updateRule({ correlation_tokens: tokens }) }}
                      itemOptions={itemOptions}
                      customDataConditions={customDataConditions}
                    />
                    {tokensToExpr(rule.correlation_tokens) && (
                      saveCondOpen === 'correlation' ? (
                        <div className="save-cond-inline">
                          <input
                            className="studio-input save-cond-name-input"
                            placeholder="Condition name…"
                            value={saveCondName}
                            onChange={e => setSaveCondName(e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter') saveConditionInline('correlation'); if (e.key === 'Escape') setSaveCondOpen(null) }}
                            autoFocus
                          />
                          <button type="button" className="btn-primary btn-sm" onClick={() => saveConditionInline('correlation')} disabled={!saveCondName.trim()}>Save</button>
                          <button type="button" className="btn-secondary btn-sm" onClick={() => setSaveCondOpen(null)}>Cancel</button>
                        </div>
                      ) : (
                        <button type="button" className="save-cond-trigger" onClick={() => { setSaveCondOpen('correlation'); setSaveCondName('') }}>
                          Save as reusable condition
                        </button>
                      )
                    )}
                  </div>
                )}
                {condError && <div className="form-error" style={{ marginTop: '0.75rem' }}>{condError}</div>}
              </div>
            )}

            {/* Step 5: Metadata */}
            {step === 'metadata' && (
              <div className="wizard-step">
                <h3 className="wizard-step-title">Name and describe your rule</h3>
                <div className="field-group">
                  <label className="field-label">Rule label</label>
                  <input
                    className="studio-input"
                    type="text"
                    placeholder="e.g. Oxygenation must be checked before SBT"
                    value={rule.label}
                    onChange={e => updateRule({ label: e.target.value })}
                  />
                </div>
                <div className="field-group">
                  <label className="field-label">Clinical rationale</label>
                  <textarea
                    className="studio-textarea"
                    rows={3}
                    placeholder="Why is this rule clinically important?"
                    value={rule.rationale}
                    onChange={e => updateRule({ rationale: e.target.value })}
                  />
                </div>
                <div className="field-group">
                  <label className="field-label">
                    Clinical consequence
                    <span className="field-hint"> (0 = low, 100 = critical)</span>
                  </label>
                  <div className="slider-row">
                    <input
                      type="range" min="0" max="1" step="0.05"
                      value={rule.severity.clinical_consequence}
                      onChange={e => updateRule({ severity: { ...rule.severity, clinical_consequence: parseFloat(e.target.value) } })}
                    />
                    <span className="slider-val">{Math.round(rule.severity.clinical_consequence * 100)}%</span>
                  </div>
                </div>
                <div className="field-group">
                  <label className="field-label">
                    Must-not vs should-not
                    <span className="field-hint"> (0 = guideline, 100 = hard requirement)</span>
                  </label>
                  <div className="slider-row">
                    <input
                      type="range" min="0" max="1" step="0.05"
                      value={rule.severity.must_not_vs_should}
                      onChange={e => updateRule({ severity: { ...rule.severity, must_not_vs_should: parseFloat(e.target.value) } })}
                    />
                    <span className="slider-val">{Math.round(rule.severity.must_not_vs_should * 100)}%</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Wizard nav */}
          <div className="wizard-nav">
            {step !== 'template' && (
              <button type="button" className="wizard-back-btn" onClick={prevStep}>← Back</button>
            )}
            <div className="wizard-nav-spacer" />
            {editingRuleId ? (
              <button type="button" className="wizard-cancel-btn" onClick={cancelEdit}>Cancel</button>
            ) : rule.template ? (
              <button type="button" className="wizard-cancel-btn" onClick={resetStep}>Reset</button>
            ) : null}
            {step !== 'metadata' ? (
              <button
                type="button"
                className="wizard-next-btn"
                disabled={!canAdvance()}
                onClick={nextStep}
              >
                Continue →
              </button>
            ) : (
              <button type="button" className="wizard-save-btn" onClick={saveRule}>
                {editingRuleId ? 'Update Rule' : 'Save to My Rules'}
              </button>
            )}
          </div>
        </div>

        {/* Right: live preview */}
        <div className="rule-builder-preview">
          <h4 className="preview-title">Live preview</h4>
          <div className="preview-diagram-wrap">
            {rule.template ? (
              <DeclareVisualizer
                template={rule.template}
                activation={rule.activation || 'Event A'}
                target={rule.target || (UNARY_TEMPLATES.includes(rule.template) ? undefined : 'Event B')}
                compact={false}
              />
            ) : (
              <div className="preview-placeholder">Select a rule type to see a preview</div>
            )}
          </div>
          {rule.template && (
            <div className="preview-summary">
              <div className="preview-field">
                <span className="preview-field-key">Type</span>
                <span className="preview-field-val">{rule.template.replace(/_/g, ' ')}</span>
              </div>
              {rule.activation && (
                <div className="preview-field">
                  <span className="preview-field-key">Activation</span>
                  <span className="preview-field-val">{rule.activation}</span>
                </div>
              )}
              {rule.target && !UNARY_TEMPLATES.includes(rule.template) && (
                <div className="preview-field">
                  <span className="preview-field-key">Target</span>
                  <span className="preview-field-val">{rule.target}</span>
                </div>
              )}
              {(rule.min_gap_hours || rule.max_gap_hours) && (
                <div className="preview-field">
                  <span className="preview-field-key">Time window</span>
                  <span className="preview-field-val">
                    {rule.min_gap_hours && `min ${rule.min_gap_hours}h`}
                    {rule.min_gap_hours && rule.max_gap_hours && ' · '}
                    {rule.max_gap_hours && `max ${rule.max_gap_hours}h`}
                  </span>
                </div>
              )}
              {(() => {
                const expr = tokensToExpr(rule.activation_tokens)
                return expr ? (
                  <div className="preview-field">
                    <span className="preview-field-key">Activation cond.</span>
                    <span className="preview-field-val preview-field-val--expr" title={expr}>
                      {expr.length > 60 ? expr.slice(0, 57) + '…' : expr}
                    </span>
                  </div>
                ) : null
              })()}
              {!isUnary && (() => {
                const expr = tokensToExpr(rule.correlation_tokens)
                return expr ? (
                  <div className="preview-field">
                    <span className="preview-field-key">Target cond.</span>
                    <span className="preview-field-val preview-field-val--expr" title={expr}>
                      {expr.length > 60 ? expr.slice(0, 57) + '…' : expr}
                    </span>
                  </div>
                ) : null
              })()}
            </div>
          )}
        </div>
      </div>

      {/* My Rules section */}
      {savedRules.length > 0 && (
        <div className="my-rules-section">
          <h3 className="my-rules-title">My saved rules <span className="badge">{savedRules.length}</span></h3>
          <div className="my-rules-list">
            {savedRules.map(r => (
              <div key={r.id} className="my-rule-row">
                <DeclareVisualizer template={r.template} activation={r.activation} target={r.target} compact={true} />
                <div className="my-rule-info">
                  <span className="my-rule-label">{r.label}</span>
                  <span className="my-rule-template">{r.template.replace(/_/g, ' ')}</span>
                </div>
                <div className="my-rule-actions">
                  <button
                    type="button"
                    className="my-rule-edit-btn"
                    onClick={() => editRule(r)}
                    aria-label="Edit rule"
                  ><UilPen size="20" /></button>
                  <button
                    type="button"
                    className="my-rule-delete-btn"
                    onClick={() => deleteCustomRule(r.id)}
                    aria-label="Delete rule"
                  >×</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <CustomEventModal
        isOpen={showEventModal}
        onClose={() => setShowEventModal(false)}
        savedEventTypes={customEventTypes}
        onSave={onSaveCustomEvent}
        onDelete={onDeleteCustomEvent}
      />
      <DataConditionModal
        isOpen={showConditionModal}
        onClose={() => setShowConditionModal(false)}
        savedConditions={customDataConditions}
        onSave={onSaveCustomDataCondition}
        onDelete={onDeleteCustomDataCondition}
        itemOptions={itemOptions}
      />
    </div>
  )
}
