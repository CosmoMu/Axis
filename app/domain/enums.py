from enum import StrEnum


class TradeCategory(StrEnum):
    SHORT_TERM = "SHORT_TERM"
    SWING = "SWING"
    LEAPS = "LEAPS"


class TradeState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RUNNER = "RUNNER"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TradeAction(StrEnum):
    ENTRY = "ENTRY"
    ADD = "ADD"
    UPDATE = "UPDATE"
    TP1 = "TP1"
    TP2 = "TP2"
    RUNNER = "RUNNER"
    PARTIAL_SL = "PARTIAL_SL"
    SL = "SL"
    CLOSE = "CLOSE"
    CANCEL = "CANCEL"
    ROLL = "ROLL"


class ActionStage(StrEnum):
    NONE = "NONE"
    FIRST = "FIRST"
    SECOND = "SECOND"
    THIRD = "THIRD"
    FOURTH = "FOURTH"


class OptionSide(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class SourceStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    PARSED = "PARSED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class DraftStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    PARSE_FAILED = "PARSE_FAILED"
    READY = "READY"
    PUBLISHED = "PUBLISHED"
    PUBLISH_FAILED = "PUBLISH_FAILED"
    DELETED = "DELETED"


class PublicationStatus(StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REMOVED = "REMOVED"


class MembershipSource(StrEnum):
    MANUAL = "MANUAL"
    GIFT = "GIFT"
    PAYMENT = "PAYMENT"
    IMPORT = "IMPORT"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class LlmWorkload(StrEnum):
    SIGNAL_PARSE = "SIGNAL_PARSE"
    SIGNAL_REPAIR = "SIGNAL_REPAIR"
    ANALYSIS_PARSE = "ANALYSIS_PARSE"
    ANALYSIS_REWRITE = "ANALYSIS_REWRITE"
