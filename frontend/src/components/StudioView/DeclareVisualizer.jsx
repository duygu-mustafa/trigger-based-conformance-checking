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
import { UilArrowCircleRight, UilArrowCircleLeft, UilBan } from '@iconscout/react-unicons'

export default function DeclareVisualizer({ template, activation, target, conditionLabel, activationTitle, correlationConditionLabel, timeCondition, compact = false }) {
  const showActivationLabel = Boolean(activationTitle) && template !== 'EXISTENCE'
  const labelRowH = compact ? 13 : 16
  const W = compact ? 200 : 320
  const baseH = compact ? 72 : 108
  const hasExpandedLabels = !compact && (showActivationLabel || Boolean(correlationConditionLabel))
  const H = baseH + (hasExpandedLabels ? labelRowH : 0)
  const BOX_W = compact ? 78 : 112
  const BOX_H = compact ? 26 : 44
  const FONT = compact ? 9 : 11
  const BADGE_R = compact ? 10 : 13

  const isUnary = ['EXISTENCE', 'ABSENCE', 'EXACTLY', 'INIT', 'END'].includes(template)
  const isNegative = template.startsWith('NOT_') || template === 'ABSENCE'
  const isChain = template.startsWith('CHAIN_')
  const isAlternate = template.startsWith('ALTERNATE_')
  const isSymmetricProhibition =
    template === 'NOT_CO_EXISTENCE' ||
    template === 'NOT_SUCCESSION' ||
    template === 'NOT_CHAIN_SUCCESSION'
  const isPrecedence =
    template === 'PRECEDENCE' ||
    template === 'CHAIN_PRECEDENCE' ||
    template === 'ALTERNATE_PRECEDENCE'
  const isRespondedExistence =
    template === 'RESPONDED_EXISTENCE' ||
    template === 'NOT_RESPONDED_EXISTENCE'

  // When an EXISTENCE rule has an activation title (e.g. "Temperature criterion met"),
  // show a two-box diagram: [condition title] ──→ [activation activity]
  const showConditionAsBox = Boolean(activationTitle) && template === 'EXISTENCE'
  const effectiveIsUnary = isUnary && !showConditionAsBox

  // Dashed border follows the *semantic* target box (PRECEDENCE swaps left/right)
  const leftIsDashed = isPrecedence && !showConditionAsBox
  const rightIsDashed = !effectiveIsUnary && !isPrecedence && !showConditionAsBox

  const cx = W / 2
  const cy = baseH / 2

  // For unary: single centred box
  // For binary: two boxes left and right with arrow between
  const leftX = effectiveIsUnary ? cx - BOX_W / 2 : compact ? 2 : 4
  const rightX = effectiveIsUnary ? cx - BOX_W / 2 : W - BOX_W - (compact ? 2 : 4)
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

  function binaryBadgeText() {
    if (isSymmetricProhibition) return '✕'
    if (isNegative) return '⊘'
    if (template.includes('SUCCESSION')) return '⇆'
    if (template.includes('RESPONSE')) return '→'
    if (isPrecedence) return '←'
    if (template === 'CO_EXISTENCE') return '↔'
    if (isRespondedExistence) return '∃'
    return '?'
  }

  function renderBadgeIcon() {
    const iconSize = BADGE_R * 2
    if (isNegative || template === 'ABSENCE')
      return <UilBan size={iconSize} color="var(--color-violation, #e05252)" />
    if (isPrecedence)
      return <UilArrowCircleLeft size={iconSize} color="var(--color-primary, #5b8dee)" />
    return <UilArrowCircleRight size={iconSize} color="var(--color-primary, #5b8dee)" />
  }

  // ── Text helpers ──────────────────────────────────────────────────────────
  function trimLabel(str, maxLen = 14) {
    if (!str) return ''
    return str.length > maxLen ? str.slice(0, maxLen - 1) + '…' : str
  }

  // In expanded mode: show full text with word wrap when needed.
  // In compact mode: truncate with ellipsis.
  const CHARS_PER_LINE = Math.floor((BOX_W - 14) / (FONT * 0.6))

  function wrapText(text) {
    if (!text) return ['']
    const lines = []
    for (let i = 0; i < text.length; i += CHARS_PER_LINE) {
      lines.push(text.slice(i, i + CHARS_PER_LINE))
    }
    return lines
  }

  function renderLabel(text, x) {
    const isCompact = compact
    const displayText = isCompact ? trimLabel(text) : text
    const lines = isCompact ? [displayText] : wrapText(text)
    const lineH = FONT + 2
    const isMulti = lines.length > 1

    return (
      <text
        x={x} y={boxY + BOX_H / 2 + 1}
        textAnchor="middle" dominantBaseline="middle"
        fontSize={FONT}
        fill="var(--color-text-main, #e8edf5)"
        fontFamily="Inter, sans-serif"
      >
        {lines.map((line, i) => (
          <tspan
            key={i} x={x}
            dy={i === 0 && isMulti ? -(lines.length - 1) * lineH / 2 : (i > 0 ? lineH : 0)}
          >
            {line}
          </tspan>
        ))}
      </text>
    )
  }

  function formatTimeLabel(tc) {
    if (!tc) return null
    const { min_hours, max_hours } = tc
    // negative min with max≤0: "within the last N hours before activation"
    if (min_hours != null && min_hours < 0 && (max_hours == null || max_hours <= 0)) {
      return `≤ ${Math.abs(min_hours)}h`
    }
    if (min_hours != null && max_hours != null && min_hours >= 0) return `${min_hours}–${max_hours}h`
    if (max_hours != null) return `≤ ${max_hours}h`
    if (min_hours != null && min_hours >= 0) return `≥ ${min_hours}h`
    return null
  }
  const timeLabel = !compact && !effectiveIsUnary ? formatTimeLabel(timeCondition) : null

  // When target duplicates activation AND a condition label is supplied,
  // show the condition name on the right box instead of the duplicated activity.
  const showConditionOnRight = Boolean(conditionLabel) && target === activation

  // Use raw strings — renderLabel handles truncation (compact) and wrapping (expanded).
  const rawLeft  = showConditionAsBox ? activationTitle
                 : isPrecedence       ? (target || 'B')
                 :                      (activation || 'A')
  const rawRight = showConditionAsBox   ? activation
                 : isPrecedence         ? (activation || 'A')
                 : showConditionOnRight  ? conditionLabel
                 :                        (target || 'B')

  function renderConnector() {
    const TS = compact ? 3.5 : 5

    const doubleTick = (offsetX = 0) => (
      <path
        d={`M${midX - 2 + offsetX},${arrowY - TS} L${midX - 2 + offsetX},${arrowY + TS} M${midX + 2 + offsetX},${arrowY - TS} L${midX + 2 + offsetX},${arrowY + TS}`}
        stroke={arrowColor} strokeWidth="1.5"
      />
    )

    const altArc = () => {
      const ax = compact ? 4 : 6
      const ay1 = compact ? 6 : 8
      const ay2 = compact ? 11 : 16
      return (
        <path
          d={`M${midX - ax},${arrowY - ay1} Q${midX},${arrowY - ay2} ${midX + ax},${arrowY - ay1}`}
          stroke={arrowColor} strokeWidth="1.2" fill="none"
        />
      )
    }

    // Symmetric prohibition: no direction arrow, filled ✕ circle on dashed line
    if (isSymmetricProhibition) {
      const tickOffset = BADGE_R + 6
      return (
        <g>
          <line
            x1={arrowX1} y1={arrowY} x2={arrowX2} y2={arrowY}
            stroke={arrowColor} strokeWidth="1.5" strokeDasharray="5,3" opacity="0.7"
          />
          {template === 'NOT_CHAIN_SUCCESSION' && doubleTick(tickOffset)}
        </g>
      )
    }

    // Responded existence: dashed line, no arrowhead (badge carries the symbol)
    if (isRespondedExistence) {
      return (
        <g>
          <line
            x1={arrowX1} y1={arrowY} x2={arrowX2} y2={arrowY}
            stroke={arrowColor} strokeWidth="1.5" strokeDasharray="5,3" opacity="0.7"
          />
        </g>
      )
    }

    // Precedence: boxes are swapped to [target]→[activation], so arrow points left-to-right
    if (isPrecedence) {
      return (
        <g>
          <line
            x1={arrowX1} y1={arrowY} x2={arrowX2 - 2} y2={arrowY}
            stroke={arrowColor} strokeWidth="1.5"
            markerEnd={`url(#arrow-${template}-pos)`}
          />
          {isChain && doubleTick()}
          {isAlternate && altArc()}
        </g>
      )
    }

    // Bidirectional: CO_EXISTENCE and SUCCESSION family (non-prohibited)
    if (template === 'CO_EXISTENCE' || (template.includes('SUCCESSION') && !isSymmetricProhibition)) {
      return (
        <g>
          <line
            x1={arrowX1} y1={arrowY - 3} x2={arrowX2} y2={arrowY - 3}
            stroke={arrowColor} strokeWidth="1.5"
            markerEnd={`url(#arrow-${template}-pos)`}
          />
          <line
            x1={arrowX2} y1={arrowY + 3} x2={arrowX1} y2={arrowY + 3}
            stroke={arrowColor} strokeWidth="1.5"
            markerEnd={`url(#arrow-${template}-neg)`}
          />
          {isChain && doubleTick()}
          {isAlternate && altArc()}
        </g>
      )
    }

    // Other negatives: dashed arrow with open strike-through circle
    if (isNegative) {
      return (
        <g>
          <line
            x1={arrowX1} y1={arrowY} x2={arrowX2} y2={arrowY}
            stroke={arrowColor} strokeWidth="1.5" strokeDasharray="5,3"
            markerEnd={`url(#arrow-${template}-neg)`} opacity="0.7"
          />
          <circle cx={midX} cy={arrowY} r={BADGE_R - 2} fill="none" stroke={arrowColor} strokeWidth="1.5" opacity="0.8" />
          <line
            x1={midX - (BADGE_R - 4)} y1={arrowY - (BADGE_R - 4)}
            x2={midX + (BADGE_R - 4)} y2={arrowY + (BADGE_R - 4)}
            stroke={arrowColor} strokeWidth="1.5" opacity="0.8"
          />
          {isChain && doubleTick()}
        </g>
      )
    }

    // Default positive directional (RESPONSE, CHAIN_RESPONSE, ALTERNATE_RESPONSE)
    return (
      <g>
        <line
          x1={arrowX1} y1={arrowY} x2={arrowX2 - 2} y2={arrowY}
          stroke={arrowColor} strokeWidth="1.5"
          markerEnd={`url(#arrow-${template}-pos)`}
        />
        {isChain && doubleTick()}
        {isAlternate && altArc()}
      </g>
    )
  }

  const overlayStyle = {
    position: 'absolute',
    pointerEvents: 'none',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  }

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
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
          strokeDasharray={leftIsDashed ? '6,3' : 'none'}
        />
        {renderLabel(rawLeft, leftX + BOX_W / 2)}

        {/* Right activity box (binary only) */}
        {!effectiveIsUnary && (
          <>
            <rect
              x={rightX} y={boxY}
              width={BOX_W} height={BOX_H}
              rx="5"
              fill="var(--color-bg-card, #1e2a3a)"
              stroke={isNegative ? arrowColor : 'var(--color-primary, #5b8dee)'}
              strokeWidth="1.5"
              strokeDasharray={rightIsDashed ? '6,3' : 'none'}
            />
            {renderLabel(rawRight, rightX + BOX_W / 2)}

            {/* Arrow / connector */}
            {renderConnector()}
          </>
        )}

        {/* Badge circle with template symbol (unary non-ABSENCE stay as text) */}
        {effectiveIsUnary && template !== 'ABSENCE' && (
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
        )}

        {/* Compact mode: indicator dots for data conditions */}
        {compact && showActivationLabel && (
          <circle
            cx={(isPrecedence ? rightX : leftX) + BOX_W / 2}
            cy={boxY + BOX_H - 4}
            r={3}
            fill="var(--color-primary, #5b8dee)"
            opacity="0.8"
          />
        )}
        {compact && Boolean(correlationConditionLabel) && !effectiveIsUnary && !showConditionAsBox && (
          <circle
            cx={(isPrecedence ? leftX : rightX) + BOX_W / 2}
            cy={boxY + BOX_H - 4}
            r={3}
            fill="var(--color-primary, #5b8dee)"
            opacity="0.8"
          />
        )}

        {/* Expanded mode: condition labels below their respective boxes */}
        {!compact && showActivationLabel && (
          <text
            x={(isPrecedence ? rightX : leftX) + BOX_W / 2}
            y={boxY + BOX_H + 12}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={9}
            fontWeight="600"
            fill="var(--color-text-dim, #7a8aa0)"
            fontFamily="Inter, sans-serif"
            letterSpacing="0.01em"
          >
            {trimLabel(activationTitle, 22)}
          </text>
        )}
        {!compact && Boolean(correlationConditionLabel) && !effectiveIsUnary && !showConditionAsBox && (
          <text
            x={(isPrecedence ? leftX : rightX) + BOX_W / 2}
            y={boxY + BOX_H + 12}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={9}
            fontWeight="600"
            fill="var(--color-text-dim, #7a8aa0)"
            fontFamily="Inter, sans-serif"
            letterSpacing="0.01em"
          >
            {trimLabel(correlationConditionLabel, 22)}
          </text>
        )}

        {/* Clock + time label on arc (expanded binary rules with time condition) */}
        {timeLabel && (
          <g
            transform={`translate(${midX}, ${arrowY + 14})`}
            fill="none"
            stroke="var(--color-text-dim, #7a8aa0)"
          >
            <circle cx="-15" cy="0" r="4.5" strokeWidth="1.2" />
            <line x1="-15" y1="-2.5" x2="-15" y2="0" strokeWidth="1.1" strokeLinecap="round" />
            <line x1="-15" y1="0" x2="-12.5" y2="1.5" strokeWidth="1" strokeLinecap="round" />
            <text
              x="-7" y="0"
              textAnchor="start" dominantBaseline="middle"
              fontSize={9} fontFamily="Inter, sans-serif" fontWeight="500"
              fill="var(--color-text-dim, #7a8aa0)" stroke="none"
            >
              {timeLabel}
            </text>
          </g>
        )}

        {/* Template name label below */}
        {!compact && (
          <text
            x={cx} y={H - 4}
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

      {/* Unicon badge overlay: ABSENCE */}
      {effectiveIsUnary && template === 'ABSENCE' && (
        <div style={{ ...overlayStyle, left: badgeX - BADGE_R, top: badgeY - BADGE_R, width: BADGE_R * 2, height: BADGE_R * 2 }}>
          {renderBadgeIcon()}
        </div>
      )}

      {/* Unicon badge overlay: all binary templates */}
      {!effectiveIsUnary && (
        <div style={{ ...overlayStyle, left: midX - BADGE_R, top: badgeY - BADGE_R, width: BADGE_R * 2, height: BADGE_R * 2 }}>
          {renderBadgeIcon()}
        </div>
      )}
    </div>
  )
}
