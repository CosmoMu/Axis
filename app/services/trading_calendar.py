from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

ET = ZoneInfo("America/New_York")


class TradingCalendarError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TradingDayWindow:
    first_trading_day: date
    last_trading_day: date
    expires_at: datetime


class TradingCalendarService:
    """US equity membership calendar backed by the maintained XNYS schedule."""

    def __init__(self, calendar: object | None = None) -> None:
        self.calendar = calendar or xcals.get_calendar("XNYS")

    def trading_window(
        self,
        activated_at: datetime,
        trading_days: int,
        *,
        continue_after: datetime | None = None,
    ) -> TradingDayWindow:
        if trading_days <= 0:
            raise TradingCalendarError("TRADING_DAYS_INVALID")
        now = self._aware(activated_at)
        if continue_after is not None and self._aware(continue_after) > now:
            base_date = self._aware(continue_after).astimezone(ET).date() + timedelta(days=1)
            first = self._date_to_session(base_date, direction="next")
        else:
            local_date = now.astimezone(ET).date()
            if self.calendar.is_session(local_date):
                close = self._python_datetime(self.calendar.session_close(local_date))
                first = (
                    local_date
                    if now <= close
                    else self._date_to_session(local_date + timedelta(days=1), direction="next")
                )
            else:
                first = self._date_to_session(local_date, direction="next")
        if trading_days == 1:
            last = first
        else:
            sessions = self.calendar.sessions_window(first, trading_days)
            last = self._python_date(sessions[-1])
        expiry_local = datetime.combine(last, time(23, 59, 59), tzinfo=ET)
        return TradingDayWindow(first, last, expiry_local.astimezone(UTC))

    def is_trading_day(self, value: date) -> bool:
        return bool(self.calendar.is_session(value))

    def is_market_open(self, value: datetime) -> bool:
        current = self._aware(value)
        session_date = current.astimezone(ET).date()
        if not self.calendar.is_session(session_date):
            return False
        opened = self._python_datetime(self.calendar.session_open(session_date))
        closed = self._python_datetime(self.calendar.session_close(session_date))
        return opened <= current <= closed

    def next_trading_day(self, value: date) -> date:
        return self._date_to_session(value, direction="next")

    @staticmethod
    def calendar_expiry(base: datetime, *, days: int = 0, months: int = 0) -> datetime:
        if days <= 0 and months <= 0:
            raise TradingCalendarError("CALENDAR_EXTENSION_INVALID")
        local = TradingCalendarService._aware(base).astimezone(ET)
        target_date = local.date() + timedelta(days=days)
        if months:
            from dateutil.relativedelta import relativedelta

            target_date += relativedelta(months=months)
        return datetime.combine(target_date, time(23, 59, 59), tzinfo=ET).astimezone(UTC)

    def _date_to_session(self, value: date, *, direction: str) -> date:
        try:
            return self._python_date(self.calendar.date_to_session(value, direction=direction))
        except (ValueError, IndexError) as exc:
            raise TradingCalendarError("TRADING_CALENDAR_OUT_OF_RANGE") from exc

    @staticmethod
    def _python_date(value: object) -> date:
        to_pydatetime = getattr(value, "to_pydatetime", None)
        parsed = to_pydatetime() if callable(to_pydatetime) else value
        if isinstance(parsed, datetime):
            return parsed.date()
        if isinstance(parsed, date):
            return parsed
        raise TradingCalendarError("TRADING_CALENDAR_VALUE_INVALID")

    @staticmethod
    def _python_datetime(value: object) -> datetime:
        to_pydatetime = getattr(value, "to_pydatetime", None)
        parsed = to_pydatetime() if callable(to_pydatetime) else value
        if not isinstance(parsed, datetime):
            raise TradingCalendarError("TRADING_CALENDAR_VALUE_INVALID")
        return TradingCalendarService._aware(parsed)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
