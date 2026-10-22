import React, { useMemo, useState } from 'react';
import {
  AttemptTrendChart,
  CoViolationHeatmap,
  ProfileBars,
  SoleCriterionList,
  count,
  pct,
} from '../InsightsView/charts';

// Supporting analyses folded into the story chapters (formerly the Insights
// page). Collapsed by default so the chapter flow stays short.

// Explanations stay one hover away so the slides-like chapters stay uncluttered.
export function InfoTip({ text }) {
  if (!text) return null;
  return <span className="story-info" title={text} aria-label={text} tabIndex={0}>ⓘ</span>;
}

export function More({ title, lead, note, children }) {
  return (
    <details className="summary-card story-more">
      <summary>{title}</summary>
      <div className="story-more-body">
        {lead && <p className="header-subtitle">{lead}</p>}
        {children}
        {note && <p className="insight-note">{note}</p>}
      </div>
    </details>
  );
}

export function VacuityPanel({ insights }) {
  return (
    <More title="Vacuity by model group"
          lead="A constraint that never activates cannot be violated. Share of episode-constraint pairs that were vacuous, per model group.">
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
    </More>
  );
}

export function SoleCriterionPanel({ insights }) {
  const breadth = insights.breadth || {};
  const profiles = insights.profiles || {};
  return (
    <More title="Which single criterion carries the signal?"
          lead={`Episodes that violated exactly one criterion (${pct(profiles.share_single_criterion)} of episodes), against the ${pct(breadth.reference_success_rate)} reference rate. The dashed marker on each bar is that reference.`}>
      <SoleCriterionList breadth={breadth} />
    </More>
  );
}

export function ProfilesPanel({ insights }) {
  const [selectedProfile, setSelectedProfile] = useState(null);
  const profiles = insights.profiles || {};
  const constraintLabel = (cid) => insights.constraint_labels?.[cid] || cid;

  const profileDetail = useMemo(() => {
    if (!selectedProfile) return null;
    const row = (profiles.top || []).find((r) => r.profile === selectedProfile);
    if (!row) return null;
    const all = insights?.coviolation?.ids || [];
    return { ...row, omitted: all.filter((cid) => !row.members.includes(cid)) };
  }, [selectedProfile, profiles, insights]);

  return (
    <More title="Deviation profiles"
          lead={`${count(profiles.n_distinct)} distinct combinations of readiness criteria are violated across the cohort. The most frequent one accounts for only ${pct(profiles.top_profile_share)} of episodes — the deviation space is wide, not dominated by one pattern.`}
          note="Click a profile to see which criteria it leaves satisfied.">
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
    </More>
  );
}

export function CoViolationPanel({ insights }) {
  const breadth = insights.breadth || {};
  return (
    <More title="Criteria are not violated independently"
          lead="P(column criterion violated | row criterion violated). Read along a row: given that this criterion was violated, how often was each other one violated too."
          note={
            `The matrix is asymmetric because base rates differ by an order of magnitude. ` +
            `Mean criteria violated per episode: ${Number(breadth.mean_criteria_violated || 0).toFixed(2)} of ` +
            `${insights.coviolation?.ids?.length || 0}.`
          }>
      <CoViolationHeatmap coviolation={insights.coviolation} />
    </More>
  );
}

const MAX_TREND_SERIES = 6;

export function AttemptTrendPanel({ insights }) {
  const trend = insights.attempt_trend || [];
  const [trendIds, setTrendIds] = useState(null);

  // Default to the constraints with the largest movement across attempts; the
  // export is already sorted that way.
  const activeTrendIds = useMemo(
    () => trendIds || trend.slice(0, 4).map((s) => s.constraint_id),
    [trendIds, trend]
  );
  const trendSeries = useMemo(
    () => trend.filter((s) => activeTrendIds.includes(s.constraint_id)),
    [trend, activeTrendIds]
  );
  const toggleTrend = (cid) => {
    setTrendIds(activeTrendIds.includes(cid)
      ? activeTrendIds.filter((id) => id !== cid)
      : [...activeTrendIds, cid].slice(-MAX_TREND_SERIES));
  };

  return (
    <More title="Violation rate by weaning attempt"
          lead="Where in a stay each obligation goes unmet. Later attempts select for patients who are harder to liberate, so a flat line and a falling line say different things about the same rule."
          note={`Buckets beyond the last shown are pooled. Pick up to ${MAX_TREND_SERIES} constraints; they are offered in order of how much their rate moves from the first to the last bucket.`}>
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
    </More>
  );
}
