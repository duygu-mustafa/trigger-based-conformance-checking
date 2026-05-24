import React, { useState, useMemo } from 'react';
import { getConstraintIcon } from './SummaryView/utils';

const RulesOverview = ({ summaryData }) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('all'); // 'all', 'readiness', 'sbt', 'intervention'
  const [expandedRules, setExpandedRules] = useState({}); // { [ruleId]: boolean }

  const rules = useMemo(() => {
    const rawRules = summaryData?.violation_frequency || [];
    return [...rawRules].sort((a, b) => {
      const getWeight = (id) => {
        if (id.startsWith('RC-')) return 1;
        if (id.startsWith('SBT-')) return 2;
        if (id.startsWith('INT-')) return 3;
        return 4;
      };
      const wA = getWeight(a.constraint_id);
      const wB = getWeight(b.constraint_id);
      if (wA !== wB) return wA - wB;
      return a.constraint_id.localeCompare(b.constraint_id);
    });
  }, [summaryData]);

  // Helper to categorize a rule based on ID
  const getRuleCategoryInfo = (id) => {
    if (id.startsWith('RC-')) {
      return {
        key: 'readiness',
        label: 'Readiness Assessment',
        className: 'badge-readiness'
      };
    } else if (id.startsWith('SBT-')) {
      return {
        key: 'sbt',
        label: 'SBT Execution',
        className: 'badge-sbt'
      };
    } else if (id.startsWith('INT-')) {
      return {
        key: 'intervention',
        label: 'Failure Intervention',
        className: 'badge-intervention'
      };
    }
    return {
      key: 'other',
      label: 'Other',
      className: 'badge-other'
    };
  };

  // Toggle expanded view of a rule
  const toggleRule = (id) => {
    setExpandedRules(prev => ({
      ...prev,
      [id]: !prev[id]
    }));
  };

  // Expand or collapse all currently visible rules
  const toggleAll = (visibleRules, expand) => {
    const nextState = { ...expandedRules };
    visibleRules.forEach(r => {
      nextState[r.constraint_id] = expand;
    });
    setExpandedRules(nextState);
  };

  // Count helper
  const counts = useMemo(() => {
    let readiness = 0;
    let sbt = 0;
    let intervention = 0;
    
    rules.forEach(r => {
      const cat = getRuleCategoryInfo(r.constraint_id).key;
      if (cat === 'readiness') readiness++;
      else if (cat === 'sbt') sbt++;
      else if (cat === 'intervention') intervention++;
    });

    return {
      all: rules.length,
      readiness,
      sbt,
      intervention
    };
  }, [rules]);

  // Filtered rules based on search and category tab selection
  const filteredRules = useMemo(() => {
    return rules.filter(rule => {
      // 1. Category filter
      const cat = getRuleCategoryInfo(rule.constraint_id).key;
      if (activeCategory !== 'all' && cat !== activeCategory) {
        return false;
      }

      // 2. Search filter
      const normalizedQuery = searchQuery.toLowerCase().trim();
      if (!normalizedQuery) return true;

      const idMatch = rule.constraint_id.toLowerCase().includes(normalizedQuery);
      const labelMatch = (rule.constraint_label || '').toLowerCase().includes(normalizedQuery);
      const definitionMatch = (rule.rationale || '').toLowerCase().includes(normalizedQuery);
      const templateMatch = (rule.template || '').toLowerCase().includes(normalizedQuery);

      return idMatch || labelMatch || definitionMatch || templateMatch;
    });
  }, [rules, activeCategory, searchQuery]);

  // Helper to highlight matching text in search
  const highlightText = (text, highlight) => {
    if (!highlight.trim()) return text;
    const parts = String(text || '').split(new RegExp(`(${highlight.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')})`, 'gi'));
    return (
      <span>
        {parts.map((part, i) => 
          part.toLowerCase() === highlight.toLowerCase() 
            ? <mark key={i} className="search-highlight">{part}</mark> 
            : part
        )}
      </span>
    );
  };

  const isAllExpanded = useMemo(() => {
    if (filteredRules.length === 0) return false;
    return filteredRules.every(r => expandedRules[r.constraint_id]);
  }, [filteredRules, expandedRules]);

  return (
    <div className="rules-overview-container">
      <div className="rules-overview-header">
        <div className="title-group">
          <h2>Clinical Guideline Rules Reference</h2>
          <p className="subtitle">
            An overview of the {counts.all} declarative guidelines governing Readiness Assessment, SBT Execution, and Post-Failure Interventions.
          </p>
        </div>
      </div>

      {/* Toolbar: Search, Filters, and Expand/Collapse Controls */}
      <div className="rules-toolbar">
        <div className="search-and-filters">
          <div className="search-box-wrapper">
            <input
              type="text"
              className="rules-search-input"
              placeholder="Search by ID, label, keyword..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button 
                type="button" 
                className="clear-search-btn"
                onClick={() => setSearchQuery('')}
              >
                &times;
              </button>
            )}
          </div>

          <div className="category-tabs">
            <button
              type="button"
              className={`category-tab-btn ${activeCategory === 'all' ? 'active' : ''}`}
              onClick={() => setActiveCategory('all')}
            >
              All Rules <span className="tab-count">{counts.all}</span>
            </button>
            <button
              type="button"
              className={`category-tab-btn ${activeCategory === 'readiness' ? 'active' : ''}`}
              onClick={() => setActiveCategory('readiness')}
            >
              Readiness <span className="tab-count">{counts.readiness}</span>
            </button>
            <button
              type="button"
              className={`category-tab-btn ${activeCategory === 'sbt' ? 'active' : ''}`}
              onClick={() => setActiveCategory('sbt')}
            >
              SBT Execution <span className="tab-count">{counts.sbt}</span>
            </button>
            <button
              type="button"
              className={`category-tab-btn ${activeCategory === 'intervention' ? 'active' : ''}`}
              onClick={() => setActiveCategory('intervention')}
            >
              Interventions <span className="tab-count">{counts.intervention}</span>
            </button>
          </div>
        </div>

        <div className="bulk-actions">
          {filteredRules.length > 0 && (
            <button
              type="button"
              className="bulk-action-btn"
              onClick={() => toggleAll(filteredRules, !isAllExpanded)}
            >
              {isAllExpanded ? 'Collapse All' : 'Expand All'}
            </button>
          )}
        </div>
      </div>

      {/* Rules Catalog List */}
      <div className="rules-catalog">
        {filteredRules.length === 0 ? (
          <div className="no-rules-found">
            <p>No guidelines match your search query or selected category.</p>
            <button 
              type="button" 
              className="reset-filters-btn"
              onClick={() => { setSearchQuery(''); setActiveCategory('all'); }}
            >
              Reset Search & Filters
            </button>
          </div>
        ) : (
          filteredRules.map(rule => {
            const catInfo = getRuleCategoryInfo(rule.constraint_id);
            const isExpanded = !!expandedRules[rule.constraint_id];
            const icon = getConstraintIcon(rule.constraint_id);

            return (
              <div 
                key={rule.constraint_id} 
                className={`rule-card ${isExpanded ? 'expanded' : ''}`}
              >
                {/* Rule Card Header */}
                <div 
                  className="rule-card-header"
                  onClick={() => toggleRule(rule.constraint_id)}
                >
                  <div className="rule-card-title-section">
                    <span className="rule-id-monospaced">
                      {highlightText(rule.constraint_id, searchQuery)}
                    </span>
                    <span className={`rule-category-badge ${catInfo.className}`}>
                      {catInfo.label}
                    </span>
                    {icon && <img src={icon} alt="" className="rule-card-icon" />}
                    <h3 className="rule-card-label">
                      {highlightText(rule.constraint_label, searchQuery)}
                    </h3>
                  </div>
                  <button 
                    type="button" 
                    className="rule-card-expand-indicator"
                    aria-label={isExpanded ? 'Collapse rule details' : 'Expand rule details'}
                  >
                    <svg 
                      width="12" 
                      height="12" 
                      viewBox="0 0 24 24" 
                      fill="none" 
                      stroke="currentColor" 
                      strokeWidth="2.5" 
                      className={`expand-chevron ${isExpanded ? 'open' : ''}`}
                    >
                      <path d="M6 9l6 6 6-6" />
                    </svg>
                  </button>
                </div>

                {/* Rule Card Body Details (Collapsible) */}
                {isExpanded && (
                  <div className="rule-card-details">
                    {/* Definition / Clinical Rationale */}
                    <div className="rule-detail-section definition-box">
                      <h4>Clinical Definition & Rationale</h4>
                      <p className="rule-definition-text">
                        {highlightText(rule.rationale || 'No definition available for this rule.', searchQuery)}
                      </p>
                    </div>

                    {/* Technical Parameters & Logic */}
                    <div className={`rule-detail-section params-and-logic ${(rule.activation_condition || rule.target_condition) ? 'has-logic' : 'no-logic'}`}>
                      <div className="params-column">
                        <h4>Parameters</h4>
                        <div className="params-grid">
                          <div className="param-item">
                            <span className="param-label">Declare Template:</span>
                            <span className="param-value code-font">{rule.template || 'N/A'}</span>
                          </div>
                          
                          {rule.min_gap_hours !== null && rule.min_gap_hours !== undefined && (
                            <div className="param-item">
                              <span className="param-label">Min Gap:</span>
                              <span className="param-value">{rule.min_gap_hours} hours</span>
                            </div>
                          )}

                          {rule.max_gap_hours !== null && rule.max_gap_hours !== undefined && (
                            <div className="param-item">
                              <span className="param-label">Max Gap:</span>
                              <span className="param-value">{rule.max_gap_hours} hours</span>
                            </div>
                          )}

                          {rule.observation_window_hours !== null && rule.observation_window_hours !== undefined && (
                            <div className="param-item">
                              <span className="param-label">Obs. Window:</span>
                              <span className="param-value">{rule.observation_window_hours} hours</span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Logical Guards / Expressions (if present) */}
                      {(rule.activation_condition || rule.target_condition) && (
                        <div className="logic-column">
                          <h4>Technical Logic Condition</h4>
                          <div className="logic-blocks">
                            {rule.activation_condition && (
                              <div className="logic-block-item">
                                <span className="logic-label">Activation Guard:</span>
                                <pre className="logic-expr-code">
                                  <code>{rule.activation_condition}</code>
                                </pre>
                              </div>
                            )}
                            
                            {rule.target_condition && (
                              <div className="logic-block-item">
                                <span className="logic-label">Correlation Guard:</span>
                                <pre className="logic-expr-code">
                                  <code>{rule.target_condition}</code>
                                </pre>
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default RulesOverview;
