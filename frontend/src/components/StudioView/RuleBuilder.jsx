import { useState, useEffect } from 'react'
import DeclareVisualizer from './DeclareVisualizer'

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

const OPERATORS = ['≥', '≤', '=', '≠', '>', '<']

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

// ── Condition tree ─────────────────────────────────────────────────────────
// leaf: { type:'leaf', item_key, item_label, operator, value }
// group: { type:'AND'|'OR', children: ConditionNode[] }
// not:  { type:'NOT', child: ConditionNode }

const REVERSE_OP_MAP = { '≥': '>=', '≤': '<=', '=': '==', '≠': '!=', '>': '>', '<': '<' }

function treeToExpr(node) {
  if (!node) return ''
  if (node.type === 'leaf') {
    if (!node.item_key || node.value === '') return ''
    const op = REVERSE_OP_MAP[node.operator] || node.operator
    const val = isNaN(parseFloat(node.value)) ? `'${node.value}'` : node.value
    return `items['${node.item_key}'] ${op} ${val}`
  }
  if (node.type === 'NOT') {
    const inner = treeToExpr(node.child)
    return inner ? `NOT (${inner})` : ''
  }
  const parts = (node.children || []).map(c => treeToExpr(c)).filter(Boolean).map(s => `(${s})`)
  if (!parts.length) return ''
  if (parts.length === 1) return parts[0].slice(1, -1)
  return parts.join(` ${node.type} `)
}

function migrateFlat(conditions, logic) {
  if (!conditions?.length) return null
  return { type: logic || 'AND', children: conditions.map(c => ({ type: 'leaf', ...c })) }
}

function ConditionLeaf({ node, onChange, onRemove, itemOptions }) {
  return (
    <div className="condition-row">
      <select
        className="condition-select condition-select--item"
        value={node.item_key || ''}
        onChange={e => {
          const opt = itemOptions.find(o => o.key === e.target.value)
          onChange({ ...node, item_key: e.target.value, item_label: opt?.label || e.target.value })
        }}
        aria-label="Clinical measurement"
      >
        <option value="">Select measurement…</option>
        {itemOptions.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
      </select>
      <select
        className="condition-select condition-select--op"
        value={node.operator || '≥'}
        onChange={e => onChange({ ...node, operator: e.target.value })}
        aria-label="Comparison operator"
      >
        {OPERATORS.map(op => <option key={op} value={op}>{op}</option>)}
      </select>
      <input
        className="condition-input"
        type="number" step="any" placeholder="Value"
        value={node.value || ''}
        onChange={e => onChange({ ...node, value: e.target.value })}
        aria-label="Threshold value"
      />
      <button className="condition-remove-btn" onClick={onRemove} type="button" aria-label="Remove condition">×</button>
    </div>
  )
}

function ConditionNode({ node, onChange, onRemove, itemOptions, depth }) {
  if (node.type === 'leaf') {
    return <ConditionLeaf node={node} onChange={onChange} onRemove={onRemove} itemOptions={itemOptions} />
  }
  return <ConditionGroup node={node} onChange={onChange} onRemove={onRemove} itemOptions={itemOptions} depth={depth} />
}

function ConditionGroup({ node, onChange, onRemove, itemOptions, depth = 0 }) {
  const indent = depth > 0 ? { marginLeft: depth * 14 } : {}

  if (node.type === 'NOT') {
    return (
      <div className="condition-group condition-group--not" style={indent}>
        <div className="condition-group-header">
          <span className="condition-group-not-badge">NOT</span>
          {onRemove && (
            <button className="condition-remove-btn" type="button" onClick={onRemove} aria-label="Remove NOT group">×</button>
          )}
        </div>
        <ConditionNode
          node={node.child || { type: 'AND', children: [] }}
          onChange={child => onChange({ ...node, child })}
          onRemove={null}
          itemOptions={itemOptions}
          depth={depth + 1}
        />
      </div>
    )
  }

  return (
    <div className="condition-group" style={indent}>
      <div className="condition-group-header">
        <div className="logic-toggle">
          {['AND', 'OR'].map(l => (
            <button key={l} type="button" className={`logic-btn ${node.type === l ? 'active' : ''}`}
              onClick={() => onChange({ ...node, type: l })}>{l}</button>
          ))}
        </div>
        {onRemove && (
          <button className="condition-remove-btn" type="button" onClick={onRemove} aria-label="Remove group">×</button>
        )}
      </div>
      {(node.children || []).map((child, i) => (
        <ConditionNode
          key={i} node={child}
          onChange={updated => onChange({ ...node, children: node.children.map((c, j) => j === i ? updated : c) })}
          onRemove={() => onChange({ ...node, children: node.children.filter((_, j) => j !== i) })}
          itemOptions={itemOptions}
          depth={depth + 1}
        />
      ))}
      <div className="condition-add-row">
        <button type="button" className="add-condition-btn"
          onClick={() => onChange({ ...node, children: [...(node.children || []), { type: 'leaf', item_key: '', item_label: '', operator: '≥', value: '' }] })}>
          + Condition
        </button>
        <button type="button" className="add-condition-btn"
          onClick={() => onChange({ ...node, children: [...(node.children || []), { type: 'OR', children: [] }] })}>
          + Group
        </button>
        <button type="button" className="add-condition-btn"
          onClick={() => onChange({ ...node, children: [...(node.children || []), { type: 'NOT', child: { type: 'AND', children: [] } }] })}>
          + NOT
        </button>
      </div>
    </div>
  )
}

function ConditionTree({ tree, onChange, itemOptions }) {
  const root = tree || { type: 'AND', children: [] }
  return (
    <div className="condition-tree">
      <ConditionGroup node={root} onChange={onChange} onRemove={null} itemOptions={itemOptions} depth={0} />
    </div>
  )
}

export default function RuleBuilder({ activities = {}, itemLabels = {}, onSaveRule }) {
  const [step, setStep] = useState('template')
  const [rule, setRule] = useState({
    template: '',
    activation: '',
    target: '',
    min_gap_hours: '',
    max_gap_hours: '',
    activation_condition_tree: null,
    correlation_condition_tree: null,
    label: '',
    rationale: '',
    severity: { clinical_consequence: 0.7, must_not_vs_should: 0.7 },
  })
  const [savedRules, setSavedRules] = useState(() => {
    try {
      const raw = JSON.parse(localStorage.getItem('studio_custom_rules') || '[]')
      return raw.map(r => ({
        ...r,
        activation_condition_tree: r.activation_condition_tree
          ?? migrateFlat(r.activation_conditions, r.activation_logic),
        correlation_condition_tree: r.correlation_condition_tree
          ?? migrateFlat(r.correlation_conditions, r.correlation_logic),
      }))
    }
    catch { return [] }
  })

  const isUnary = UNARY_TEMPLATES.includes(rule.template)
  const allActivities = activities.all || []

  // Build item options list from itemLabels (hide internal/derived ids)
  const itemOptions = Object.entries(itemLabels)
    .filter(([key]) => !key.startsWith('derived_') && !['sbt_status', 'sbt_outcome'].includes(key))
    .map(([key, label]) => ({ key, label: label.split('#')[0].trim() }))
    .sort((a, b) => a.label.localeCompare(b.label))

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
    const idx = STEPS.findIndex(s => s.id === step)
    if (idx < STEPS.length - 1) setStep(STEPS[idx + 1].id)
  }

  function prevStep() {
    const idx = STEPS.findIndex(s => s.id === step)
    if (idx > 0) setStep(STEPS[idx - 1].id)
  }

  function saveRule() {
    const activationExpr = treeToExpr(rule.activation_condition_tree)
    const correlationExpr = treeToExpr(rule.correlation_condition_tree)
    const toSave = {
      ...rule,
      id: `CUSTOM-${Date.now()}`,
      label: rule.label || `${rule.template}: ${rule.activation}${rule.target ? ` → ${rule.target}` : ''}`,
      min_gap_hours: rule.min_gap_hours ? parseFloat(rule.min_gap_hours) : undefined,
      max_gap_hours: rule.max_gap_hours ? parseFloat(rule.max_gap_hours) : undefined,
      activation_condition_expr: activationExpr || undefined,
      correlation_condition_expr: correlationExpr || undefined,
      category: 'custom',
    }
    const updated = [...savedRules, toSave]
    setSavedRules(updated)
    localStorage.setItem('studio_custom_rules', JSON.stringify(updated))
    onSaveRule?.(toSave)
    setRule({
      template: '', activation: '', target: '',
      min_gap_hours: '', max_gap_hours: '',
      activation_condition_tree: null,
      correlation_condition_tree: null,
      label: '', rationale: '',
      severity: { clinical_consequence: 0.7, must_not_vs_should: 0.7 },
    })
    setStep('template')
  }

  function deleteCustomRule(id) {
    const updated = savedRules.filter(r => r.id !== id)
    setSavedRules(updated)
    localStorage.setItem('studio_custom_rules', JSON.stringify(updated))
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
                    </select>
                  </div>
                )}
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
                  </div>
                  <ConditionTree
                    tree={rule.activation_condition_tree}
                    onChange={tree => updateRule({ activation_condition_tree: tree })}
                    itemOptions={itemOptions}
                  />
                </div>

                {!isUnary && (
                  <div className="condition-section">
                    <div className="condition-section-header">
                      <h4>Conditions on target event</h4>
                    </div>
                    <ConditionTree
                      tree={rule.correlation_condition_tree}
                      onChange={tree => updateRule({ correlation_condition_tree: tree })}
                      itemOptions={itemOptions}
                    />
                  </div>
                )}
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
                Save to My Rules
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
              {rule.activation_condition_tree && (() => {
                const expr = treeToExpr(rule.activation_condition_tree)
                return expr ? (
                  <div className="preview-field">
                    <span className="preview-field-key">Activation cond.</span>
                    <span className="preview-field-val preview-field-val--expr" title={expr}>
                      {expr.length > 60 ? expr.slice(0, 57) + '…' : expr}
                    </span>
                  </div>
                ) : null
              })()}
              {!isUnary && rule.correlation_condition_tree && (() => {
                const expr = treeToExpr(rule.correlation_condition_tree)
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
                <button
                  type="button"
                  className="my-rule-delete-btn"
                  onClick={() => deleteCustomRule(r.id)}
                  aria-label="Delete rule"
                >×</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
