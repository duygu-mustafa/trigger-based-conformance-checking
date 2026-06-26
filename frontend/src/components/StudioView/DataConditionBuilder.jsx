import { useState, useEffect } from 'react'
import { FormulaBuilder, tokensToExpr, validateTokens, treeToTokens, emptyCondToken } from './ConditionTree'
import { UilPen } from '@iconscout/react-unicons'

const SOURCE_TABLE_OPTIONS = [
  { value: 'chartevents',     label: 'ICU chart (chartevents)' },
  { value: 'inputevents',     label: 'Medications / inputs (inputevents)' },
  { value: 'procedureevents', label: 'Procedures (procedureevents)' },
  { value: 'outputevents',    label: 'Fluid outputs (outputevents)' },
  { value: 'labevents',       label: 'Lab results (labevents)' },
  { value: 'bg',              label: 'Blood gas derived (bg)' },
]

function useDebounce(value, delay) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

function TablesTab({ dataItems, onAdd }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [manualId, setManualId] = useState('')
  const [sourceTable, setSourceTable] = useState('chartevents')
  const debouncedQuery = useDebounce(query, 300)

  useEffect(() => {
    if (!debouncedQuery.trim()) { setResults([]); return }
    setLoading(true)
    fetch(`/api/item_search?q=${encodeURIComponent(debouncedQuery)}&table=${sourceTable}&limit=30`)
      .then(r => r.json())
      .then(data => { setResults(data); setLoading(false) })
      .catch(() => { setResults([]); setLoading(false) })
  }, [debouncedQuery, sourceTable])

  function addResult(item) {
    if (!dataItems.find(s => s.itemid === item.itemid && s.source_table === sourceTable))
      onAdd({ itemid: item.itemid, label: item.label || String(item.itemid), source_table: sourceTable })
    setQuery(''); setResults([])
  }

  function addManual() {
    const id = parseInt(manualId)
    if (!id) return
    if (!dataItems.find(s => s.itemid === id && s.source_table === sourceTable))
      onAdd({ itemid: id, label: String(id), source_table: sourceTable })
    setManualId('')
  }

  return (
    <div>
      <div className="field-group">
        <label className="field-label">Source table</label>
        <select className="studio-select" value={sourceTable} onChange={e => setSourceTable(e.target.value)}>
          {SOURCE_TABLE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>
      <div className="item-search">
        <div className="item-search-row">
          <input
            className="studio-input item-search-input"
            placeholder="Search items by label…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          <input
            className="studio-input item-search-manual"
            type="number"
            placeholder="itemid"
            value={manualId}
            onChange={e => setManualId(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addManual()}
            style={{ width: 90 }}
          />
          <button type="button" className="btn-secondary" onClick={addManual} style={{ whiteSpace: 'nowrap' }}>
            Add ID
          </button>
        </div>
        {loading && <div className="item-search-hint">Searching…</div>}
        {results.length > 0 && (
          <ul className="item-search-results">
            {results.map(r => (
              <li key={r.itemid}>
                <button type="button" className="item-search-result-btn" onClick={() => addResult(r)}>
                  <span className="item-search-result-label">{r.label}</span>
                  <span className="item-search-result-id">{r.itemid}</span>
                  {r.category && <span className="item-search-result-cat">{r.category}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function SqlTab({ onAdd }) {
  const [sql, setSql] = useState('')
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(new Set())

  function runPreview() {
    if (!sql.trim()) return
    setLoading(true); setError(''); setPreview(null); setSelected(new Set())
    fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql, limit: 100 }),
    })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail || 'Query failed')))
      .then(data => { setPreview(data); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }

  function toggleRow(i) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }

  function addSelected() {
    if (!preview) return
    const itemidIdx = preview.columns.indexOf('itemid')
    const labelIdx = preview.columns.indexOf('label')
    const tableIdx = preview.columns.indexOf('source_table')
    if (itemidIdx === -1) { setError('Query must return an "itemid" column.'); return }
    ;[...selected].forEach(i => {
      const row = preview.rows[i]
      onAdd({
        itemid: parseInt(row[itemidIdx]),
        label: labelIdx !== -1 ? String(row[labelIdx]) : String(row[itemidIdx]),
        source_table: tableIdx !== -1 ? String(row[tableIdx]) : 'custom',
      })
    })
    setSelected(new Set())
  }

  return (
    <div>
      <textarea
        className="studio-input"
        rows={4}
        placeholder="SELECT itemid, label FROM mimiciv_icu.d_items LIMIT 20"
        value={sql}
        onChange={e => setSql(e.target.value)}
        style={{ fontFamily: 'monospace', fontSize: '0.8rem', resize: 'vertical', width: '100%' }}
      />
      <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
        <button type="button" className="btn-secondary" onClick={runPreview} disabled={loading}>
          {loading ? 'Running…' : 'Preview'}
        </button>
        {selected.size > 0 && (
          <button type="button" className="btn-primary" onClick={addSelected}>
            Add {selected.size} row{selected.size !== 1 ? 's' : ''} to data
          </button>
        )}
      </div>
      {error && <div className="form-error" style={{ marginTop: '0.5rem' }}>{error}</div>}
      {preview && (
        <div style={{ marginTop: '0.75rem', overflowX: 'auto', maxHeight: 220, overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
            <thead>
              <tr>
                <th style={{ width: 28 }} />
                {preview.columns.map(c => (
                  <th key={c} style={{ textAlign: 'left', padding: '4px 8px', borderBottom: '1px solid var(--color-border, #2a3040)', color: 'var(--color-text-muted)' }}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, i) => (
                <tr key={i} onClick={() => toggleRow(i)} style={{ cursor: 'pointer', background: selected.has(i) ? 'var(--color-accent-subtle, rgba(99,179,237,0.1))' : 'transparent' }}>
                  <td style={{ textAlign: 'center', padding: '4px' }}>
                    <input type="checkbox" readOnly checked={selected.has(i)} />
                  </td>
                  {row.map((cell, j) => (
                    <td key={j} style={{ padding: '4px 8px', borderBottom: '1px solid var(--color-border-subtle, #1e2535)' }}>{String(cell ?? '')}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function DataConditionBuilder({ savedConditions = [], onSave, onDelete, itemOptions = [] }) {
  const [activeTab, setActiveTab] = useState('tables')
  const [name, setName] = useState('')
  const [tokens, setTokens] = useState([emptyCondToken()])
  const [dataItems, setDataItems] = useState([])
  const [editingId, setEditingId] = useState(null)
  const [error, setError] = useState('')

  function resetForm() {
    setName(''); setTokens([emptyCondToken()]); setDataItems([]); setEditingId(null); setError('')
  }

  function handleSave() {
    if (!name.trim()) { setError('Name is required.'); return }
    const validationError = validateTokens(tokens)
    if (validationError) { setError(validationError); return }
    const expr = tokensToExpr(tokens)
    onSave({ ...(editingId ? { id: editingId } : {}), name: name.trim(), tokens, expression: expr, data_items: dataItems })
    resetForm()
  }

  function populateForm(cond) {
    setName(cond.name)
    setTokens(cond.tokens || treeToTokens(cond.tree))
    setDataItems(cond.data_items || [])
    setEditingId(cond.id); setError('')
  }

  return (
    <div className="custom-event-builder">
      {savedConditions.length > 0 && (
        <div className="saved-event-types">
          <h3 className="saved-event-types-title">Saved data conditions</h3>
          {savedConditions.map(cond => (
            <div key={cond.id} className="custom-event-card">
              <div className="custom-event-card-header">
                <span className="custom-event-card-name">{cond.name}</span>
                <div className="custom-event-card-actions">
                  <button type="button" className="custom-event-edit-btn" onClick={() => populateForm(cond)} aria-label="Edit">
                    <UilPen size={14} />
                  </button>
                  <button type="button" className="condition-remove-btn" onClick={() => onDelete(cond.id)} aria-label="Delete">×</button>
                </div>
              </div>
              {cond.expression && (
                <div className="custom-event-card-sql">
                  <code>{cond.expression.length > 80 ? cond.expression.slice(0, 77) + '…' : cond.expression}</code>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div>
        <h3 className="builder-section-title">{editingId ? 'Edit condition' : 'New data condition'}</h3>

        {/* Data source tabs */}
        <div className="field-group">
          <label className="field-label">Data to load</label>
          <div style={{ display: 'flex', gap: '0.25rem', marginBottom: '0.75rem' }}>
            <button
              type="button"
              className={`sub-tab-btn${activeTab === 'tables' ? ' active' : ''}`}
              onClick={() => setActiveTab('tables')}
            >Tables</button>
            <button
              type="button"
              className={`sub-tab-btn${activeTab === 'sql' ? ' active' : ''}`}
              onClick={() => setActiveTab('sql')}
            >SQL</button>
          </div>
          {activeTab === 'tables'
            ? <TablesTab dataItems={dataItems} onAdd={item => setDataItems(prev => [...prev, item])} />
            : <SqlTab onAdd={item => setDataItems(prev => {
                if (prev.find(s => s.itemid === item.itemid && s.source_table === item.source_table)) return prev
                return [...prev, item]
              })} />
          }
        </div>

        {/* Selected data items */}
        {dataItems.length > 0 && (
          <div className="selected-items-chips" style={{ marginBottom: '1rem' }}>
            {dataItems.map((it, i) => (
              <span key={i} className="item-chip">
                {it.label} ({it.source_table})
                <button type="button" className="chip-remove" onClick={() => setDataItems(prev => prev.filter((_, j) => j !== i))} aria-label="Remove">×</button>
              </span>
            ))}
          </div>
        )}

        {error && <div className="form-error" style={{ marginBottom: '0.75rem' }}>{error}</div>}

        <div className="field-group">
          <label className="field-label">Condition name</label>
          <input
            className="studio-input"
            placeholder="e.g. good_oxygenation"
            value={name}
            onChange={e => setName(e.target.value)}
          />
        </div>

        <div className="field-group">
          <label className="field-label">Expression</label>
          <FormulaBuilder tokens={tokens} onChange={setTokens} itemOptions={[
            ...itemOptions,
            ...dataItems
              .filter(it => !itemOptions.find(o => o.key === String(it.itemid)))
              .map(it => ({ key: String(it.itemid), label: it.label }))
          ]} />
        </div>

        <div className="builder-actions">
          <button type="button" className="btn-primary" onClick={handleSave}>
            {editingId ? 'Update condition' : 'Save condition'}
          </button>
          {editingId && (
            <button type="button" className="btn-secondary" onClick={resetForm}>Cancel</button>
          )}
        </div>
      </div>
    </div>
  )
}
