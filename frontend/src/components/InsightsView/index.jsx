import React, { useMemo, useState } from 'react';
import {
  AttemptTrendChart,
  CauseStackedBars,
  CoViolationHeatmap,
  DoseResponseChart,
  MixedOutcomeBars,
  ProfileBars,
  SoleCriterionList,
  count,
  pct,
} from './charts';

const TABS = [
  { id: 'magnitude', label: 'Magnitude' },
  { id: 'breadth', label: 'Breadth' },
  { id: 'quality', label: 'Data quality' },
  { id: 'overtime', label: 'Over time' },
];

const MAX_TREND_SERIES = 6;

function Kpi({ label, value, sub }) {
  return (
    <section className="summary-card metric-card">
      <h3>{label}</h3>
      <p className="metric-value">{value}</p>
      {sub && <p className="metric-subtext">{sub}</p>}
    </section>
  );
}

function Card({ title, lead, note, children }) {
  return (
    <section className="summary-card insight-card">
      <div className="section-header">
        <div className="title-group">
          <h3>{title}</h3>
          {lead && <p className="header-subtitle">{lead}</p>}
        </div>
      </div>
      {children}
      {note && <p className="insight-note">{note}</p>}
    </section>
  );
}

export default function InsightsView({ insights }) {
  const [tab, setTab] = useState('magnitude');
  const [selectedProfile, setSelectedProfile] = useState(null);
  const [trendIds, setTrendIds] = useState(null);

  const cohort = insights?.cohort || {};
  const breadth = insights?.breadth || {};
  const mixed = insights?.mixed_outcomes || {};
  const causes = insights?.causes || {};
  const profiles = insights?.profiles || {};
  const trend = insights?.attempt_trend || [];

  // Default to the constraints with the largest movement across attempts; the
  // export is already sorted that way.
  const activeTrendIds = useMemo(() => {
    if (trendIds) return trendIds;
    return trend.slice(0, 4).map((s) => s.constraint_id);
  }, [trendIds, trend]);

  const trendSeries = useMemo(
    () => trend.filter((s) => activeTrendIds.includes(s.constraint_id)),
    [trend, activeTrendIds]
  );

  const toggleTrend = (cid) => {
    const next = activeTrendIds.includes(cid)
      ? activeTrendIds.filter((id) => id !== cid)
      : [...activeTrendIds, cid].slice(-MAX_TREND_SERIES);
    setTrendIds(next);
  };

  const profileDetail = useMemo(() => {
    if (!selectedProfile) return null;
    const row = (profiles.top || []).find((r) => r.profile === selectedProfile);
    if (!row) return null;
    const all = insights?.coviolation?.ids || [];
    return {
      ...row,
      omitted: all.filter((cid) => !row.members.includes(cid)),
    };
  }, [selectedProfile, profiles, insights]);

  if (!insights) {
    return <p className="summary-empty">No insight data available.</p>;
  }

  const constraintLabel = (cid) =>
    insights.constraint_labels?.[cid] || cid;

  return (
    <div className="section-page insights-view">
      <div className="section-kpi-grid">
        <Kpi label="Events" value={count(cohort.n_events)}
             sub={`${count(cohort.n_stays)} stays · ${count(cohort.n_patients)} patients`} />
        <Kpi label="Distinct activities" value={count(cohort.n_distinct_activities)}
             sub={`${cohort.n_model_activities} used by the model · ${cohort.n_source_tables} source tables`} />
        <Kpi label="Model-relevant events" value={pct(cohort.model_activity_share, 1)}
             sub={`${count(cohort.n_model_activity_events)} of all events`} />
        <Kpi label="Episodes" value={count(cohort.n_episodes)}
             sub={`${count(cohort.n_episodes_evaluable)} with an evaluable outcome`} />
        <Kpi label="SBT failure rate" value={pct(cohort.failure_rate_evaluable)}
             sub="among evaluable episodes" />
        <Kpi label="Median violations / episode" value={cohort.median_mandatory_violations}
             sub={`mean ${Number(cohort.mean_mandatory_violations || 0).toFixed(2)} mandatory constraints`} />
      </div>

      <div className="insight-tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab"
                  aria-selected={tab === t.id}
                  className={`insight-tab${tab === t.id ? ' active' : ''}`}
                  onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'magnitude' && (
        <>
          <Card
            title="How much does breadth of deviation matter?"
            lead="SBT success rate by the number of readiness criteria left unmet at trial start. Whiskers are the 95% CI of the risk ratio against the no-violation arm, rescaled to the plotted rate."
            note={
              `Each arm is an independent group of episodes, not a cumulative count. ` +
              `The all-${breadth.arms?.length ? breadth.arms[breadth.arms.length - 1].n_violated : 6} arm ` +
              `sits above the arms below it: violating every criterion at once is the signature of a thinly charted ` +
              `episode rather than a sicker patient — see the Data quality tab. ` +
              `RC-DP-06 is excluded throughout (violated in nearly every activation, so it carries no information).`
            }
          >
            <DoseResponseChart breadth={breadth} />
          </Card>

          <Card
            title="Which single criterion carries the signal?"
            lead={`Episodes that violated exactly one criterion (${pct(profiles.share_single_criterion)} of episodes), against the ${pct(breadth.reference_success_rate)} reference rate. The dashed marker on each bar is that reference.`}
          >
            <SoleCriterionList breadth={breadth} />
          </Card>

          <Card
            title="Why a per-stay verdict cannot hold"
            lead="Stays containing both a failed and a successful breathing trial. A single outcome label per stay is necessarily wrong for part of such a stay."
            note={
              `Collapsing each mixed stay to its majority outcome — the best case for a per-stay label — still ` +
              `mislabels ${count(mixed.n_episodes_mislabelled_by_majority_collapse)} episodes, ` +
              `${pct(mixed.share_all_evaluable_episodes_mislabelled)} of all evaluable episodes in the cohort.`
            }
          >
            <div className="insight-inline-kpis">
              <div className="insight-inline-kpi">
                <span className="insight-inline-value">{pct(mixed.mixed_share_of_two_or_more_evaluable)}</span>
                <span className="insight-inline-label">
                  of stays with ≥2 evaluable trials are mixed
                  <br />({count(mixed.n_mixed_outcome_stays)} of {count(mixed.n_stays_with_two_or_more_evaluable)})
                </span>
              </div>
              <div className="insight-inline-kpi">
                <span className="insight-inline-value">{pct(mixed.mixed_share_of_all_stays)}</span>
                <span className="insight-inline-label">of the whole cohort</span>
              </div>
              <div className="insight-inline-kpi">
                <span className="insight-inline-value">{pct(mixed.share_all_evaluable_episodes_mislabelled)}</span>
                <span className="insight-inline-label">of evaluable episodes mislabelled at best case</span>
              </div>
            </div>
            <MixedOutcomeBars mixed={mixed} />
          </Card>
        </>
      )}

      {tab === 'breadth' && (
        <>
          <Card
            title="Deviation profiles"
            lead={`${count(profiles.n_distinct)} distinct combinations of readiness criteria are violated across the cohort. The most frequent one accounts for only ${pct(profiles.top_profile_share)} of episodes — the deviation space is wide, not dominated by one pattern.`}
            note="Click a profile to see which criteria it leaves satisfied."
          >
            <ProfileBars profiles={profiles}
                         selectedProfile={selectedProfile}
                         onSelectProfile={setSelectedProfile} />
            {profileDetail && (
              <div className="insight-detail">
                <h4>{profileDetail.profile}</h4>
                <p className="insight-row-meta">
                  {count(profileDetail.n_episodes)} episodes · {pct(profileDetail.share)} of episodes
                </p>
                <p className="insight-detail-head">Violated</p>
                <ul className="insight-detail-list bad">
                  {profileDetail.members.map((cid) => (
                    <li key={cid}><strong>{cid}</strong> {constraintLabel(cid)}</li>
                  ))}
                </ul>
                {profileDetail.omitted.length > 0 && (
                  <>
                    <p className="insight-detail-head">Satisfied</p>
                    <ul className="insight-detail-list good">
                      {profileDetail.omitted.map((cid) => (
                        <li key={cid}><strong>{cid}</strong> {constraintLabel(cid)}</li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}
          </Card>

          <Card
            title="Criteria are not violated independently"
            lead="P(column criterion violated | row criterion violated). Read along a row: given that this criterion was violated, how often was each other one violated too."
            note={
              `The matrix is asymmetric because base rates differ by an order of magnitude. ` +
              `High off-diagonal cells mean violations arrive in bundles, which is why the weighted score ` +
              `cannot treat them as additive. ` +
              `Mean criteria violated per episode: ${Number(breadth.mean_criteria_violated || 0).toFixed(2)} of ` +
              `${insights.coviolation?.ids?.length || 0}.`
            }
          >
            <CoViolationHeatmap coviolation={insights.coviolation} />
          </Card>
        </>
      )}

      {tab === 'quality' && (
        <>
          <Card
            title="Documentation gap or care deviation?"
            lead="A readiness criterion is violated either because no usable reading was charted, or because a reading was charted and the threshold was not met. Only the second is a deviation in care."
            note={
              `Across ${count(causes.n_violated)} readiness violations in ${count(causes.n_activations)} activations, ` +
              `${pct(causes.share_documentation)} trace to a missing, stale or incomplete reading and ` +
              `${pct(causes.share_care)} to a criterion that was measured and genuinely unmet. ` +
              `High violation rates in the Frequencies view are therefore mostly a statement about charting coverage.`
            }
          >
            <div className="insight-inline-kpis">
              <div className="insight-inline-kpi">
                <span className="insight-inline-value">{pct(causes.share_documentation)}</span>
                <span className="insight-inline-label">documentation gap</span>
              </div>
              <div className="insight-inline-kpi">
                <span className="insight-inline-value">{pct(causes.share_care)}</span>
                <span className="insight-inline-label">criterion measured and unmet</span>
              </div>
            </div>
            <CauseStackedBars causes={causes} />
          </Card>

          <Card
            title="Vacuity by model group"
            lead="A constraint that never activates cannot be violated. Share of episode-constraint pairs that were vacuous, per model group."
          >
            <div className="summary-table-wrapper">
              <table className="summary-table">
                <thead>
                  <tr>
                    <th>Model group</th>
                    <th>Constraints</th>
                    <th>Vacuity rate</th>
                    <th>Violation rate among activations</th>
                  </tr>
                </thead>
                <tbody>
                  {(insights.vacuity_by_group || []).map((row) => (
                    <tr key={row.model_group}>
                      <td>{row.model_group}</td>
                      <td>{row.n_constraints}</td>
                      <td>{pct(row.vacuity_rate)}</td>
                      <td>{pct(row.violation_rate_activated)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      {tab === 'overtime' && (
        <Card
          title="Violation rate by weaning attempt"
          lead="Where in a stay each obligation goes unmet. Later attempts select for patients who are harder to liberate, so a flat line and a falling line say different things about the same rule."
          note={`Buckets beyond the last shown are pooled. Pick up to ${MAX_TREND_SERIES} constraints; they are offered in order of how much their rate moves from the first to the last bucket.`}
        >
          <div className="insight-picker">
            {trend.map((s) => (
              <button key={s.constraint_id} type="button"
                      className={`insight-pick${activeTrendIds.includes(s.constraint_id) ? ' active' : ''}`}
                      title={`${s.label}\nΔ first→last ${(s.delta_first_to_last * 100).toFixed(1)} pp · ${count(s.n_activated_total)} activations`}
                      onClick={() => toggleTrend(s.constraint_id)}>
                {s.constraint_id}
                <span className="insight-pick-delta">
                  {s.delta_first_to_last >= 0 ? '+' : ''}{(s.delta_first_to_last * 100).toFixed(0)}pp
                </span>
              </button>
            ))}
          </div>
          <AttemptTrendChart series={trendSeries} />
          <div className="summary-table-wrapper">
            <table className="summary-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Clinical rule</th>
                  <th>Activations</th>
                  <th>Δ first → last</th>
                </tr>
              </thead>
              <tbody>
                {trendSeries.map((s) => (
                  <tr key={s.constraint_id}>
                    <td>{s.constraint_id}</td>
                    <td>{s.label}</td>
                    <td>{count(s.n_activated_total)}</td>
                    <td>
                      {s.delta_first_to_last >= 0 ? '+' : ''}
                      {(s.delta_first_to_last * 100).toFixed(1)} pp
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <p className="insight-footer">
        Generated {insights.generated_at} by <code>case_study/10_frontend_insights.py</code> from the
        tables in <code>case_study/out/</code>.
      </p>
    </div>
  );
}
