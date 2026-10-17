export default function GenericResults({ summary }) {
  const constraints = summary?.constraints || []

  return (
    <div className="generic-results">
      <div className="runner-kpis">
        <div className="kpi-card">
          <span className="kpi-value">{summary.num_cases}</span>
          <span className="kpi-label">Cases</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-value">{summary.num_events}</span>
          <span className="kpi-label">Events</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-value">{constraints.length}</span>
          <span className="kpi-label">Rules checked</span>
        </div>
      </div>

      {summary.warnings?.length > 0 && (
        <div className="runner-warnings">
          {summary.warnings.map((w, i) => <p key={i} className="runner-warning">⚠ {w}</p>)}
        </div>
      )}

      {constraints.length === 0 && <p className="runner-empty">No rules were evaluated.</p>}

      {constraints.length > 0 && (
        <table className="run-stays-table">
          <thead>
            <tr>
              <th>Rule</th>
              <th>Template</th>
              <th>Satisfied</th>
              <th>Violated</th>
              <th>Vacuous</th>
              <th>Violation rate</th>
              <th>Violating cases</th>
            </tr>
          </thead>
          <tbody>
            {constraints.map(c => (
              <tr key={c.id}>
                <td>{c.label}</td>
                <td>{c.template}</td>
                <td>{c.satisfied}</td>
                <td>{c.violated}</td>
                <td>{c.vacuous}</td>
                <td>{(c.violation_rate * 100).toFixed(1)}%</td>
                <td>{c.violating_case_ids.slice(0, 10).join(', ')}{c.violating_case_ids.length > 10 ? '…' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
