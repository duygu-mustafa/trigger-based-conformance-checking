import { useState, useEffect } from 'react'
import { UilPen } from '@iconscout/react-unicons'

const SOURCE_TABLE_OPTIONS = [
  { value: 'chartevents',    label: 'ICU chart (chartevents)' },
  { value: 'inputevents',    label: 'Medications / inputs (inputevents)' },
  { value: 'procedureevents', label: 'Procedures (procedureevents)' },
  { value: 'outputevents',   label: 'Fluid outputs (outputevents)' },
  { value: 'labevents',      label: 'Lab results (labevents)' },
  { value: 'bg',             label: 'Blood gas derived (bg)' },
]

const OPERATORS = ['>=', '<=', '==', '!=', '>', '<']

const VALUE_FILTER_COLUMNS = {
  chartevents:    ['valuenum', 'value'],
  inputevents:    ['amount'],
  procedureevents: [],
  outputevents:   ['value_num'],
  labevents:      ['valuenum', 'value'],
  bg:             ['value_num'],
}

const BG_FIXED_ITEMS = [
  { itemid: 'pao2fio2ratio', label: 'PaO2/FiO2 Ratio' },
  { itemid: 'fio2_bg',       label: 'FiO2 (Blood Gas)' },
  { itemid: 'ph_bg',         label: 'pH (Blood Gas)' },
  { itemid: 'hemoglobin_bg', label: 'Hemoglobin (Blood Gas)' },
]

function useDebounce(value, delay) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

function ItemSearch({ sourceTable, selectedItems, onAdd }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [manualId, setManualId] = useState('')
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
    if (!selectedItems.find(s => s.itemid === item.itemid)) {
      onAdd({ itemid: item.itemid, label: item.label || String(item.itemid) })
    }
    setQuery('')
    setResults([])
  }

  function addManual() {
    const id = parseInt(manualId)
    if (!id) return
    if (!selectedItems.find(s => s.itemid === id)) {
      onAdd({ itemid: id, label: String(id) })
    }
    setManualId('')
  }

  return (
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
  )
}

function QueryPreviewTable({ columns, rows }) {
  if (!columns || columns.length === 0) return null
  return (
    <div className="query-results-wrapper">
      <table className="query-results-table">
        <thead>
          <tr>{columns.map(c => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>{cell === null ? <em className="null-cell">null</em> : String(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EventTypeCard({ et, onDelete, onEdit }) {
  const isSql = et.kind === 'sql'
  const isVc = et.kind === 'value_change'
  const tableLabel = SOURCE_TABLE_OPTIONS.find(o => o.value === et.source_table)?.label || et.source_table

  function vcSummary(vc) {
    if (!vc) return null
    if (vc.value_type === 'numeric') {
      const from = `[${vc.prev_min ?? '–'}, ${vc.prev_max ?? '–'}]`
      const to = `[${vc.next_min ?? '–'}, ${vc.next_max ?? '–'}]`
      return `${from} → ${to}`
    }
    return `{${vc.prev_values.join(', ')}} → {${vc.next_values.join(', ')}}`
  }

  return (
    <div className="custom-event-card">
      <div className="custom-event-card-header">
        <span className="custom-event-card-name">{et.name}</span>
        <span className="custom-event-card-table">
          {isSql ? 'Custom SQL' : isVc ? `Value change · ${tableLabel}` : tableLabel}
        </span>
        <div className="custom-event-card-actions">
          <button
            type="button"
            className="custom-event-edit-btn"
            onClick={() => onEdit(et)}
            aria-label="Edit event type"
          ><UilPen size="25" /></button>
          <button
            type="button"
            className="condition-remove-btn"
            onClick={() => onDelete(et.id)}
            aria-label="Delete event type"
          >×</button>
        </div>
      </div>
      {isSql ? (
        <div className="custom-event-card-sql">
          <code>{et.sql?.length > 80 ? et.sql.slice(0, 80) + '…' : et.sql}</code>
        </div>
      ) : (
        <div className="custom-event-card-items">
          {et.selectedItems?.map(item => (
            <span key={item.itemid} className="item-chip">
              {item.itemid}: {item.label}
            </span>
          ))}
        </div>
      )}
      {isVc && et.value_change && (
        <div className="custom-event-card-filter">
          Transition: <code>{vcSummary(et.value_change)}</code>
        </div>
      )}
      {et.value_filter && (
        <div className="custom-event-card-filter">
          Filter: <code>{et.value_filter.column} {et.value_filter.operator} {et.value_filter.value}</code>
        </div>
      )}
    </div>
  )
}

export default function CustomEventBuilder({ savedEventTypes = [], onSave, onDelete }) {
  const [mode, setMode] = useState('table')

  // Table mode state
  const [name, setName] = useState('')
  const [sourceTable, setSourceTable] = useState('chartevents')
  const [selectedItems, setSelectedItems] = useState([])
  const [filterEnabled, setFilterEnabled] = useState(false)
  const [filterColumn, setFilterColumn] = useState('valuenum')
  const [filterOperator, setFilterOperator] = useState('>=')
  const [filterValue, setFilterValue] = useState('')

  // SQL mode state
  const [sqlName, setSqlName] = useState('')
  const [sql, setSql] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewResult, setPreviewResult] = useState(null)
  const [previewError, setPreviewError] = useState('')

  // Value-change mode state
  const [vcItem, setVcItem] = useState(null)
  const [vcValueType, setVcValueType] = useState('numeric')
  const [vcPrevMin, setVcPrevMin] = useState('')
  const [vcPrevMax, setVcPrevMax] = useState('')
  const [vcNextMin, setVcNextMin] = useState('')
  const [vcNextMax, setVcNextMax] = useState('')
  const [vcPrevValues, setVcPrevValues] = useState([])
  const [vcNextValues, setVcNextValues] = useState([])
  const [vcTagInput, setVcTagInput] = useState({ prev: '', next: '' })

  const [error, setError] = useState('')
  const [editingEventId, setEditingEventId] = useState(null)

  const filterCols = VALUE_FILTER_COLUMNS[sourceTable] || []

  function populateForm(et) {
    if (et.kind === 'sql') {
      setMode('sql')
      setSqlName(et.name)
      setSql(et.sql)
    } else if (et.kind === 'value_change') {
      setMode('value_change')
      setName(et.name)
      setSourceTable(et.source_table || 'chartevents')
      setVcItem(et.selectedItems?.[0] || null)
      const vc = et.value_change || {}
      setVcValueType(vc.value_type || 'numeric')
      setVcPrevMin(vc.prev_min != null ? String(vc.prev_min) : '')
      setVcPrevMax(vc.prev_max != null ? String(vc.prev_max) : '')
      setVcNextMin(vc.next_min != null ? String(vc.next_min) : '')
      setVcNextMax(vc.next_max != null ? String(vc.next_max) : '')
      setVcPrevValues(vc.prev_values || [])
      setVcNextValues(vc.next_values || [])
      setVcTagInput({ prev: '', next: '' })
    } else {
      setMode('table')
      setName(et.name)
      setSourceTable(et.source_table || 'chartevents')
      setSelectedItems(et.selectedItems || [])
      if (et.value_filter) {
        setFilterEnabled(true)
        setFilterColumn(et.value_filter.column)
        setFilterOperator(et.value_filter.operator)
        setFilterValue(String(et.value_filter.value))
      } else {
        setFilterEnabled(false)
        setFilterColumn('valuenum')
        setFilterOperator('>=')
        setFilterValue('')
      }
    }
    setEditingEventId(et.id)
    setError('')
  }

  function resetForm() {
    setName('')
    setSourceTable('chartevents')
    setSelectedItems([])
    setFilterEnabled(false)
    setFilterColumn('valuenum')
    setFilterOperator('>=')
    setFilterValue('')
    setSqlName('')
    setSql('')
    setPreviewResult(null)
    setPreviewError('')
    setVcItem(null)
    setVcValueType('numeric')
    setVcPrevMin('')
    setVcPrevMax('')
    setVcNextMin('')
    setVcNextMax('')
    setVcPrevValues([])
    setVcNextValues([])
    setVcTagInput({ prev: '', next: '' })
    setError('')
    setEditingEventId(null)
  }

  function handleModeSwitch(m) {
    setMode(m)
    setError('')
    setPreviewResult(null)
    setPreviewError('')
  }

  function handleSourceTableChange(t) {
    setSourceTable(t)
    setSelectedItems([])
    const cols = VALUE_FILTER_COLUMNS[t] || []
    setFilterColumn(cols[0] || '')
    if (cols.length === 0) setFilterEnabled(false)
  }

  function removeItem(itemid) {
    setSelectedItems(prev => prev.filter(s => s.itemid !== itemid))
  }

  async function handlePreview() {
    if (!sql.trim()) { setPreviewError('Enter a SQL query first.'); return }
    setPreviewLoading(true)
    setPreviewResult(null)
    setPreviewError('')
    try {
      const res = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql: sql.trim(), limit: 200 }),
      })
      const data = await res.json()
      if (!res.ok) {
        setPreviewError(data.detail || 'Query failed.')
      } else {
        setPreviewResult(data)
      }
    } catch (e) {
      setPreviewError('Network error: ' + e.message)
    } finally {
      setPreviewLoading(false)
    }
  }

  function handleSave() {
    if (mode === 'table') {
      if (!name.trim()) { setError('Name is required.'); return }
      if (selectedItems.length === 0) { setError('Select at least one item.'); return }
      const et = {
        kind: 'table',
        name: name.trim(),
        source_table: sourceTable,
        itemids: selectedItems.map(s => s.itemid),
        selectedItems,
        value_filter: filterEnabled && filterValue !== ''
          ? { column: filterColumn, operator: filterOperator, value: parseFloat(filterValue) || filterValue }
          : null,
      }
      if (editingEventId) et.id = editingEventId
      onSave(et)
      resetForm()
    } else if (mode === 'value_change') {
      if (!name.trim()) { setError('Name is required.'); return }
      if (!vcItem) { setError('Select an item.'); return }
      if (vcValueType === 'numeric') {
        const hasPrev = vcPrevMin !== '' || vcPrevMax !== ''
        const hasNext = vcNextMin !== '' || vcNextMax !== ''
        if (!hasPrev || !hasNext) { setError('Specify at least one bound for both "from" and "to" ranges.'); return }
      } else {
        if (vcPrevValues.length === 0 || vcNextValues.length === 0) {
          setError('Add at least one value to both "from" and "to" lists.'); return
        }
      }
      const et = {
        kind: 'value_change',
        name: name.trim(),
        source_table: sourceTable,
        itemids: [vcItem.itemid],
        selectedItems: [vcItem],
        value_filter: null,
        sql: null,
        value_change: {
          value_type: vcValueType,
          prev_min: vcPrevMin !== '' ? parseFloat(vcPrevMin) : null,
          prev_max: vcPrevMax !== '' ? parseFloat(vcPrevMax) : null,
          next_min: vcNextMin !== '' ? parseFloat(vcNextMin) : null,
          next_max: vcNextMax !== '' ? parseFloat(vcNextMax) : null,
          prev_values: vcPrevValues,
          next_values: vcNextValues,
        },
      }
      if (editingEventId) et.id = editingEventId
      onSave(et)
      resetForm()
    } else {
      if (!sqlName.trim()) { setError('Name is required.'); return }
      if (!sql.trim()) { setError('SQL query is required.'); return }
      const et = {
        kind: 'sql',
        name: sqlName.trim(),
        sql: sql.trim(),
        source_table: null,
        itemids: [],
        value_filter: null,
      }
      if (editingEventId) et.id = editingEventId
      onSave(et)
      resetForm()
    }
  }

  function cancelEdit() {
    resetForm()
  }

  return (
    <div className="custom-event-builder">
      <div className="builder-form-card">
        <h3 className="builder-section-title">Define a new event type</h3>

        <div className="mode-toggle">
          <button
            type="button"
            className={`mode-toggle-btn${mode === 'table' ? ' mode-toggle-btn--active' : ''}`}
            onClick={() => handleModeSwitch('table')}
          >
            Table lookup
          </button>
          <button
            type="button"
            className={`mode-toggle-btn${mode === 'value_change' ? ' mode-toggle-btn--active' : ''}`}
            onClick={() => handleModeSwitch('value_change')}
          >
            Value change
          </button>
          <button
            type="button"
            className={`mode-toggle-btn${mode === 'sql' ? ' mode-toggle-btn--active' : ''}`}
            onClick={() => handleModeSwitch('sql')}
          >
            Custom SQL
          </button>
        </div>

        {mode === 'value_change' ? (
          <>
            <div className="field-group">
              <label className="field-label">Activity name</label>
              <input
                className="studio-input"
                placeholder="e.g. SpO2Drop"
                value={name}
                onChange={e => setName(e.target.value)}
              />
              <span className="field-hint">Fires when the item transitions between the specified value ranges.</span>
            </div>

            <div className="field-group">
              <label className="field-label">MIMIC table</label>
              <select
                className="studio-select"
                value={sourceTable}
                onChange={e => { handleSourceTableChange(e.target.value); setVcItem(null) }}
              >
                {SOURCE_TABLE_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>

            <div className="field-group">
              <label className="field-label">Item</label>
              {vcItem ? (
                <div className="selected-items-chips">
                  <span className="item-chip item-chip--removable">
                    {vcItem.itemid}: {vcItem.label}
                    <button type="button" className="chip-remove" onClick={() => setVcItem(null)} aria-label="Remove item">×</button>
                  </span>
                </div>
              ) : (
                <ItemSearch
                  sourceTable={sourceTable}
                  selectedItems={vcItem ? [vcItem] : []}
                  onAdd={item => setVcItem(item)}
                />
              )}
            </div>

            <div className="field-group">
              <label className="field-label">Value type</label>
              <div className="vc-type-toggle">
                <label className="vc-radio-label">
                  <input type="radio" name="vcValueType" value="numeric" checked={vcValueType === 'numeric'} onChange={() => setVcValueType('numeric')} />
                  Numeric
                </label>
                <label className="vc-radio-label">
                  <input type="radio" name="vcValueType" value="categorical" checked={vcValueType === 'categorical'} onChange={() => setVcValueType('categorical')} />
                  Categorical
                </label>
              </div>
            </div>

            {vcValueType === 'numeric' ? (
              <div className="field-group">
                <label className="field-label">Transition range</label>
                <div className="vc-range-grid">
                  <div className="vc-range-col">
                    <span className="vc-range-header">From</span>
                    <div className="vc-range-row">
                      <input className="studio-input" type="number" step="any" placeholder="min" value={vcPrevMin} onChange={e => setVcPrevMin(e.target.value)} />
                      <span className="vc-range-sep">–</span>
                      <input className="studio-input" type="number" step="any" placeholder="max" value={vcPrevMax} onChange={e => setVcPrevMax(e.target.value)} />
                    </div>
                  </div>
                  <span className="vc-arrow">→</span>
                  <div className="vc-range-col">
                    <span className="vc-range-header">To</span>
                    <div className="vc-range-row">
                      <input className="studio-input" type="number" step="any" placeholder="min" value={vcNextMin} onChange={e => setVcNextMin(e.target.value)} />
                      <span className="vc-range-sep">–</span>
                      <input className="studio-input" type="number" step="any" placeholder="max" value={vcNextMax} onChange={e => setVcNextMax(e.target.value)} />
                    </div>
                  </div>
                </div>
                <span className="field-hint">Leave a bound empty to make it unbounded. At least one bound required in each side.</span>
              </div>
            ) : (
              <div className="field-group">
                <label className="field-label">Transition values</label>
                <div className="vc-cat-grid">
                  <div className="vc-cat-col">
                    <span className="vc-range-header">From</span>
                    <div className="vc-tag-input-row">
                      <input
                        className="studio-input"
                        placeholder="Add value…"
                        value={vcTagInput.prev}
                        onChange={e => setVcTagInput(t => ({ ...t, prev: e.target.value }))}
                        onKeyDown={e => {
                          if ((e.key === 'Enter' || e.key === ',') && vcTagInput.prev.trim()) {
                            e.preventDefault()
                            const v = vcTagInput.prev.trim()
                            if (!vcPrevValues.includes(v)) setVcPrevValues(prev => [...prev, v])
                            setVcTagInput(t => ({ ...t, prev: '' }))
                          }
                        }}
                      />
                      <button type="button" className="btn-secondary" onClick={() => {
                        const v = vcTagInput.prev.trim()
                        if (v && !vcPrevValues.includes(v)) setVcPrevValues(prev => [...prev, v])
                        setVcTagInput(t => ({ ...t, prev: '' }))
                      }}>Add</button>
                    </div>
                    <div className="selected-items-chips" style={{ marginTop: 6 }}>
                      {vcPrevValues.map(v => (
                        <span key={v} className="item-chip item-chip--removable">
                          {v}
                          <button type="button" className="chip-remove" onClick={() => setVcPrevValues(prev => prev.filter(x => x !== v))}>×</button>
                        </span>
                      ))}
                    </div>
                  </div>
                  <span className="vc-arrow">→</span>
                  <div className="vc-cat-col">
                    <span className="vc-range-header">To</span>
                    <div className="vc-tag-input-row">
                      <input
                        className="studio-input"
                        placeholder="Add value…"
                        value={vcTagInput.next}
                        onChange={e => setVcTagInput(t => ({ ...t, next: e.target.value }))}
                        onKeyDown={e => {
                          if ((e.key === 'Enter' || e.key === ',') && vcTagInput.next.trim()) {
                            e.preventDefault()
                            const v = vcTagInput.next.trim()
                            if (!vcNextValues.includes(v)) setVcNextValues(next => [...next, v])
                            setVcTagInput(t => ({ ...t, next: '' }))
                          }
                        }}
                      />
                      <button type="button" className="btn-secondary" onClick={() => {
                        const v = vcTagInput.next.trim()
                        if (v && !vcNextValues.includes(v)) setVcNextValues(next => [...next, v])
                        setVcTagInput(t => ({ ...t, next: '' }))
                      }}>Add</button>
                    </div>
                    <div className="selected-items-chips" style={{ marginTop: 6 }}>
                      {vcNextValues.map(v => (
                        <span key={v} className="item-chip item-chip--removable">
                          {v}
                          <button type="button" className="chip-remove" onClick={() => setVcNextValues(next => next.filter(x => x !== v))}>×</button>
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
                <span className="field-hint">Press Enter or comma to add. Compares against value_raw column.</span>
              </div>
            )}
          </>
        ) : mode === 'table' ? (
          <>
            <div className="field-group">
              <label className="field-label">Activity name</label>
              <input
                className="studio-input"
                placeholder="e.g. HeartRateMeasured"
                value={name}
                onChange={e => setName(e.target.value)}
              />
              <span className="field-hint">This name will appear as an activity in rule dropdowns.</span>
            </div>

            <div className="field-group">
              <label className="field-label">MIMIC table</label>
              <select
                className="studio-select"
                value={sourceTable}
                onChange={e => handleSourceTableChange(e.target.value)}
              >
                {SOURCE_TABLE_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>

            <div className="field-group">
              <label className="field-label">Items</label>
              {sourceTable === 'bg' ? (
                <div className="bg-fixed-items">
                  {BG_FIXED_ITEMS.map(item => {
                    const checked = !!selectedItems.find(s => s.itemid === item.itemid)
                    return (
                      <label key={item.itemid} className="bg-item-checkbox">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={e => {
                            if (e.target.checked) {
                              setSelectedItems(prev => [...prev, item])
                            } else {
                              setSelectedItems(prev => prev.filter(s => s.itemid !== item.itemid))
                            }
                          }}
                        />
                        <span>{item.label}</span>
                      </label>
                    )
                  })}
                </div>
              ) : (
                <>
                  <ItemSearch
                    sourceTable={sourceTable}
                    selectedItems={selectedItems}
                    onAdd={item => setSelectedItems(prev => [...prev, item])}
                  />
                  {selectedItems.length > 0 && (
                    <div className="selected-items-chips">
                      {selectedItems.map(item => (
                        <span key={item.itemid} className="item-chip item-chip--removable">
                          {item.itemid}: {item.label}
                          <button
                            type="button"
                            className="chip-remove"
                            onClick={() => removeItem(item.itemid)}
                            aria-label="Remove item"
                          >×</button>
                        </span>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            {filterCols.length > 0 && (
              <div className="field-group">
                <label className="field-label">
                  <input
                    type="checkbox"
                    checked={filterEnabled}
                    onChange={e => setFilterEnabled(e.target.checked)}
                    style={{ marginRight: 6 }}
                  />
                  Apply value filter (optional)
                </label>
                {filterEnabled && (
                  <div className="value-filter-row">
                    <select
                      className="studio-select"
                      value={filterColumn}
                      onChange={e => setFilterColumn(e.target.value)}
                      style={{ width: 130 }}
                    >
                      {filterCols.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                    <select
                      className="studio-select"
                      value={filterOperator}
                      onChange={e => setFilterOperator(e.target.value)}
                      style={{ width: 70 }}
                    >
                      {OPERATORS.map(op => <option key={op} value={op}>{op}</option>)}
                    </select>
                    <input
                      className="studio-input"
                      type="number" step="any"
                      placeholder="Value"
                      value={filterValue}
                      onChange={e => setFilterValue(e.target.value)}
                      style={{ width: 100 }}
                    />
                  </div>
                )}
              </div>
            )}
          </>
        ) : (
          <>
            <div className="field-group">
              <label className="field-label">Activity name</label>
              <input
                className="studio-input"
                placeholder="e.g. CustomLabEvent"
                value={sqlName}
                onChange={e => setSqlName(e.target.value)}
              />
              <span className="field-hint">This name will appear as an activity in rule dropdowns.</span>
            </div>

            <div className="field-group">
              <label className="field-label">SQL query</label>
              <textarea
                className="sql-editor"
                rows={10}
                placeholder={`SELECT stay_id, charttime AS event_time, valuenum AS value_num, valueuom AS unit\nFROM mimiciv_icu.chartevents\nWHERE itemid = 220045`}
                value={sql}
                onChange={e => setSql(e.target.value)}
                spellCheck={false}
              />
              <span className="field-hint">
                Must return <code>stay_id</code> and one of <code>event_time</code>, <code>charttime</code>, or <code>starttime</code>.
                Optional: <code>value_raw</code>, <code>value_num</code>, <code>unit</code>.
                During analysis, rows are automatically filtered to the sampled stays.
              </span>
            </div>

            <div className="field-group">
              <button
                type="button"
                className="btn-secondary"
                onClick={handlePreview}
                disabled={previewLoading}
              >
                {previewLoading ? 'Running…' : 'Preview query'}
              </button>
              {previewError && <div className="form-error" style={{ marginTop: 8 }}>{previewError}</div>}
              {previewResult && (
                <div style={{ marginTop: 12 }}>
                  <div className="field-hint" style={{ marginBottom: 6 }}>
                    {previewResult.count} row{previewResult.count !== 1 ? 's' : ''} returned
                    {previewResult.count === 200 ? ' (preview limit)' : ''}
                  </div>
                  <QueryPreviewTable columns={previewResult.columns} rows={previewResult.rows} />
                </div>
              )}
            </div>
          </>
        )}

        {error && <div className="form-error">{error}</div>}

        <div className="builder-actions">
          <button type="button" className="btn-primary" onClick={handleSave}>
            {editingEventId ? 'Update event type' : 'Save event type'}
          </button>
          {editingEventId ? (
            <button type="button" className="btn-secondary" onClick={cancelEdit}>
              Cancel
            </button>
          ) : (
            <button type="button" className="btn-secondary" onClick={resetForm}>
              Reset
            </button>
          )}
        </div>
      </div>

      {savedEventTypes.length > 0 && (
        <div className="saved-event-types">
          <h3 className="builder-section-title">Saved event types ({savedEventTypes.length})</h3>
          {savedEventTypes.map(et => (
            <EventTypeCard key={et.id} et={et} onDelete={onDelete} onEdit={populateForm} />
          ))}
        </div>
      )}
    </div>
  )
}
