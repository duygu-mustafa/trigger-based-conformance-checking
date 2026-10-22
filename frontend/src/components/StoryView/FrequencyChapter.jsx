import React from 'react';
import { count, pct } from '../InsightsView/charts';
import { ActivationViolationBars, FAMILY_ORDER, PairHistogram } from '../InsightsView/storyCharts';
import { RULE_NAMES } from '../../ruleNames';
import { InfoTip, VacuityPanel } from './MorePanels';

// Chapter 2: activation vs violation rate for every rule, with a detail panel
// for the selected rule (replaces the old Frequencies page). Distributions come
// from frequency_detail.json (case_study/10_frontend_insights.py).

const TEMPLATE_TEXT = {
  PRECEDENCE: 'Precedence',
  RESPONSE: 'Response',
  NOT_RESPONSE: 'Not Response',
  NOT_RESPONDED_EXISTENCE: 'Not Responded Existence',
};

function RuleDetail({ rule, onDrill }) {
  if (!rule) return <p className="summary-empty">Select a rule.</p>;
  const isReadiness = rule.constraint_id.startsWith('RC-DP');
  const timing = rule.timing;
  const values = rule.values || [];

  return (
    <div className="freq-detail">
      <div className="freq-detail-head">
        <span className="insight-row-id">{rule.constraint_id}</span>
        <h3>{rule.label}</h3>
        <div className="freq-detail-meta">
          <span><b>{TEMPLATE_TEXT[rule.template] || rule.template}</b>({rule.activation} → {rule.target})</span>
          <span>{rule.time_window}</span>
          {rule.condition && <span>condition: <b>{rule.condition}</b></span>}
          <span>outcome: {rule.outcome_scope === 'next_episode' ? 'next episode' : 'same episode'}</span>
        </div>
      </div>

      <div className="story-kpis">
        <div className="story-kpi">
          <span className="story-kpi-value">{pct(rule.activation_rate)}</span>
          <span className="story-kpi-label">activated ({count(rule.n_activated)} of {count(rule.n_episodes)} episodes)</span>
        </div>
        <div className="story-kpi">
          <span className="story-kpi-value">{pct(rule.violation_rate_activated)}</span>
          <span className="story-kpi-label">violated among activations ({count(rule.n_violated)})</span>
        </div>
        <div className="story-kpi">
          <span className="story-kpi-value">
            {pct(rule.violation_rate_success, 0)} / {pct(rule.violation_rate_failure, 0)}
          </span>
          <span className="story-kpi-label">violation rate in successful / failed episodes</span>
        </div>
      </div>

      {values.map((v) => (
        <div key={v.key}>
          <h4>
            {v.label}
            {v.violated_kind === 'unmet' && (
              <InfoTip text="Violated = assessed and not met; documentation gaps have no value to plot." />
            )}
          </h4>
          <PairHistogram hist={v} xTitle={v.label}
                         violatedLabel={v.violated_kind === 'unmet' ? 'Assessed & not met' : 'Violated'} />
        </div>
      ))}

      {timing && (
        <div>
          <h4>
            Hours from activation to target
            {timing.n_violated < rule.n_violated && (
              <InfoTip text={`${timing.n_violated ? `${count(rule.n_violated - timing.n_violated)} of the` : 'The'} ${count(rule.n_violated)} violated activations found no target in the window.`} />
            )}
          </h4>
          <PairHistogram hist={timing} xTitle="hours" />
        </div>
      )}

      {!timing && values.length === 0 && (
        <p className="freq-note">
          {rule.condition
            ? 'This condition is categorical, so there is no numeric reading to plot.'
            : 'No distribution recorded for this rule: it has no data condition, and the checker keeps no delay for this template.'}
        </p>
      )}

      {isReadiness && onDrill && (
        <button type="button" className="story-btn" onClick={() => onDrill(rule.constraint_id)}>
          Why violated? Drill into {rule.constraint_id} →
        </button>
      )}
    </div>
  );
}

export default function FrequencyChapter({ insights, detail, selectedId, onSelect, onDrill }) {
  const rules = detail?.rules || {};
  // Default to the rule the bar chart puts on top (highest violation rate).
  const ids = (detail?.order || [])
    .filter((cid) => rules[cid])
    .sort((a, b) => (rules[b].violation_rate_activated || 0) - (rules[a].violation_rate_activated || 0));
  const active = rules[selectedId] ? selectedId : ids[0];
  // The picker lists rules by family, then by ID, so a rule is easy to find.
  const groups = insights.constraint_groups || {};
  const families = [...FAMILY_ORDER, 'Other']
    .map((family) => ({
      family,
      ids: ids
        .filter((cid) => (FAMILY_ORDER.includes(groups[cid]) ? groups[cid] : 'Other') === family)
        .sort((a, b) => a.localeCompare(b, undefined, { numeric: true })),
    }))
    .filter((g) => g.ids.length);
  return (
    <div className="story-grid freq-grid">
      <section className="summary-card story-panel">
        <h3>
          Activation and violation rate per rule
          <InfoTip text="Bar length is the share of episodes where the rule applies; the red part is the share where it was violated. The label gives the violation rate among activations, since a rule that never applies cannot be violated. Pick a rule on the right to see its distributions." />
        </h3>
        <ActivationViolationBars frequency={insights.violation_frequency} selectedId={active} />
      </section>
      <section className="summary-card story-panel">
        {detail && (
          <label className="freq-rule-picker">
            <span>Rule</span>
            <select className="summary-select" value={active || ''}
                    onChange={(e) => onSelect(e.target.value)}>
              {families.map((g) => (
                <optgroup key={g.family} label={g.family}>
                  {g.ids.map((cid) => (
                    <option key={cid} value={cid}>{cid} · {RULE_NAMES[cid] || rules[cid].label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
        )}
        {detail
          ? <RuleDetail rule={rules[active]} onDrill={onDrill} />
          : <div className="loading-spinner">Loading rule details…</div>}
      </section>
      <VacuityPanel insights={insights} />
    </div>
  );
}
