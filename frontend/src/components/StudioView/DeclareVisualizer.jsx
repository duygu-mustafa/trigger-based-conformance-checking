/**
 * DeclareVisualizer — SVG diagrams for Declare constraint templates.
 *
 * Renders a compact, clinician-readable visual for any DeclareTemplate,
 * using the same SVG-native approach as the existing Timeline component.
 *
 * Props:
 *   template    string   — e.g. "RESPONSE", "NOT_CO_EXISTENCE"
 *   activation  string   — label for the activation activity box
 *   target      string   — label for the target activity box (binary rules)
 *   compact     bool     — if true, render a smaller thumbnail version
 */
export default function DeclareVisualizer({ template, activation, target, compact = false }) {
  const W = compact ? 200 : 320
  const H = compact ? 72 : 100
  const BOX_W = compact ? 68 : 100
  const BOX_H = compact ? 26 : 36
  const FONT = compact ? 9 : 11
  const BADGE_R = compact ? 10 : 13

  const isUnary = ['EXISTENCE', 'ABSENCE', 'EXACTLY', 'INIT', 'END'].includes(template)
  const isNegative = template.startsWith('NOT_') || template === 'ABSENCE'
  const isChain = template.startsWith('CHAIN_')

  const cx = W / 2
  const cy = H / 2

  // For unary: single centred box
  // For binary: two boxes left and right with arrow between
  const leftX = isUnary ? cx - BOX_W / 2 : compact ? 8 : 16
  const rightX = isUnary ? cx - BOX_W / 2 : W - BOX_W - (compact ? 8 : 16)
  const boxY = cy - BOX_H / 2

  const arrowColor = isNegative ? 'var(--color-violation, #e05252)' : 'var(--color-primary, #5b8dee)'
  const strokeDash = isNegative ? '5,3' : isChain ? 'none' : 'none'

  // Arrow path: from right edge of left box to left edge of right box
  const arrowX1 = leftX + BOX_W
  const arrowX2 = rightX
  const arrowY = cy
  const midX = (arrowX1 + arrowX2) / 2

  // Badge text and position (top-centre between boxes or over single box)
  const badgeX = isUnary ? cx : midX
  const badgeY = boxY - (compact ? 6 : 8)

  function badgeText() {
    switch (template) {
      case 'EXISTENCE': return '≥1'
      case 'ABSENCE': return '0'
      case 'EXACTLY': return '=N'
      case 'INIT': return 'first'
      case 'END': return 'last'
      case 'RESPONSE': return '→'
      case 'CHAIN_RESPONSE': return '→!'
      case 'ALTERNATE_RESPONSE': return '→*'
      case 'PRECEDENCE': return '←'
      case 'CHAIN_PRECEDENCE': return '!←'
      case 'ALTERNATE_PRECEDENCE': return '*←'
      case 'CO_EXISTENCE': return '↔'
      case 'RESPONDED_EXISTENCE': return '∃'
      case 'SUCCESSION': return '⇆'
      case 'ALTERNATE_SUCCESSION': return '⇆*'
      case 'CHAIN_SUCCESSION': return '⇆!'
      case 'NOT_CO_EXISTENCE': return '✕'
      case 'NOT_RESPONSE': return '⊘→'
      case 'NOT_CHAIN_RESPONSE': return '⊘→!'
      case 'NOT_PRECEDENCE': return '⊘←'
      case 'NOT_CHAIN_PRECEDENCE': return '⊘!←'
      case 'NOT_RESPONDED_EXISTENCE': return '¬∃'
      case 'NOT_SUCCESSION': return '⊘⇆'
      case 'NOT_CHAIN_SUCCESSION': return '⊘⇆!'
      default: return '?'
    }
  }

  // Activity display label: trim long names
  function trimLabel(str, maxLen = compact ? 10 : 14) {
    if (!str) return ''
    return str.length > maxLen ? str.slice(0, maxLen - 1) + '…' : str
  }

  const activationLabel = trimLabel(activation || 'A')
  const targetLabel = trimLabel(target || 'B')

  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      className="declare-visualizer"
      aria-label={`${template} rule diagram`}
    >
      <defs>
        <marker
          id={`arrow-${template}-pos`}
          markerWidth="8" markerHeight="8"
          refX="6" refY="3"
          orient="auto"
        >
          <path d="M0,0 L0,6 L8,3 z" fill={arrowColor} />
        </marker>
        <marker
          id={`arrow-${template}-neg`}
          markerWidth="8" markerHeight="8"
          refX="6" refY="3"
          orient="auto"
        >
          <path d="M0,0 L0,6 L8,3 z" fill={arrowColor} opacity="0.7" />
        </marker>
      </defs>

      {/* Left / single activity box */}
      <rect
        x={leftX} y={boxY}
        width={BOX_W} height={BOX_H}
        rx="5"
        fill="var(--color-bg-card, #1e2a3a)"
        stroke="var(--color-primary, #5b8dee)"
        strokeWidth="1.5"
      />
      <text
        x={leftX + BOX_W / 2}
        y={boxY + BOX_H / 2 + 1}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={FONT}
        fill="var(--color-text-main, #e8edf5)"
        fontFamily="Inter, sans-serif"
      >
        {activationLabel}
      </text>

      {/* Right activity box (binary only) */}
      {!isUnary && (
        <>
          <rect
            x={rightX} y={boxY}
            width={BOX_W} height={BOX_H}
            rx="5"
            fill="var(--color-bg-card, #1e2a3a)"
            stroke={isNegative ? arrowColor : 'var(--color-primary, #5b8dee)'}
            strokeWidth="1.5"
          />
          <text
            x={rightX + BOX_W / 2}
            y={boxY + BOX_H / 2 + 1}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={FONT}
            fill="var(--color-text-main, #e8edf5)"
            fontFamily="Inter, sans-serif"
          >
            {targetLabel}
          </text>

          {/* Arrow / connector */}
          {template === 'CO_EXISTENCE' || template === 'SUCCESSION' || template.includes('SUCCESSION') ? (
            /* Bidirectional */
            <>
              <line
                x1={arrowX1} y1={arrowY - 3}
                x2={arrowX2} y2={arrowY - 3}
                stroke={arrowColor} strokeWidth="1.5"
                markerEnd={`url(#arrow-${template}-pos)`}
              />
              <line
                x1={arrowX2} y1={arrowY + 3}
                x2={arrowX1} y2={arrowY + 3}
                stroke={arrowColor} strokeWidth="1.5"
                markerEnd={`url(#arrow-${template}-neg)`}
              />
            </>
          ) : isNegative ? (
            /* Negative: dashed red with strike */
            <g>
              <line
                x1={arrowX1} y1={arrowY}
                x2={arrowX2} y2={arrowY}
                stroke={arrowColor} strokeWidth="1.5"
                strokeDasharray={strokeDash || '5,3'}
                markerEnd={`url(#arrow-${template}-neg)`}
                opacity="0.7"
              />
              {/* Strike-through circle */}
              <circle cx={midX} cy={arrowY} r={BADGE_R - 2} fill="none" stroke={arrowColor} strokeWidth="1.5" opacity="0.8" />
              <line
                x1={midX - (BADGE_R - 4)} y1={arrowY - (BADGE_R - 4)}
                x2={midX + (BADGE_R - 4)} y2={arrowY + (BADGE_R - 4)}
                stroke={arrowColor} strokeWidth="1.5" opacity="0.8"
              />
            </g>
          ) : (
            /* Positive: solid arrow */
            <line
              x1={arrowX1} y1={arrowY}
              x2={arrowX2 - 2} y2={arrowY}
              stroke={arrowColor} strokeWidth="1.5"
              markerEnd={`url(#arrow-${template}-pos)`}
            />
          )}
        </>
      )}

      {/* Badge circle with template symbol */}
      {isUnary ? (
        <g>
          <circle
            cx={badgeX} cy={badgeY}
            r={BADGE_R}
            fill={isNegative ? arrowColor : 'var(--color-primary, #5b8dee)'}
            opacity="0.85"
          />
          <text
            x={badgeX} y={badgeY + 1}
            textAnchor="middle" dominantBaseline="middle"
            fontSize={FONT - 1} fontWeight="700"
            fill="#fff"
            fontFamily="Inter, sans-serif"
          >
            {badgeText()}
          </text>
        </g>
      ) : null}

      {/* Template name label below */}
      {!compact && (
        <text
          x={cx} y={H - 6}
          textAnchor="middle"
          fontSize={9}
          fill="var(--color-text-dim, #7a8aa0)"
          fontFamily="Inter, sans-serif"
          letterSpacing="0.03em"
        >
          {template.replace(/_/g, ' ')}
        </text>
      )}
    </svg>
  )
}
