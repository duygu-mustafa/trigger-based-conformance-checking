// Short rule names for chart labels, mirroring CONSTRAINT_NAME in
// case_study/config.py so the Studio matches the thesis figures.
export const RULE_NAMES = {
  'RC-DP-01': 'Oxygenation',
  'RC-DP-02': 'Arterial pH',
  'RC-DP-03': 'Hemoglobin',
  'RC-DP-04': 'Temperature',
  'RC-DP-05': 'Hemodynamics',
  'RC-DP-06': 'Mental status',
  'RC-DP-07': 'Inspiratory effort',
  'SBT-TM-01': 'Retry next day',
  'SBT-TM-01-early': 'No same-day retry',
  'SBT-TM-01-late': 'Retry by next day',
  'SBT-TM-02': 'Early weaning',
  'INT-TR-01': 'Bronchodilator',
  'INT-TR-02': 'Diuretic',
  'INT-TR-03': 'Afterload reduction',
  'INT-DX-04': 'Electrolyte/BG test',
  'INT-TR-04': 'Electrolyte correction',
  'INT-DX-05': 'Hormonal lab test',
  'INT-TR-05': 'Hormonal replacement',
  'INT-COMPOSITE-01': 'Any pathway',
  'INT-SEQ-01': 'Test before correction',
  'INT-SEQ-02': 'Test before replacement',
};

// 'Hemoglobin (RC-DP-03)', the label every per-rule axis uses; unknown ids
// (e.g. custom rules) fall back to the bare id.
export const ruleLabel = (cid) => (RULE_NAMES[cid] ? `${RULE_NAMES[cid]} (${cid})` : cid);
