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

export function ConditionTree({ tree, onChange, itemOptions }) {
  const root = tree || { type: 'AND', children: [] }
  return (
    <div className="condition-tree">
      <ConditionGroup node={root} onChange={onChange} onRemove={null} itemOptions={itemOptions} depth={0} />
    </div>
  )
}
