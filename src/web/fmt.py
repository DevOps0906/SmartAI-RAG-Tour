"""화면 표시용 포맷터."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))


def kst_stamp(raw: str | None) -> str:
    """RFC 2822('Fri, 16 Oct 2026 00:02:31 +0000') 또는 ISO 시각을 'YYYY-MM-DD HH:MM'(KST)로. 실패 시 빈 문자열."""
    if not raw:
        return ""
    dt = None
    try:
        dt = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(str(raw))
        except ValueError:
            return ""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
