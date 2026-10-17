// Per-dataset custom-rule storage key. Built-in keeps the legacy key so existing
// rules survive; uploads get a suffixed key so their rules stay scoped.
export function rulesKey(datasetId = 'builtin') {
  return datasetId === 'builtin' ? 'studio_custom_rules' : `studio_custom_rules_${datasetId}`
}

export function loadRules(datasetId) {
  try { return JSON.parse(localStorage.getItem(rulesKey(datasetId)) || '[]') }
  catch { return [] }
}
