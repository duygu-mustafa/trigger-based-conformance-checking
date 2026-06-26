/**
 * DeclareVisualizer — SVG diagrams for Declare constraint templates.
 *
 * Follows the canonical Declare graphical notation:
 *  - Unary: pill badge (INIT / END / 1..* / 0..1) + vertical stem + activity box
 *  - Binary: two activity boxes connected by 1–3 parallel lines with endpoint
 *    markers (filled dot, arrowhead, or dot+arrow) and an optional negation bar (||)
 *
 * Rendering spec per template (matches declare_notation_instructions.md):
 *   left/right marker: 'none' | 'dot' | 'arrow' | 'dot+arrow'
 *   lines: 1 (base) | 2 (alternate) | 3 (chain)
 *   neg: false | true  →  adds central || negation bar
 */

const GLYPH_MAP = {
  RESPONDED_EXISTENCE:     { left: 'dot',       right: 'none',      lines: 1, neg: false },
  RESPONSE:                { left: 'dot',       right: 'arrow',     lines: 1, neg: false },
  ALTERNATE_RESPONSE:      { left: 'dot',       right: 'arrow',     lines: 2, neg: false },
  CHAIN_RESPONSE:          { left: 'dot',       right: 'arrow',     lines: 3, neg: false },
  PRECEDENCE:              { left: '',     right: 'dot+arrow',       lines: 1, neg: false },
  ALTERNATE_PRECEDENCE:    { left: '',     right: 'dot+arrow',       lines: 2, neg: false },
  CHAIN_PRECEDENCE:        { left: '',     right: 'dot+arrow',       lines: 3, neg: false },
  CO_EXISTENCE:            { left: 'dot',       right: 'dot',       lines: 1, neg: false },
  SUCCESSION:              { left: 'dot', right: 'dot+arrow', lines: 1, neg: false },
  ALTERNATE_SUCCESSION:    { left: 'dot', right: 'dot+arrow', lines: 2, neg: false },
  CHAIN_SUCCESSION:        { left: 'dot', right: 'dot+arrow', lines: 3, neg: false },
  NOT_RESPONDED_EXISTENCE: { left: 'dot',       right: 'none',      lines: 1, neg: true  },
  NOT_RESPONSE:            { left: 'dot',       right: 'arrow',     lines: 1, neg: true  },
  NOT_PRECEDENCE:          { left: 'arrow',     right: 'dot',       lines: 1, neg: true  },
  NOT_CHAIN_RESPONSE:      { left: 'dot',       right: 'arrow',     lines: 3, neg: true  },
  NOT_CHAIN_PRECEDENCE:    { left: 'arrow',     right: 'dot',       lines: 3, neg: true  },
  NOT_CO_EXISTENCE:        { left: 'dot',       right: 'dot',       lines: 1, neg: true  },
  NOT_SUCCESSION:          { left: 'dot+arrow', right: 'dot+arrow', lines: 1, neg: true  },
  NOT_CHAIN_SUCCESSION:    { left: 'dot+arrow', right: 'dot+arrow', lines: 3, neg: true  },
}

const UNARY_BADGE_LABEL = {
  EXISTENCE: '1..*',
  ABSENCE:   '0',
  AT_MOST_ONE: '0..1',
  INIT:      'INIT',
  END:       'END',
}

const UNARY_TEMPLATES = new Set(['EXISTENCE', 'ABSENCE', 'AT_MOST_ONE', 'INIT', 'END'])

export default function DeclareVisualizer({
  template,
  activation,
  target,
  conditionLabel,
  activationTitle,
  correlationConditionLabel,
  timeCondition,
  compact = false,
}) {
  // ── Layout constants ──────────────────────────────────────────────────────
  const W       = compact ? 200 : 320
  const baseH   = compact ? 72  : 108
  const BOX_W   = compact ? 78  : 112
  const BOX_H   = compact ? 26  : 44
  const FONT    = compact ? 9   : 11

  // Endpoint marker sizes
  const DOT_R    = compact ? 4   : 6
  const ARROW_L  = compact ? 8   : 13    // arrowhead body length (horizontal)
  const ARROW_H  = compact ? 5   : 7.5  // arrowhead half-height
  const LINE_GAP = compact ? 3   : 4.5   // spacing between parallel lines
  const NEG_H    = compact ? 7   : 10    // half-height of negation bar strokes
  const NEG_GAP  = compact ? 2   : 3     // half-gap between the two bar strokes

  // Unary badge (pill shape above activity box)
  const BADGE_H  = compact ? 14 : 18
  const BADGE_W  = compact ? 34 : 44
  const STEM_H   = compact ? 5  : 7

  // ── Derived flags ─────────────────────────────────────────────────────────
  const isUnary = UNARY_TEMPLATES.has(template)

  // Special case: EXISTENCE with an activationTitle renders as a 2-box diagram
  // showing [condition title] → [activation activity].
  const showConditionAsBox = Boolean(activationTitle) && template === 'EXISTENCE'
  const effectiveIsUnary   = isUnary && !showConditionAsBox

  const isPrecedence =
    template === 'PRECEDENCE' ||
    template === 'CHAIN_PRECEDENCE' ||
    template === 'ALTERNATE_PRECEDENCE'

  const showActivationLabel   = Boolean(activationTitle) && !isUnary
  const labelRowH             = compact ? 13 : 16
  const hasExpandedLabels     = !compact && (showActivationLabel || Boolean(correlationConditionLabel))
  const H                     = baseH + (hasExpandedLabels ? labelRowH : 0)

  // ── Geometry ──────────────────────────────────────────────────────────────
  const cx   = W / 2
  const cy   = baseH / 2
  const pad  = compact ? 2 : 4
  const leftX  = effectiveIsUnary ? cx - BOX_W / 2 : pad
  const rightX = W - BOX_W - pad
  const boxY   = cy - BOX_H / 2

  // Connector span: from right edge of left box to left edge of right box
  const arrowX1 = leftX + BOX_W
  const arrowX2 = rightX
  const arrowY  = cy
  const midX    = (arrowX1 + arrowX2) / 2

  // ── Glyph spec ────────────────────────────────────────────────────────────
  const glyphSpec = showConditionAsBox
    ? { left: 'dot', right: 'arrow', lines: 1, neg: false }
    : (GLYPH_MAP[template] || { left: 'dot', right: 'arrow', lines: 1, neg: false })

  const isNegative  = glyphSpec.neg || template === 'ABSENCE'
  const strokeColor = isNegative
    ? 'var(--color-violation, #e05252)'
    : 'var(--color-primary, #5b8dee)'

  // Target box gets a dashed border; for PRECEDENCE (boxes swapped) the target
  // sits on the LEFT side, otherwise on the RIGHT.
  const leftIsDashed  = isPrecedence && !showConditionAsBox
  const rightIsDashed = !effectiveIsUnary && !isPrecedence && !showConditionAsBox

  // ── Label assignment ──────────────────────────────────────────────────────
  // PRECEDENCE swaps display order so box-A (must precede) appears on the left.
  // The GLYPH_MAP markers already encode the correct semantics for this layout.
  const showConditionOnRight = Boolean(conditionLabel) && target === activation

  const rawLeft  = showConditionAsBox ? activationTitle
                 : isPrecedence       ? (target || 'B')
                 :                      (activation || 'A')

  const rawRight = showConditionAsBox  ? activation
                 : isPrecedence        ? (activation || 'A')
                 : showConditionOnRight ? conditionLabel
                 :                       (target || 'B')

  // Condition label x-positions respect the PRECEDENCE swap
  const activationLabelX  = (isPrecedence ? rightX : leftX)  + BOX_W / 2
  const correlationLabelX = (isPrecedence ? leftX  : rightX) + BOX_W / 2

  // ── Text helpers ──────────────────────────────────────────────────────────
  function trimLabel(str, maxLen = 14) {
    if (!str) return ''
    return str.length > maxLen ? str.slice(0, maxLen - 1) + '…' : str
  }

  const CHARS_PER_LINE = Math.floor((BOX_W - 14) / (FONT * 0.6))

  function wrapText(text) {
    if (!text) return ['']
    const lines = []
    for (let i = 0; i < text.length; i += CHARS_PER_LINE)
      lines.push(text.slice(i, i + CHARS_PER_LINE))
    return lines
  }

  function renderLabel(text, x) {
    const lines  = compact ? [trimLabel(text)] : wrapText(text)
    const lineH  = FONT + 2
    const isMulti = lines.length > 1
    return (
      <text
        x={x} y={boxY + BOX_H / 2 + 1}
        textAnchor="middle" dominantBaseline="middle"
        fontSize={FONT} fill="var(--color-text-main, #e8edf5)"
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
    if (min_hours != null && min_hours < 0 && (max_hours == null || max_hours <= 0))
      return `≤ ${Math.abs(min_hours)}h`
    if (min_hours != null && max_hours != null && min_hours >= 0)
      return `${min_hours}–${max_hours}h`
    if (max_hours != null) return `≤ ${max_hours}h`
    if (min_hours != null && min_hours >= 0) return `≥ ${min_hours}h`
    return null
  }
  const timeLabel = !compact && !effectiveIsUnary ? formatTimeLabel(timeCondition) : null

  // ── Connector renderer ────────────────────────────────────────────────────
  function renderConnector() {
    const { left, right, lines, neg } = glyphSpec
    const hasLeftArrow  = left.includes('arrow')
    const hasRightArrow = right.includes('arrow')
    const hasLeftDot    = left.includes('dot')
    const hasRightDot   = right.includes('dot')

    // Line boundaries: recede behind arrowhead bodies; for dot+arrow the dot
    // sits just past the arrowhead base so the line starts beyond both.
    const extraLeft  = hasLeftArrow  ? ARROW_L + (hasLeftDot  ? DOT_R * 2 + 1 : 0) : 0
    const extraRight = hasRightArrow ? ARROW_L + (hasRightDot ? DOT_R * 2 + 1 : 0) : 0
    const lineX1 = arrowX1 + extraLeft
    const lineX2 = arrowX2 - extraRight

    // y-offsets for 1 / 2 / 3 parallel lines
    const offsets = lines === 1 ? [0]
                  : lines === 2 ? [-LINE_GAP / 2,  LINE_GAP / 2]
                  :               [-LINE_GAP, 0, LINE_GAP]

    // For dot+arrow: dot sits adjacent to the box, arrow sits behind it (farther from box).
    // For plain dot: dot sits at the box edge. For plain arrow: tip at box edge.
    const leftDotX  = hasLeftArrow  ? arrowX1 + DOT_R         : arrowX1
    const rightDotX = hasRightArrow ? arrowX2 - DOT_R         : arrowX2
    // Arrow tip position: when paired with a dot the tip is offset past the dot space
    const leftArrowTip  = hasLeftDot  ? arrowX1 + DOT_R * 2 + 1 : arrowX1
    const rightArrowTip = hasRightDot ? arrowX2 - DOT_R * 2 - 1 : arrowX2

    return (
      <g>
        {/* Parallel connector lines */}
        {offsets.map((dy, i) => (
          <line
            key={i}
            x1={lineX1} y1={arrowY + dy}
            x2={lineX2} y2={arrowY + dy}
            stroke={strokeColor} strokeWidth={1.5}
            strokeLinecap="round"
            opacity={neg ? 0.8 : 1}
          />
        ))}

        {/* Left endpoint markers */}
        {hasLeftArrow && (
          <polygon
            points={`${leftArrowTip},${arrowY} ${leftArrowTip + ARROW_L},${arrowY - ARROW_H} ${leftArrowTip + ARROW_L},${arrowY + ARROW_H}`}
            fill={strokeColor} opacity={neg ? 0.8 : 1}
          />
        )}
        {hasLeftDot && (
          <circle cx={leftDotX} cy={arrowY} r={DOT_R}
            fill={strokeColor} opacity={neg ? 0.8 : 1} />
        )}

        {/* Right endpoint markers */}
        {hasRightArrow && (
          <polygon
            points={`${rightArrowTip},${arrowY} ${rightArrowTip - ARROW_L},${arrowY - ARROW_H} ${rightArrowTip - ARROW_L},${arrowY + ARROW_H}`}
            fill={strokeColor} opacity={neg ? 0.8 : 1}
          />
        )}
        {hasRightDot && (
          <circle cx={rightDotX} cy={arrowY} r={DOT_R}
            fill={strokeColor} opacity={neg ? 0.8 : 1} />
        )}

        {/* Negation bar: two short vertical strokes crossing the connector midpoint */}
        {neg && (
          <g>
            <line
              x1={midX - NEG_GAP} y1={arrowY - NEG_H}
              x2={midX - NEG_GAP} y2={arrowY + NEG_H}
              stroke={strokeColor} strokeWidth={2} strokeLinecap="round"
            />
            <line
              x1={midX + NEG_GAP} y1={arrowY - NEG_H}
              x2={midX + NEG_GAP} y2={arrowY + NEG_H}
              stroke={strokeColor} strokeWidth={2} strokeLinecap="round"
            />
          </g>
        )}
      </g>
    )
  }

  // ── Unary badge + stem ────────────────────────────────────────────────────
  function renderUnaryBadge() {
    const label    = UNARY_BADGE_LABEL[template] || '?'
    const badgeTop = boxY - STEM_H - BADGE_H
    const badgeFill = isNegative ? strokeColor : 'var(--color-primary, #5b8dee)'
    return (
      <g>
        <rect
          x={cx - BADGE_W / 2} y={badgeTop}
          width={BADGE_W} height={BADGE_H}
          rx={BADGE_H / 2}
          fill={badgeFill} opacity="0.9"
        />
        <text
          x={cx} y={badgeTop + BADGE_H / 2 + 1}
          textAnchor="middle" dominantBaseline="middle"
          fontSize={compact ? 8 : 10} fontWeight="700"
          fill="#fff" fontFamily="Inter, sans-serif"
        >
          {label}
        </text>
        {/* Vertical stem from badge bottom to box top */}
        <line
          x1={cx} y1={badgeTop + BADGE_H}
          x2={cx} y2={boxY}
          stroke={badgeFill} strokeWidth={1.5}
        />
      </g>
    )
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <svg
        width={W} height={H}
        viewBox={`0 0 ${W} ${H}`}
        className="declare-visualizer"
        aria-label={`${template} rule diagram`}
      >
        {/* Left / single activity box */}
        <rect
          x={leftX} y={boxY} width={BOX_W} height={BOX_H} rx="5"
          fill="var(--color-bg-card, #1e2a3a)"
          stroke="var(--color-primary, #5b8dee)"
          strokeWidth="1.5"
          strokeDasharray='none'
        />
        {renderLabel(rawLeft, leftX + BOX_W / 2)}

        {/* Unary: badge + stem above the single box */}
        {effectiveIsUnary && renderUnaryBadge()}

        {/* Binary: right box + connector */}
        {!effectiveIsUnary && (
          <>
            <rect
              x={rightX} y={boxY} width={BOX_W} height={BOX_H} rx="5"
              fill="var(--color-bg-card, #1e2a3a)"
              stroke="var(--color-primary, #5b8dee)"
              strokeWidth="1.5"
              strokeDasharray='none'
            />
            {renderLabel(rawRight, rightX + BOX_W / 2)}
            {renderConnector()}
          </>
        )}

        {/* Compact mode: φ_a / φ_c below activation and correlation boxes */}
        {compact && showActivationLabel && (
          <text
            x={activationLabelX} y={boxY + BOX_H + 10}
            textAnchor="middle" dominantBaseline="middle"
            fontSize={9} fontStyle="italic"
            fill="var(--color-text-dim, #7a8aa0)"
            fontFamily="Inter, sans-serif"
          >
            <tspan>φ</tspan>
            <tspan fontSize={6} dy="2">a</tspan>
          </text>
        )}
        {compact && Boolean(correlationConditionLabel) && !effectiveIsUnary && !showConditionAsBox && (
          <text
            x={correlationLabelX} y={boxY + BOX_H + 10}
            textAnchor="middle" dominantBaseline="middle"
            fontSize={9} fontStyle="italic"
            fill="var(--color-text-dim, #7a8aa0)"
            fontFamily="Inter, sans-serif"
          >
            <tspan>φ</tspan>
            <tspan fontSize={6} dy="2">c</tspan>
          </text>
        )}

        {/* Expanded mode: condition labels below their respective boxes */}
        {!compact && showActivationLabel && (
          <text
            x={activationLabelX} y={boxY + BOX_H + 12}
            textAnchor="middle" dominantBaseline="middle"
            fontSize={9} fontWeight="600"
            fill="var(--color-text-dim, #7a8aa0)"
            fontFamily="Inter, sans-serif" letterSpacing="0.01em"
          >
            {trimLabel(activationTitle, 22)}
          </text>
        )}
        {!compact && Boolean(correlationConditionLabel) && !effectiveIsUnary && !showConditionAsBox && (
          <text
            x={correlationLabelX} y={boxY + BOX_H + 12}
            textAnchor="middle" dominantBaseline="middle"
            fontSize={9} fontWeight="600"
            fill="var(--color-text-dim, #7a8aa0)"
            fontFamily="Inter, sans-serif" letterSpacing="0.01em"
          >
            {trimLabel(correlationConditionLabel, 22)}
          </text>
        )}

        {/* Clock icon + time window label (expanded binary rules only) */}
        {timeLabel && (
          <g
            transform={`translate(${midX}, ${arrowY + 14})`}
            fill="none" stroke="var(--color-text-dim, #7a8aa0)"
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

        {/* Template name label at bottom (expanded mode) */}
        {!compact && (
          <text
            x={cx} y={H - 4}
            textAnchor="middle" fontSize={9}
            fill="var(--color-text-dim, #7a8aa0)"
            fontFamily="Inter, sans-serif" letterSpacing="0.03em"
          >
            {template.replace(/_/g, ' ')}
          </text>
        )}
      </svg>
    </div>
  )
}
