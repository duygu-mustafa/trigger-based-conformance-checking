import React from 'react';
import {
  CauseStackedBars,
  DoseResponseChart,
  count,
  pct,
} from '../InsightsView/charts';
import {
  CAUSE_COLORS,
  EpisodesPerStayBars,
  MarginTertileForest,
} from '../InsightsView/storyCharts';
import RuleDrilldown from '../DrilldownView/RuleDrilldown';
import {
  CoViolationPanel,
  InfoTip,
  More,
  ProfilesPanel,
  SoleCriterionPanel,
} from './MorePanels';
import FrequencyChapter from './FrequencyChapter';
import OutcomeChapter from './OutcomeChapter';

// The case-study story, in the order of thesis §6.4. Each chapter states its
// finding as a short claim.

export const SHOWCASE_STAY_ID = '32007747';
export const DRILLDOWN_CHAPTER = 4;

// Cause bars in the thesis palette, matching the drill-down that follows.
const THESIS_CAUSE_PARTS = [
  { key: 'share_undocumented', label: 'Not documented in window', color: CAUSE_COLORS.undocumented },
  { key: 'share_partial_payload', label: 'Partly documented', color: CAUSE_COLORS.partial_payload },
  { key: 'share_unmet', label: 'Assessed & not met', color: CAUSE_COLORS.unmet },
];

// Degenerate estimate (violated almost only by successful episodes); hidden in
// the Statistics page too.
const HIDDEN_RR = ['SBT-TM-02'];

function Kpis({ items }) {
  return (
    <div className="story-kpis">
      {items.map((k) => (
        <div key={k.label} className="story-kpi">
          <span className="story-kpi-value">{k.value}</span>
          <span className="story-kpi-label">{k.label}</span>
        </div>
      ))}
    </div>
  );
}

const millions = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} M` : count(n));

/* How the cohort narrows from raw events to evaluable episodes. Each step
   names the operation that leads to the next one. */
function Funnel({ steps }) {
  return (
    <ol className="story-funnel">
      {steps.map((s, i) => (
        <li key={s.label} className="story-funnel-step">
          {i > 0 && <span className="story-funnel-op">↓ {s.op}</span>}
          <div className="story-funnel-row">
            <span className="story-funnel-value">{s.value}</span>
            <span className="story-funnel-label">
              {s.label}
              {s.note && <span className="story-funnel-note">{s.note}</span>}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Panel({ title, children, note }) {
  return (
    <section className="summary-card story-panel">
      {title && <h3>{title}<InfoTip text={note} /></h3>}
      {children}
    </section>
  );
}

// Opens one of the full-cohort explorer pages; App remembers the chapter.
function ExploreButton({ page, label, onExplore }) {
  if (!onExplore) return null;
  return (
    <button type="button" className="story-btn" onClick={() => onExplore(page)}>
      Explore → {label}
    </button>
  );
}

function ShowcaseStay({ insights, onOpenTimeline }) {
  const stays = insights?.showcase_stays || [];
  const stay = stays.find((s) => s.stay_id === SHOWCASE_STAY_ID) || stays[0];
  if (!stay) return <p className="summary-empty">No showcase stay exported.</p>;
  const labels = insights?.constraint_labels || {};
  const flip = stay.flips?.[0];
  const others = stays.filter((s) => s.stay_id !== stay.stay_id).slice(0, 3);

  const Episode = ({ index, outcome, violated }) => (
    <div className={`story-episode ${outcome}`}>
      <div className="story-episode-head">
        <span>Episode {index}</span>
        <span className={`insight-chip ${outcome === 'success' ? 'good' : 'bad'}`}>
          SBT {outcome === 'success' ? 'succeeded' : 'failed'}
        </span>
      </div>
      {flip && (
        <div className="story-episode-value">
          {flip.constraint_id}: <b>{outcome === 'success' ? flip.value_successful : flip.value_failed}</b> {flip.unit}
        </div>
      )}
      <div className="story-episode-list">
        {violated.length === 0
          ? <span className="story-episode-ok">no readiness rule violated</span>
          : violated.map((cid) => (
              <span key={cid} className="insight-mini-chip" title={labels[cid]}>{cid}</span>
            ))}
      </div>
    </div>
  );

  return (
    <div className="story-showcase">
      <div className="story-showcase-head">
        <div>
          <span className="insight-row-id">Stay {stay.stay_id}</span>
          <span className="insight-row-meta"> · {stay.n_episodes} ventilation episodes</span>
        </div>
        <button type="button" className="story-btn primary" onClick={() => onOpenTimeline?.(stay.stay_id)}>
          Open timeline →
        </button>
      </div>
      <div className="story-episodes">
        <Episode index={stay.failed_episode} outcome="failure" violated={stay.violated_in_failed || []} />
        <div className="story-episode-arrow">→</div>
        <Episode index={stay.successful_episode} outcome="success" violated={stay.violated_in_successful || []} />
      </div>
      {others.length > 0 && (
        <div className="story-showcase-others">
          <span>Other candidates:</span>
          {others.map((s) => (
            <button key={s.stay_id} type="button" className="drill-link" onClick={() => onOpenTimeline?.(s.stay_id)}
                    title={(s.flips || []).map((f) => `${f.constraint_id}: ${f.value_failed} → ${f.value_successful} ${f.unit}`).join('\n')}>
              {s.stay_id}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export const CHAPTERS = [
  {
    id: 1,
    tag: 'core',
    short: 'Cohort',
    claim: (i) => `${count(i.cohort?.n_stays)} ICU stays, ${count(i.cohort?.n_episodes)} weaning episodes`,
    render: ({ insights: i }) => {
      const c = i.cohort || {};
      return (
        <>
          <div className="story-grid two">
            <Panel title="From event log to episodes">
              <Funnel steps={[
                { value: millions(c.n_events), label: 'events in the log' },
                { op: 'grouped by ICU stay', value: count(c.n_stays), label: 'ICU stays',
                  note: `${count(c.n_patients)} patients` },
                { op: 'split at each intubation', value: count(c.n_episodes), label: 'weaning episodes' },
                { op: 'episodes that contain an SBT', value: count(c.n_episodes_evaluable), label: 'evaluable episodes',
                  note: `${pct(c.failure_rate_evaluable)} of SBTs failed` },
              ]} />
            </Panel>
            <Panel title="Episodes per stay"
                   note="Every episode is checked on its own: rules see only the events between two intubations.">
              <EpisodesPerStayBars rows={i.episodes_per_stay} />
            </Panel>
          </div>
          <More title="Data preparation: how much of the log the model uses">
            <Kpis items={[
              { label: `source tables`, value: count(c.n_source_tables) },
              { label: 'distinct activities in the log', value: count(c.n_distinct_activities) },
              { label: 'activities used by the rules', value: count(c.n_model_activities) },
              { label: `of events are model-relevant (${millions(c.n_model_activity_events)})`, value: pct(c.model_activity_share) },
            ]} />
          </More>
        </>
      );
    },
  },
  {
    id: 2,
    tag: 'optional',
    short: 'How often',
    claim: (i) => {
      const rows = i.violation_frequency || [];
      const mean = rows.reduce((s, r) => s + (r.violation_rate_activated || 0), 0) / (rows.length || 1);
      return `${rows.length} rules, ${pct(mean, 0)} mean violation rate`;
    },
    render: ({ insights: i, frequencyDetail, freqRule, onFreqRule, onDrillChange, goTo }) => (
      <FrequencyChapter insights={i} detail={frequencyDetail}
                        selectedId={freqRule} onSelect={onFreqRule}
                        onDrill={(cid) => { onDrillChange({ ruleId: cid, group: null }); goTo(DRILLDOWN_CHAPTER); }} />
    ),
  },
  {
    id: 3,
    tag: 'core',
    short: 'Why violated',
    ref: '§6.4.3',
    claim: (i) => `${pct(i.causes?.share_documentation)} of readiness violations are documentation gaps`,
    render: ({ insights: i, goTo }) => {
      const prof = Object.fromEntries((i.cause_profile || []).map((p) => [p.profile, p]));
      return (
        <div className="story-grid wide-left">
          <Panel title="Cause of each readiness violation"
                 note="RC-DP-06 (mental status) is left out, as in the thesis: it is categorical and almost never charted, so it has no graded reading to compare.">
            <CauseStackedBars
              causes={{ ...i.causes, per_constraint: (i.causes?.per_constraint || []).filter((r) => r.constraint_id !== 'RC-DP-06') }}
              parts={THESIS_CAUSE_PARTS} />
          </Panel>
          <Panel title="Does the cause matter for the outcome?"
                 note="Episode profile across the readiness rules; reference = all criteria satisfied.">
            <Kpis items={[
              { label: 'violated readiness checks (graded criteria)', value: count(i.causes?.n_violated_graded ?? i.causes?.n_violated) },
              { label: `SBT success, all criteria satisfied (n=${count(prof.all_satisfied?.n_exposed)})`, value: pct(prof.all_satisfied?.success_rate) },
              { label: `SBT success, documentation gaps only (n=${count(prof.documentation_only?.n_exposed)})`, value: pct(prof.documentation_only?.success_rate) },
              { label: `SBT success, any criterion assessed & unmet (n=${count(prof.any_unmet?.n_exposed)})`, value: pct(prof.any_unmet?.success_rate) },
            ]} />
            <button type="button" className="story-btn" onClick={() => goTo(DRILLDOWN_CHAPTER)}>
              Drill into one rule →
            </button>
          </Panel>
        </div>
      );
    },
  },
  {
    id: DRILLDOWN_CHAPTER,
    tag: 'core',
    short: 'Drill-down',
    ref: 'Table 6.5, Fig. 6.4',
    claim: () => 'Only “assessed and not met” tracks failure',
    render: ({ drilldown, drilldownError, drillSel, onDrillChange, onOpenTimeline }) => {
      if (drilldownError) return <p className="error-message">Could not load drilldown.json ({drilldownError}).</p>;
      if (!drilldown) return <div className="loading-spinner">Loading drill-down…</div>;
      return (
        <RuleDrilldown drilldown={drilldown} ruleId={drillSel.ruleId} group={drillSel.group}
                       onChange={onDrillChange} onOpenTimeline={onOpenTimeline} compact />
      );
    },
  },
  {
    id: 5,
    tag: 'core',
    short: 'Outcome',
    claim: (i) => {
      if (i.association_split) {
        const unmet = i.association_split.filter((r) => r.arm === 'unmet');
        const prot = unmet.filter((r) => r.significant_bonferroni && r.rr < 1).length;
        return `Unmet criteria lower SBT success for ${prot} of ${unmet.length} readiness rules`;
      }
      const rc = (i.association || []).filter((r) => r.constraint_id.startsWith('RC-DP'));
      const prot = rc.filter((r) => r.significant_bonferroni && r.rr < 1).length;
      return `Violation lowers SBT success for ${prot} of ${rc.length} readiness rules — RC-DP-07 and several post-failure rules point the other way.`;
    },
    render: ({ insights: i }) => <OutcomeChapter insights={i} hiddenIds={HIDDEN_RR} />,
  },
  {
    id: 6,
    tag: 'optional',
    short: 'Breadth & margin',
    claim: () => 'How many criteria are missed, and by how far, matters',
    render: ({ insights: i }) => (
      <div className="story-grid two">
        <Panel title="Breadth: criteria violated at SBT start"
               note={`Only ${pct(i.breadth?.share_no_readiness_violation)} of episodes satisfy every readiness criterion.`}>
          <DoseResponseChart breadth={i.breadth} />
        </Panel>
        <Panel title="Magnitude: unmet readings by how far they miss"
               note="Tertiles of the distance to the threshold, each compared with satisfied episodes of the same rule.">
          <MarginTertileForest strata={i.margin_strata} />
        </Panel>
        <SoleCriterionPanel insights={i} />
        <ProfilesPanel insights={i} />
        <CoViolationPanel insights={i} />
      </div>
    ),
  },
  {
    id: 7,
    tag: 'core',
    short: 'One patient',
    ref: 'Fig. 1.1',
    claim: () => 'One patient, two attempts, two verdicts',
    render: ({ insights, onOpenTimeline, onExplore }) => (
      <Panel>
        <ShowcaseStay insights={insights} onOpenTimeline={onOpenTimeline} />
        <ExploreButton page="results-patients" label="Patients (browse all stays)" onExplore={onExplore} />
      </Panel>
    ),
  },
];
