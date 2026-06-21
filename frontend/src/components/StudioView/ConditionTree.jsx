import { useState, useRef, useEffect } from 'react'

export const OPERATORS = ['≥', '≤', '=', '≠', '>', '<']
export const REVERSE_OP_MAP = { '≥': '>=', '≤': '<=', '=': '==', '≠': '!=', '>': '>', '<': '<' }

export function treeToExpr(node) {
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

export function migrateFlat(conditions, logic) {
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
  const [collapsed, setCollapsed] = useState(false)
  const depthClass = `condition-group--depth-${depth % 4}`

  if (node.type === 'NOT') {
    return (
      <div className={`condition-group condition-group--not ${depthClass}`}>
        <div className="condition-group-header">
          <button type="button" className="condition-collapse-btn" onClick={() => setCollapsed(c => !c)} aria-label={collapsed ? 'Expand' : 'Collapse'}>
            <span className={`condition-collapse-chevron${collapsed ? ' collapsed' : ''}`}>›</span>
          </button>
          <span className="condition-group-not-badge">NOT</span>
          {onRemove && (
            <button className="condition-remove-btn" type="button" onClick={onRemove} aria-label="Remove NOT group">×</button>
          )}
        </div>
        {!collapsed && (
          <div className="condition-group-children">
            <ConditionNode
              node={node.child || { type: 'AND', children: [] }}
              onChange={child => onChange({ ...node, child })}
              onRemove={null}
              itemOptions={itemOptions}
              depth={depth + 1}
            />
          </div>
        )}
      </div>
    )
  }

  const childCount = (node.children || []).length
  return (
    <div className={`condition-group ${depthClass}`}>
      <div className="condition-group-header">
        <button type="button" className="condition-collapse-btn" onClick={() => setCollapsed(c => !c)} aria-label={collapsed ? 'Expand' : 'Collapse'}>
          <span className={`condition-collapse-chevron${collapsed ? ' collapsed' : ''}`}>›</span>
        </button>
        <div className="logic-toggle">
          {['AND', 'OR'].map(l => (
            <button key={l} type="button" className={`logic-btn ${node.type === l ? 'active' : ''}`}
              onClick={() => onChange({ ...node, type: l })}>{l}</button>
          ))}
        </div>
        {collapsed && childCount > 0 && (
          <span className="condition-collapsed-count">{childCount} condition{childCount !== 1 ? 's' : ''}</span>
        )}
        {onRemove && (
          <button className="condition-remove-btn" type="button" onClick={onRemove} aria-label="Remove group">×</button>
        )}
      </div>
      {!collapsed && (
        <div className="condition-group-children">
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
      )}
    </div>
  )
}

export function ConditionTree({ tree, onChange, itemOptions }) {
  const root = tree || { type: 'AND', children: [] }
  return (
    <div className="condition-tree">
      <ConditionGroup node={root} onChange={onChange} onRemove={null} itemOptions={itemOptions} depth={0} />
    </div>
  )
}

// ── Formula builder (flat token model) ───────────────────────────────────────

export const emptyCondToken = () => ({ type: 'cond', item_key: '', item_label: '', operator: '≥', value: '', negated: false })

export function tokensToExpr(tokens) {
  return (tokens || []).flatMap(t => {
    if (t.type === 'op') return [t.value]
    if (t.type === 'open') return [t.negated ? 'NOT (' : '(']
    if (t.type === 'close') return [')']
    if (!t.item_key || t.value === '') return []
    const op = REVERSE_OP_MAP[t.operator] || t.operator
    const val = isNaN(parseFloat(t.value)) ? `'${t.value}'` : t.value
    const leaf = `items['${t.item_key}'] ${op} ${val}`
    return [t.negated ? `NOT (${leaf})` : leaf]
  }).join(' ')
}

export function validateTokens(tokens) {
  const toks = tokens || []
  let depth = 0
  let condCount = 0
  let prev = null

  for (let i = 0; i < toks.length; i++) {
    const t = toks[i]

    // Bracket balance + empty-brackets
    if (t.type === 'open') {
      depth++
    } else if (t.type === 'close') {
      depth--
      if (depth < 0) return 'Closing bracket with no matching opening bracket'
      if (prev?.type === 'open') return 'Empty brackets are not allowed'
    } else if (t.type === 'cond') {
      if (!t.item_key || t.value === '') return 'All conditions must have a measurement and value'
      condCount++
    }

    // Adjacency checks (only AND/OR ops; NOT is a flag on cond/open tokens, not a separate op)
    if (prev === null) {
      if (t.type === 'op') return 'Expression cannot start with an operator'
    } else {
      const p = prev.type
      const c = t.type
      if (p === 'op' && c === 'op')    return 'Two operators in a row'
      if (p === 'op' && c === 'close') return 'Operator before closing bracket'
      if (p === 'cond' && c === 'cond') return 'Missing operator between conditions'
      if (p === 'cond' && c === 'open') return 'Missing operator before opening bracket'
      if (p === 'close' && c === 'cond') return 'Missing operator after closing bracket'
      if (p === 'close' && c === 'open') return 'Missing operator between brackets'
      if (p === 'open' && c === 'op')  return 'Operator right after opening bracket'
    }

    prev = t
  }

  if (depth > 0) return `${depth} unclosed bracket${depth !== 1 ? 's' : ''}`
  if (prev?.type === 'op') return 'Expression cannot end with an operator'
  if (prev?.type === 'open') return 'Opening bracket is never closed'
  if (condCount === 0) return 'At least one condition is required'

  // Check no mixed AND/OR at same bracket depth
  const opsByDepth = {}
  let d = 0
  for (const t of toks) {
    if (t.type === 'open') { d++; continue }
    if (t.type === 'close') { d--; continue }
    if (t.type === 'op') {
      if (!opsByDepth[d]) opsByDepth[d] = new Set()
      opsByDepth[d].add(t.value)
    }
  }
  for (const ops of Object.values(opsByDepth)) {
    if (ops.size > 1) return 'Cannot mix AND and OR at the same level — use brackets, e.g. a AND (b OR c)'
  }

  return null
}

export function validateTokensOptional(tokens) {
  const toks = tokens || []
  // Only the default single-empty-cond state counts as "no condition"
  if (toks.length === 1 && toks[0].type === 'cond' && !toks[0].item_key) return null
  return validateTokens(tokens)
}

export function treeToTokens(node) {
  if (!node) return [emptyCondToken()]
  if (node.type === 'leaf') {
    return [{ type: 'cond', item_key: node.item_key || '', item_label: node.item_label || '', operator: node.operator || '≥', value: String(node.value ?? ''), negated: false }]
  }
  if (node.type === 'NOT') {
    const inner = treeToTokens(node.child)
    if (inner.length === 1 && inner[0].type === 'cond') inner[0].negated = true
    return inner
  }
  const op = node.type
  const children = node.children || []
  if (!children.length) return [emptyCondToken()]
  return children.flatMap((child, i) =>
    i === 0 ? treeToTokens(child) : [{ type: 'op', value: op }, ...treeToTokens(child)]
  )
}

function FormulaCondCard({ token, onChange, onRemove, itemOptions }) {
  return (
    <div className={`formula-cond-card${token.negated ? ' formula-cond-card--negated' : ''}`}>
      <button
        type="button"
        className={`formula-not-toggle${token.negated ? ' active' : ''}`}
        onClick={() => onChange({ ...token, negated: !token.negated })}
        title="Toggle NOT"
      >NOT</button>
      <select
        className="condition-select condition-select--item"
        value={token.item_key || ''}
        onChange={e => {
          const opt = itemOptions.find(o => o.key === e.target.value)
          onChange({ ...token, item_key: e.target.value, item_label: opt?.label || e.target.value })
        }}
        aria-label="Measurement"
      >
        <option value="">Select measurement…</option>
        {itemOptions.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
      </select>
      <select
        className="condition-select condition-select--op"
        value={token.operator || '≥'}
        onChange={e => onChange({ ...token, operator: e.target.value })}
        aria-label="Operator"
      >
        {OPERATORS.map(op => <option key={op} value={op}>{op}</option>)}
      </select>
      <input
        className="condition-input"
        type="number" step="any" placeholder="Value"
        value={token.value || ''}
        onChange={e => onChange({ ...token, value: e.target.value })}
        aria-label="Value"
      />
      <button type="button" className="condition-remove-btn" onClick={onRemove} aria-label="Remove">×</button>
    </div>
  )
}

function FormulaInserter({ pos, onInsert, customDataConditions }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    function onDown(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  function insert(tokens) { onInsert(pos, tokens); setOpen(false) }

  return (
    <div className="formula-inserter" ref={ref}>
      <button type="button" className="formula-inserter-btn" onClick={() => setOpen(o => !o)} aria-label="Insert here">+</button>
      {open && (
        <div className="formula-inserter-popover">
          <button type="button" className="formula-inserter-action" onClick={() => insert([emptyCondToken()])}>Condition</button>
          <button type="button" className="formula-inserter-action formula-inserter-action--bracket" onClick={() => insert([{ type: 'open', negated: false }])}>(</button>
          <button type="button" className="formula-inserter-action formula-inserter-action--bracket" onClick={() => insert([{ type: 'close' }])}>)</button>
          <button type="button" className="formula-inserter-action formula-inserter-action--op" onClick={() => insert([{ type: 'op', value: 'AND' }])}>AND</button>
          <button type="button" className="formula-inserter-action formula-inserter-action--op" onClick={() => insert([{ type: 'op', value: 'OR' }])}>OR</button>
          {customDataConditions && customDataConditions.length > 0 && (
            <select
              className="formula-inserter-datacond"
              defaultValue=""
              onChange={e => {
                const cond = customDataConditions.find(c => String(c.id) === e.target.value)
                if (cond) insert(cond.tokens || [emptyCondToken()])
              }}
            >
              <option value="" disabled>Data condition…</option>
              {customDataConditions.map(c => <option key={c.id} value={String(c.id)}>{c.name}</option>)}
            </select>
          )}
        </div>
      )}
    </div>
  )
}

export function FormulaBuilder({ tokens, onChange, itemOptions, customDataConditions = [] }) {
  const toks = tokens && tokens.length ? tokens : [emptyCondToken()]

  function updateToken(i, updated) { onChange(toks.map((t, j) => j === i ? updated : t)) }

  function removeToken(i) {
    const t = toks[i]
    let next = [...toks]
    if (t.type === 'cond') {
      if (i > 0 && next[i - 1]?.type === 'op') next.splice(i - 1, 2)
      else if (i < next.length - 1 && next[i + 1]?.type === 'op') next.splice(i, 2)
      else next.splice(i, 1)
      onChange(next.length ? next : [emptyCondToken()])
    } else {
      next.splice(i, 1)
      onChange(next.length ? next : [emptyCondToken()])
    }
  }

  function insertTokens(i, newTokens) {
    const next = [...toks]
    next.splice(i, 0, ...newTokens)
    onChange(next)
  }

  function flipOp(i) { onChange(toks.map((t, j) => j === i ? { ...t, value: t.value === 'AND' ? 'OR' : 'AND' } : t)) }
  function flipNot(i) { onChange(toks.map((t, j) => j === i ? { ...t, negated: !t.negated } : t)) }

  function addCondition(opValue) { onChange([...toks, { type: 'op', value: opValue }, emptyCondToken()]) }
  function addOpen() { onChange([...toks, { type: 'open', negated: false }]) }
  function addClose() { onChange([...toks, { type: 'close' }]) }

  function renderToken(t, i) {
    if (t.type === 'op') {
      return <button key={i} type="button" className="formula-op" onClick={() => flipOp(i)} title="Click to switch AND/OR">{t.value}</button>
    }
    if (t.type === 'open') {
      return (
        <div key={i} className={`formula-bracket formula-bracket--open${t.negated ? ' formula-bracket--not' : ''}`}>
          <button type="button" className={`formula-not-toggle${t.negated ? ' active' : ''}`} onClick={() => flipNot(i)} title="Toggle NOT before bracket">NOT</button>
          <span className="formula-bracket-char">(</span>
          <button type="button" className="condition-remove-btn" onClick={() => removeToken(i)} aria-label="Remove bracket">×</button>
        </div>
      )
    }
    if (t.type === 'close') {
      return (
        <div key={i} className="formula-bracket formula-bracket--close">
          <span className="formula-bracket-char">)</span>
          <button type="button" className="condition-remove-btn" onClick={() => removeToken(i)} aria-label="Remove bracket">×</button>
        </div>
      )
    }
    return <FormulaCondCard key={i} token={t} onChange={u => updateToken(i, u)} onRemove={() => removeToken(i)} itemOptions={itemOptions} />
  }

  return (
    <div className="formula-builder">
      <div className="formula-strip">
        <FormulaInserter pos={0} onInsert={insertTokens} customDataConditions={customDataConditions} />
        {toks.map((t, i) => (
          <div key={i} className="formula-token-slot">
            {renderToken(t, i)}
            <FormulaInserter pos={i + 1} onInsert={insertTokens} customDataConditions={customDataConditions} />
          </div>
        ))}
      </div>
      <div className="formula-actions">
        <button type="button" className="formula-add-btn" onClick={() => addCondition('AND')}>+ AND</button>
        <button type="button" className="formula-add-btn" onClick={() => addCondition('OR')}>+ OR</button>
        <button type="button" className="formula-add-btn formula-add-btn--bracket" onClick={addOpen}>( open</button>
        <button type="button" className="formula-add-btn formula-add-btn--bracket" onClick={addClose}>close )</button>
      </div>
    </div>
  )
}
