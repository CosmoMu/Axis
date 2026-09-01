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


class SourceKind(StrEnum):
    SIGNAL = "SIGNAL"
    ANALYSIS = "ANALYSIS"


class AnalysisDraftStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    PARSE_FAILED = "PARSE_FAILED"
    ARCHIVED = "ARCHIVED"
    PUBLISHED = "PUBLISHED"
    PUBLISH_FAILED = "PUBLISH_FAILED"
    DELETED = "DELETED"


class AnalysisType(StrEnum):
    MARKET = "MARKET"
    TICKER = "TICKER"
    SECTOR = "SECTOR"
    MACRO = "MACRO"


class AnalysisStance(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    WATCH = "WATCH"


class AnalysisHorizon(StrEnum):
    INTRADAY = "INTRADAY"
    SHORT_TERM = "SHORT_TERM"
    SWING = "SWING"
    LONG_TERM = "LONG_TERM"
    UNSPECIFIED = "UNSPECIFIED"


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
    PAST_DUE = "PAST_DUE"
    CANCEL_AT_PERIOD_END = "CANCEL_AT_PERIOD_END"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REMOVED = "REMOVED"


class MembershipSource(StrEnum):
    MANUAL = "MANUAL"
    GIFT = "GIFT"
    PAYMENT = "PAYMENT"
    IMPORT = "IMPORT"


class MembershipPlanType(StrEnum):
    DAY_PASS = "DAY_PASS"
    MONTHLY = "MONTHLY"


class EntitlementType(StrEnum):
    FREE_TRIAL = "FREE_TRIAL"
    DAY_PASS = "DAY_PASS"
    MONTHLY = "MONTHLY"
    GIFT = "GIFT"
    MANUAL = "MANUAL"
    MANUAL_EXTENSION = "MANUAL_EXTENSION"


class EntitlementStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCEL_AT_PERIOD_END = "CANCEL_AT_PERIOD_END"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REVOKED = "REVOKED"


class MembershipExtensionType(StrEnum):
    TRADING_DAYS = "TRADING_DAYS"
    CALENDAR_DAYS = "CALENDAR_DAYS"
    CALENDAR_MONTH = "CALENDAR_MONTH"
    CUSTOM = "CUSTOM"


class AcknowledgementDocumentType(StrEnum):
    RISK_DISCLOSURE = "RISK_DISCLOSURE"
    TERMS = "TERMS"
    PRIVACY = "PRIVACY"


class AccessApplicationStatus(StrEnum):
    PENDING = "PENDING"
    FLAGGED = "FLAGGED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class NewcomerRiskSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


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
