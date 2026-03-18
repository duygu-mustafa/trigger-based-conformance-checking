from enum import Enum


class DeclareTemplate(Enum):
    # Existence (unary)
    EXISTENCE            = "Existence"
    ABSENCE              = "Absence"
    EXACTLY              = "Exactly"
    INIT                 = "Init"

    # Positive binary
    RESPONDED_EXISTENCE  = "Responded Existence"
    RESPONSE             = "Response"
    ALTERNATE_RESPONSE   = "Alternate Response"
    CHAIN_RESPONSE       = "Chain Response"

    PRECEDENCE           = "Precedence"
    ALTERNATE_PRECEDENCE = "Alternate Precedence"
    CHAIN_PRECEDENCE     = "Chain Precedence"

    CO_EXISTENCE         = "Co-Existence"

    SUCCESSION           = "Succession"
    ALTERNATE_SUCCESSION = "Alternate Succession"
    CHAIN_SUCCESSION     = "Chain Succession"

    # Negative binary
    NOT_RESPONDED_EXISTENCE = "Not Responded Existence"
    NOT_RESPONSE            = "Not Response"
    NOT_CHAIN_RESPONSE      = "Not Chain Response"
    NOT_PRECEDENCE          = "Not Precedence"
    NOT_CHAIN_PRECEDENCE    = "Not Chain Precedence"
    NOT_CO_EXISTENCE        = "Not Co-Existence"
    NOT_SUCCESSION          = "Not Succession"


UNARY_TEMPLATES = {
    DeclareTemplate.EXISTENCE,
    DeclareTemplate.ABSENCE,
    DeclareTemplate.EXACTLY,
    DeclareTemplate.INIT,
}

NEGATIVE_TEMPLATES = {
    DeclareTemplate.ABSENCE,
    DeclareTemplate.NOT_RESPONDED_EXISTENCE,
    DeclareTemplate.NOT_RESPONSE,
    DeclareTemplate.NOT_CHAIN_RESPONSE,
    DeclareTemplate.NOT_PRECEDENCE,
    DeclareTemplate.NOT_CHAIN_PRECEDENCE,
    DeclareTemplate.NOT_CO_EXISTENCE,
    DeclareTemplate.NOT_SUCCESSION,
}
