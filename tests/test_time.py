import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "work-report" / "scripts"))

from common import (day_window, logical_today, parse_ts, parse_week_label, resolve_day,  # noqa: E402
                    resolve_week, week_label, week_start_date)

CST = timezone(timedelta(hours=8))


class TimeTest(unittest.TestCase):
    def test_day_start_hour(self):
        self.assertEqual(logical_today(datetime(2026, 11, 3, 3, 59, tzinfo=CST), 4), date(2026, 11, 2))
        self.assertEqual(logical_today(datetime(2026, 11, 3, 4, 0, tzinfo=CST), 4), date(2026, 11, 3))
        self.assertEqual(logical_today(datetime(2026, 11, 3, 0, 1, tzinfo=CST), 0), date(2026, 11, 3))

    def test_window_utc_crosses_day(self):
        start, end = day_window(date(2026, 11, 2), CST, 4)
        self.assertEqual(start, datetime(2026, 11, 2, 4, tzinfo=CST))
        self.assertEqual(end - start, timedelta(days=1))
        # UTC 11-01 20:30 是北京时间 11-02 04:30，落在 11-02 窗口内
        ts = parse_ts("2026-11-01T20:30:00.000Z")
        self.assertTrue(start <= ts < end)
        # 北京时间 11-03 03:00 仍属 11-02
        self.assertTrue(start <= parse_ts("2026-11-02T19:00:00Z") < end)
        self.assertFalse(start <= parse_ts("2026-11-02T20:00:00Z") < end)

    def test_parse_ts_naive_is_utc(self):
        self.assertEqual(parse_ts("2026-11-02T00:00:00"), datetime(2026, 11, 2, tzinfo=timezone.utc))
        self.assertIsNone(parse_ts("bad"))

    def test_iso_week_cross_year(self):
        ws = week_start_date(date(2026, 12, 31), "monday")
        self.assertEqual(week_label(ws, "monday"), "2026-W53")
        self.assertEqual(week_label(week_start_date(date(2027, 1, 4), "monday"), "monday"), "2027-W01")
        self.assertEqual(parse_week_label("2026-W53", "monday"), date(2026, 12, 28))
        self.assertEqual(parse_week_label("2026W45", "monday"), date(2026, 11, 2))

    def test_resolve_day(self):
        today = date(2026, 1, 5)
        self.assertEqual(resolve_day(None, today), today)
        self.assertEqual(resolve_day("昨天", today), date(2026, 1, 4))
        self.assertEqual(resolve_day("-3", today), date(2026, 1, 2))
        self.assertEqual(resolve_day("12-30", today), date(2025, 12, 30))
        self.assertEqual(resolve_day("2026-01-01", today), date(2026, 1, 1))

    def test_resolve_week(self):
        today = date(2026, 11, 2)
        self.assertEqual(resolve_week("本周", today, "monday"), date(2026, 11, 2))
        self.assertEqual(resolve_week("last", today, "monday"), date(2026, 10, 26))
        self.assertEqual(resolve_week("2026-W44", today, "monday"), date(2026, 10, 26))


if __name__ == "__main__":
    unittest.main()
