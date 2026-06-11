import Timeline from './Timeline'

function IconBack() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M10 2L4 8l6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

export default function TimelineDrawer({ stayId, caseData, caseIds, loading, onClose, onChangeStay }) {
  return (
    <div className="timeline-fullpage">
      <div className="timeline-fullpage-header">
        <button
          type="button"
          className="timeline-back-btn"
          onClick={onClose}
          aria-label="Back to previous page"
        >
          <IconBack />
          <span>Back</span>
        </button>
        <span className="timeline-fullpage-title">Patient Timeline</span>
        <div className="timeline-fullpage-case-selector">
          <label htmlFor="timeline-case-select">Case</label>
          <select
            id="timeline-case-select"
            value={stayId}
            onChange={e => onChangeStay(e.target.value)}
          >
            {caseIds.map(id => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="timeline-fullpage-body">
        {loading ? (
          <div className="timeline-fullpage-loading">Loading case {stayId}…</div>
        ) : caseData ? (
          <Timeline data={caseData} />
        ) : (
          <div className="timeline-fullpage-loading">No data available for case {stayId}.</div>
        )}
      </div>
    </div>
  )
}
