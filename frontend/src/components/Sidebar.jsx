const NAV_GROUPS = [
  {
    label: 'Configure',
    items: [
      { id: 'library', label: 'Rule Library' },
      { id: 'builder', label: 'Rule Builder' },
    ],
  },
  {
    label: 'Analyze',
    items: [
      { id: 'runner', label: 'Run Analysis' },
    ],
  },
  {
    label: 'Results',
    items: [
      { id: 'results-frequencies', label: 'Frequencies' },
      { id: 'results-statistics', label: 'Statistics' },
      { id: 'results-patients', label: 'Patients' },
    ],
  },
]



function IconLibrary() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="2" y="2" width="5" height="12" rx="1" stroke="currentColor" strokeWidth="1.5"/>
      <rect x="9" y="2" width="5" height="12" rx="1" stroke="currentColor" strokeWidth="1.5"/>
    </svg>
  )
}

function IconBuilder() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M2 12.5l7-7 2 2-7 7H2v-2z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/>
      <path d="M11 3l2 2-1.5 1.5-2-2L11 3z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/>
    </svg>
  )
}

function IconRunner() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5"/>
      <path d="M6.5 5.5l4 2.5-4 2.5V5.5z" fill="currentColor"/>
    </svg>
  )
}

function IconFrequencies() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="2" y="10" width="2.5" height="4" rx="0.5" fill="currentColor"/>
      <rect x="6" y="6" width="2.5" height="8" rx="0.5" fill="currentColor"/>
      <rect x="10" y="3" width="2.5" height="11" rx="0.5" fill="currentColor"/>
    </svg>
  )
}

function IconStatistics() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="2" y="2" width="12" height="12" rx="1.5" stroke="currentColor" strokeWidth="1.4"/>
      <line x1="2" y1="6" x2="14" y2="6" stroke="currentColor" strokeWidth="1"/>
      <line x1="2" y1="10" x2="14" y2="10" stroke="currentColor" strokeWidth="1"/>
      <line x1="6" y1="2" x2="6" y2="14" stroke="currentColor" strokeWidth="1"/>
    </svg>
  )
}

function IconPatients() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="6" cy="5" r="2.5" stroke="currentColor" strokeWidth="1.5"/>
      <path d="M1 13c0-2.8 2.2-5 5-5s5 2.2 5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <circle cx="12.5" cy="5" r="1.8" stroke="currentColor" strokeWidth="1.3"/>
      <path d="M10 13c0-1.5.8-2.8 2-3.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    </svg>
  )
}

function IconCollapse() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <path d="M7.5 2L3.5 6l4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function IconExpand() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <path d="M4.5 2l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

const ICON_MAP = {
  library: IconLibrary,
  builder: IconBuilder,
  runner: IconRunner,
  'results-frequencies': IconFrequencies,
  'results-statistics': IconStatistics,
  'results-patients': IconPatients,
}

function NavItem({ item, activePage, onNavigate }) {
  const Icon = ICON_MAP[item.id] || (() => null)
  const isActive = activePage === item.id
  return (
    <button
      type="button"
      className={`sidebar-nav-item${isActive ? ' active' : ''}`}
      onClick={() => onNavigate(item.id)}
      title={item.label}
      aria-current={isActive ? 'page' : undefined}
    >
      <span className="sidebar-nav-icon"><Icon /></span>
      <span className="sidebar-nav-label">{item.label}</span>
    </button>
  )
}

export default function Sidebar({ activePage, onNavigate, collapsed, onToggle }) {
  return (
    <aside className={`app-sidebar${collapsed ? ' collapsed' : ''}`} aria-label="Main navigation">
      <div className="sidebar-header">
        {!collapsed && (
          <div className="sidebar-brand">
            <span className="sidebar-brand-eyebrow">ICU Weaning</span>
            <span className="sidebar-brand-name">Conformance Report</span>
          </div>
        )}
        <button
          type="button"
          className="sidebar-toggle-btn"
          onClick={onToggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <IconExpand /> : <IconCollapse />}
        </button>
      </div>

      <nav className="sidebar-nav" role="navigation">
        {NAV_GROUPS.map((group, gi) => (
          <div key={group.label} className="sidebar-group">
            {gi > 0 && <div className="sidebar-divider" />}
            <span className="sidebar-group-label">{group.label}</span>
            {group.items.map(item => (
              <NavItem key={item.id} item={item} activePage={activePage} onNavigate={onNavigate} />
            ))}
          </div>
        ))}


      </nav>
    </aside>
  )
}
