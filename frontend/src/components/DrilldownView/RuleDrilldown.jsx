import React, { useMemo } from 'react';
import { count, formatP, pct } from '../InsightsView/charts';
import { CAUSE_COLORS, MarginTertileForest, ValueHistogram } from '../InsightsView/storyCharts';
import { ruleLabel } from '../../ruleNames';
import '../StoryView/story.css';

// Rule drill-down: activations → satisfied | violated → why violated.
// Reads drilldown.json (case_study/10_frontend_insights.py); nothing is
// recomputed here.

const VIOLATED_COLOR = '#c62828';
const CAUSE_KEYS = ['undocumented', 'no_payload', 'partial_payload', 'unmet'];

const SHORT_LABEL = {
  satisfied: 'Satisfied',
  violated: 'Violated',
  undocumented: 'Not documented',
  no_payload: 'Reading without value',
  partial_payload: 'Partly documented',
  unmet: 'Assessed & not met',
};

const fmtValue = (v) => {
  if (v === null || v === undefined) return '–';
  const n = Number(v);
  if (Math.abs(n) >= 100) return n.toFixed(0);
  return Number(n.toPrecision(3)).toString();
};

const rrText = (g) => (g.rr === null || g.rr === undefined
  ? '–'
  : `${g.rr.toFixed(2)} [${g.rr_ci_low.toFixed(2)}, ${g.rr_ci_high.toFixed(2)}]`);

function groupColor(key) {
  if (key === 'violated') return VIOLATED_COLOR;
  return CAUSE_COLORS[key] || '#90a4ae';
}

/* Two-level split. Level 1 spans all activations; level 2 spans the violated
   episodes only, so its segments read as "share of violations". */
function SplitBars({ rule, groups, selected, onSelect }) {
  const c = rule.counts;
  const satShare = c.n_satisfied / c.n_activations;
  const causes = groups.filter((g) => g.key !== 'satisfied');

  const Seg = ({ k, share, n, label }) => (
    <button type="button"
            className={`drill-seg${selected === k ? ' selected' : ''}`}
            style={{ flexBasis: `${share * 100}%`, background: groupColor(k) }}
            onClick={() => onSelect(k)}
            title={`${label}: ${count(n)} (${pct(share)})`}>
      {share > 0.07 && (
        <span className="drill-seg-text">
          <strong>{label}</strong>
          <span>{count(n)} · {pct(share, 1)}</span>
        </span>
      )}
    </button>
  );

  return (
    <div className="drill-split">
      <div className="drill-split-level">
        <span className="drill-split-caption">All {count(c.n_activations)} SBT starts</span>
        <div className="drill-split-bar">
          <Seg k="satisfied" share={satShare} n={c.n_satisfied} label="Satisfied" />
          <Seg k="violated" share={1 - satShare} n={c.n_violated} label="Violated" />
        </div>
      </div>
      <svg className="drill-split-funnel" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
        <polygon points={`${satShare * 100},0 100,0 100,10 0,10`} />
      </svg>
      <div className="drill-split-level">
        <span className="drill-split-caption">The {count(c.n_violated)} violations, by cause</span>
        <div className="drill-split-bar">
          {causes.map((g) => (
            <Seg key={g.key} k={g.key} share={g.share_of_violated || 0} n={g.n} label={SHORT_LABEL[g.key]} />
          ))}
        </div>
      </div>
    </div>
  );
}

function GroupCard({ group, reference, selected, onSelect }) {
  const rate = group.success_rate || 0;
  const isRef = group.key === 'satisfied';
  const sig = group.significant;
  return (
    <button type="button" title={group.meaning}
            className={`drill-card${selected ? ' selected' : ''}`}
            style={{ borderTopColor: groupColor(group.key) }}
            onClick={() => onSelect(group.key)}>
      <div className="drill-card-head">
        <span className="drill-card-title">{SHORT_LABEL[group.key] || group.label}</span>
        {group.kind && group.kind !== 'satisfied' && (
          <span className={`drill-kind ${group.kind}`}>{group.kind === 'care' ? 'care' : 'documentation'}</span>
        )}
      </div>
      <div className="drill-card-n">
        {count(group.n)}
        <span>
          {isRef || group.key === 'violated'
            ? `${pct(group.share_of_activations)} of SBT starts`
            : `${pct(group.share_of_violated)} of violations`}
        </span>
      </div>
      <div className="drill-card-rate">
        <span className="drill-card-label">SBT success</span>
        <div className="insight-track thin">
          <div className="insight-track-ref" style={{ left: `${reference * 100}%` }} />
          <div className="insight-track-fill" style={{ width: `${rate * 100}%`, background: groupColor(group.key) }} />
        </div>
        <span className="drill-card-value">{pct(rate)}</span>
      </div>
      <div className="drill-card-rr">
        {isRef ? (
          <span className="drill-card-label">reference group</span>
        ) : (
          <>
            <span className="drill-card-label">RR vs satisfied</span>
            <span className="drill-card-value">{rrText(group)}</span>
            <span className={`insight-chip ${sig ? 'bad' : 'neutral'}`}>
              {sig ? 'significant' : 'n.s.'}
            </span>
          </>
        )}
      </div>
    </button>
  );
}

function AttemptComposition({ byAttempt, groups, selected }) {
  if (!byAttempt?.length) return null;
  const keys = groups.map((g) => g.key);
  const last = byAttempt[byAttempt.length - 1].bucket;
  return (
    <div className="insight-stacked">
      {byAttempt.map((b) => (
        <div key={b.bucket} className="drill-attempt-row">
          <span className="drill-attempt-label">
            Attempt {b.bucket}{b.bucket === last ? '+' : ''}
            <small>{count(b.n_activations)}</small>
          </span>
          <div className="insight-stack">
            {keys.map((k) => {
              const share = (b.counts?.[k] || 0) / (b.n_activations || 1);
              if (share <= 0) return null;
              const dim = selected && selected !== 'violated' && selected !== k;
              const dimViolated = selected === 'violated' && k === 'satisfied';
              return (
                <div key={k} className="insight-stack-seg"
                     style={{ width: `${share * 100}%`, background: groupColor(k),
                              opacity: dim || dimViolated ? 0.3 : 1 }}
                     title={`${SHORT_LABEL[k]}: ${pct(share)} of ${count(b.n_activations)}`}>
                  {share > 0.1 && <span>{pct(share, 0)}</span>}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function Examples({ rows, unit, onOpenTimeline }) {
  if (!rows?.length) return <p className="summary-empty">No example stays with a timeline file.</p>;
  return (
    <div className="drill-examples">
      {rows.map((ex) => (
        <div key={`${ex.stay_id}-${ex.episode_index}`} className="drill-example">
          <span className="drill-example-id">Stay {ex.stay_id}</span>
          <span className="drill-example-meta">episode {ex.episode_index}</span>
          <span className="drill-example-meta">
            {ex.value === null || ex.value === undefined ? 'no value' : `${fmtValue(ex.value)} ${unit || ''}`}
          </span>
          <span className={`insight-chip ${ex.outcome === 'success' ? 'good' : 'bad'}`}>{ex.outcome}</span>
          {onOpenTimeline && (
            <button type="button" className="drill-link" onClick={() => onOpenTimeline(ex.stay_id)}>
              Open timeline →
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

/* One sentence that states what this rule's split says. */
function takeaway(rule, groups) {
  const c = rule.counts;
  const unmet = groups.find((g) => g.key === 'unmet');
  const docShare = (c.n_undocumented + c.n_no_payload + c.n_partial_payload) / (c.n_violated || 1);
  const parts = [`${pct(docShare)} of the ${count(c.n_violated)} violations are documentation gaps`];
  if (unmet && unmet.n > 0) {
    parts.push(`only the ${pct(unmet.share_of_violated)} assessed and not met carry RR ${unmet.rr?.toFixed(2)}${unmet.significant ? '' : ' (n.s.)'}`);
  } else {
    parts.push('no reading was ever charted and found unmet');
  }
  const docs = groups.filter((g) => g.kind === 'documentation' && g.n >= 100);
  if (docs.length) {
    parts.push(docs.map((g) => `${SHORT_LABEL[g.key].toLowerCase()} RR ${g.rr?.toFixed(2)}${g.significant ? '' : ' (n.s.)'}`).join(', '));
  }
  return parts.join('; ') + '.';
}

export default function RuleDrilldown({ drilldown, ruleId, group, onChange, onOpenTimeline, compact = false }) {
  const order = drilldown?.order || [];
  const activeId = order.includes(ruleId) ? ruleId : order[0];
  const rule = drilldown?.rules?.[activeId];

  const groups = useMemo(() => (rule?.groups || []).filter((g) => g.n > 0), [rule]);

  const violatedGroup = useMemo(() => {
    if (!rule) return null;
    const c = rule.counts;
    return {
      key: 'violated',
      label: 'violated (any cause)',
      meaning: 'All violations together — what a binary verdict reports.',
      kind: null,
      n: c.n_violated,
      share_of_activations: c.n_violated / c.n_activations,
      success_rate: rule.all_violations?.success_rate,
      rr: rule.all_violations?.rr,
      rr_ci_low: rule.all_violations?.rr_ci_low,
      rr_ci_high: rule.all_violations?.rr_ci_high,
      significant: (rule.all_violations?.rr_ci_high ?? 1) < 1 || (rule.all_violations?.rr_ci_low ?? 1) > 1,
    };
  }, [rule]);

  if (!rule) return <p className="summary-empty">No drill-down data. Run <code>case_study/10_frontend_insights.py</code>.</p>;

  const selected = group && (group === 'violated' || groups.some((g) => g.key === group))
    ? group
    : (groups.find((g) => g.key === 'unmet') ? 'unmet' : 'violated');
  const selectedGroup = selected === 'violated' ? violatedGroup : groups.find((g) => g.key === selected);
  const reference = rule.reference_success_rate || 0;
  const select = (k) => onChange?.({ ruleId: activeId, group: k });

  const showHistogram = rule.histogram && (selected === 'unmet' || selected === 'satisfied' || selected === 'violated');
  const showMargins = rule.has_margin && selected === 'unmet' && rule.margin_strata?.length > 0;
  const examples = selected === 'violated'
    ? CAUSE_KEYS.flatMap((k) => (rule.examples?.[k] || []).slice(0, 2))
    : rule.examples?.[selected];

  return (
    <div className={`drill${compact ? ' compact' : ''}`}>
      <div className="drill-selector" role="tablist" aria-label="Readiness rule">
        {order.map((cid) => (
          <button key={cid} type="button" role="tab"
                  aria-selected={cid === activeId}
                  className={`drill-rule-chip${cid === activeId ? ' active' : ''}`}
                  title={drilldown.rules[cid]?.label}
                  onClick={() => onChange?.({ ruleId: cid, group: null })}>
            {ruleLabel(cid)}
          </button>
        ))}
        {drilldown.unsupported?.length > 0 && (
          <span className="drill-rule-chip disabled" title={drilldown.unsupported_reason}>
            +{drilldown.unsupported.length} rules without causes
          </span>
        )}
      </div>

      <section className="summary-card drill-header">
        <div className="drill-header-main">
          <span className="insight-row-id">{rule.constraint_id}</span>
          <h3>{rule.label}</h3>
          <p className="drill-criterion">{rule.criterion}</p>
        </div>
        <div className="drill-header-meta">
          <span><b>{rule.template}</b>({rule.target}, {rule.activation})</span>
          <span>window {rule.time_condition}</span>
          <span>target selection: <b>{rule.target_selection}</b></span>
        </div>
      </section>

      <section className="summary-card drill-split-card">
        <SplitBars rule={rule} groups={groups} selected={selected} onSelect={select} />
        {!compact && <p className="drill-takeaway">{takeaway(rule, groups)}</p>}
      </section>

      <div className="drill-cards">
        {groups.filter((g) => g.key === 'satisfied').map((g) => (
          <GroupCard key={g.key} group={g} reference={reference} selected={selected === g.key} onSelect={select} />
        ))}
        <GroupCard group={violatedGroup} reference={reference} selected={selected === 'violated'} onSelect={select} />
        {groups.filter((g) => g.key !== 'satisfied').map((g) => (
          <GroupCard key={g.key} group={g} reference={reference} selected={selected === g.key} onSelect={select} />
        ))}
      </div>

      <section className="summary-card drill-detail">
        <div className="drill-detail-head">
          <span className="insight-swatch" style={{ background: groupColor(selected) }} />
          <h3>{SHORT_LABEL[selected]}</h3>
          <span className="insight-row-meta">
            n = {count(selectedGroup?.n)} · success {pct(selectedGroup?.success_rate)}
            {selectedGroup?.value_median !== null && selectedGroup?.value_median !== undefined &&
              ` · median ${fmtValue(selectedGroup.value_median)} ${rule.unit}`}
            {selectedGroup?.p_bonferroni !== undefined && selectedGroup?.p_bonferroni !== null &&
              ` · p (Bonferroni, ${selectedGroup.n_tests} tests) = ${formatP(selectedGroup.p_bonferroni)}`}
          </span>
        </div>

        <div className="drill-detail-grid">
          {showHistogram ? (
            <div>
              <h4>Latest reading before the trial</h4>
              <ValueHistogram histogram={rule.histogram} height={compact ? 240 : 280} />
            </div>
          ) : (
            <div className="drill-novalue">
              <h4>No value to plot</h4>
              <p>
                {selected === 'undocumented' && 'No reading charted in the 24 h window.'}
                {selected === 'partial_payload' && 'Reading incomplete (e.g. SpO₂ without FiO₂ or PEEP).'}
                {selected === 'no_payload' && 'Charted without a usable value.'}
                {(selected === 'unmet' || selected === 'satisfied' || selected === 'violated') && 'Categorical criterion.'}
              </p>
            </div>
          )}
          <div>
            <h4>Composition by weaning attempt</h4>
            <AttemptComposition byAttempt={rule.by_attempt} groups={groups} selected={selected} />
          </div>
        </div>

        {showMargins && (
          <div>
            <h4>How far below the threshold? (tertiles of the miss)</h4>
            <MarginTertileForest strata={rule.margin_strata} />
          </div>
        )}

        <div>
          <h4>Example stays</h4>
          <Examples rows={examples} unit={rule.unit} onOpenTimeline={onOpenTimeline} />
        </div>
      </section>
    </div>
  );
}
