import React, { useState } from 'react';
import { count, formatP } from '../InsightsView/charts';
import {
  ARMS, RiskRatioForest, SplitRiskRatioForest, orderSplitRows,
} from '../InsightsView/storyCharts';
import { InfoTip, More } from './MorePanels';

// Chapter 5: outcome association as a forest (RR or OR), with the full
// per-rule table underneath (replaces the old Statistics page). Readiness
// rules are split into "assessed, not met" and "documentation gap", as in
// Chapter 4; the other rules have no data condition and keep one estimate.

const ci = (v, lo, hi) => (v === null || v === undefined
  ? '–'
  : `${v.toFixed(2)} [${(lo ?? 0).toFixed(2)}, ${(hi ?? 0).toFixed(2)}]`);

function AssociationTable({ rows }) {
  return (
    <div className="summary-table-wrapper">
      <table className="summary-table assoc-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Rule</th>
            <th>Violation</th>
            <th>Outcome</th>
            <th title="violated & success / violated & failure / satisfied & success / satisfied & failure">
              2×2 (a / b / c / d)
            </th>
            <th>RR [95% CI]</th>
            <th title="Readiness rules: all violations pooled, before the split">RR pooled</th>
            <th>OR [95% CI]</th>
            <th>p</th>
            <th>p (Bonferroni)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.constraint_id}-${r.arm}`} className={r.significant_bonferroni ? 'sig' : 'ns'}>
              <td><strong>{r.constraint_id}</strong></td>
              <td>{r.label}</td>
              <td>{ARMS[r.arm]?.name ?? r.arm}</td>
              <td>{r.reference === 'next' ? 'next episode' : 'same episode'}</td>
              <td className="num">
                {count(r.a_violated_success)} / {count(r.b_violated_failure)} /{' '}
                {count(r.c_satisfied_success)} / {count(r.d_satisfied_failure)}
              </td>
              <td className="num">
                {r.degenerate_estimate ? <span title="degenerate estimate">n/a*</span> : ci(r.rr, r.rr_ci_low, r.rr_ci_high)}
              </td>
              <td className="num">
                {r.pooled_rr ? ci(r.pooled_rr, r.pooled_rr_ci_low, r.pooled_rr_ci_high) : '–'}
              </td>
              <td className="num">
                {r.degenerate_estimate ? 'n/a*' : ci(r.or, r.or_ci_low, r.or_ci_high)}
              </td>
              <td className="num">{formatP(r.p_raw)}</td>
              <td className="num">
                {formatP(r.p_bonferroni)}
                {r.significant_bonferroni && <span className="insight-chip bad assoc-sig">sig.</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function OutcomeChapter({ insights, hiddenIds }) {
  const [measure, setMeasure] = useState('rr');
  const split = insights.association_split;
  const groups = insights.constraint_groups;
  const source = split || insights.association || [];
  const rows = split ? orderSplitRows(split, groups) : source.slice().sort((a, b) => a.rr - b.rr);
  const degenerate = [...new Set(source.filter((r) => r.degenerate_estimate).map((r) => r.constraint_id))];
  const notShown = [...new Set([...hiddenIds, ...degenerate])].join(', ');

  return (
    <>
      <section className="summary-card story-panel">
        <div className="assoc-head">
          <h3>
            Outcome association per rule
            <InfoTip text={
              `${measure === 'rr' ? 'Risk ratio' : 'Odds ratio'} of SBT success, violated vs satisfied, activations only; ` +
              `Fisher test, Bonferroni over ${rows[0]?.n_tests ?? 21} tests. ` +
              (split
                ? 'Readiness violations are split by cause: red = criterion assessed and not met, ' +
                  'blue = documentation gap (not charted in the window, or charted without the value). ' +
                  'Both arms are compared with the same satisfied episodes; purple = all violations pooled, the estimate before the split. ' +
                  'The other rules have no data condition on their target, so a violation means the action is missing — ' +
                  'there is no documentation split to make. '
                : '') +
              `Diamonds: next-episode outcome. ${notShown} not shown (degenerate estimate). ` +
              'Observational — associations, not effects.' +
              (measure === 'or' ? ' The OR lies further from 1 than the RR because SBT success is a common outcome.' : '')
            } />
          </h3>
          <div className="assoc-toggle" role="tablist" aria-label="Effect measure">
            {[['rr', 'Risk ratio'], ['or', 'Odds ratio']].map(([k, label]) => (
              <button key={k} type="button" role="tab" aria-selected={measure === k}
                      className={`story-toggle${measure === k ? ' on' : ''}`}
                      onClick={() => setMeasure(k)}>
                {label}
              </button>
            ))}
          </div>
        </div>
        {split
          ? <SplitRiskRatioForest rows={split} groups={groups} hideIds={hiddenIds} measure={measure} />
          : <RiskRatioForest association={insights.association} hideIds={hiddenIds} measure={measure} />}
      </section>
      <More title="Table: 2×2 counts, RR, OR and p-values per rule">
        <AssociationTable rows={rows} />
        <p className="freq-note">
          a = violated & success, b = violated & failure, c = satisfied & success, d = satisfied & failure.
          * {degenerate.join(', ')}: degenerate estimate (violation is defined by a successful late trial).
        </p>
      </More>
    </>
  );
}
