import datetime

import pytest

from plain.jobs.scheduling import Schedule


def test_schedule():
    s = Schedule(hour=9)
    assert s.next(datetime.datetime(2021, 1, 1, 8, 0)) == datetime.datetime(
        2021, 1, 1, 9, 0
    )


def test_schedule_shorthands():
    assert Schedule.from_cron("@yearly").next(
        datetime.datetime(2021, 1, 1)
    ) == datetime.datetime(2022, 1, 1)
    assert Schedule.from_cron("@annually").next(
        datetime.datetime(2021, 1, 1)
    ) == datetime.datetime(2022, 1, 1)
    assert Schedule.from_cron("@monthly").next(
        datetime.datetime(2021, 1, 1)
    ) == datetime.datetime(2021, 2, 1)
    assert Schedule.from_cron("@weekly").next(
        datetime.datetime(2021, 1, 1)
    ) == datetime.datetime(2021, 1, 3)  # Sunday, per standard cron
    assert Schedule.from_cron("@daily").next(
        datetime.datetime(2021, 1, 1)
    ) == datetime.datetime(2021, 1, 2)
    assert Schedule.from_cron("@midnight").next(
        datetime.datetime(2021, 1, 1)
    ) == datetime.datetime(2021, 1, 2)
    assert Schedule.from_cron("@hourly").next(
        datetime.datetime(2021, 1, 1)
    ) == datetime.datetime(2021, 1, 1, 1, 0)


def test_schedule_range():
    s = Schedule(minute=0, hour="9-11")
    assert s.next(datetime.datetime(2021, 1, 1, 8, 0)) == datetime.datetime(
        2021, 1, 1, 9, 0
    )
    assert s.next(datetime.datetime(2021, 1, 1, 9, 0)) == datetime.datetime(
        2021, 1, 1, 10, 0
    )
    assert s.next(datetime.datetime(2021, 1, 1, 10, 0)) == datetime.datetime(
        2021, 1, 1, 11, 0
    )
    assert s.next(datetime.datetime(2021, 1, 1, 11, 0)) == datetime.datetime(
        2021, 1, 2, 9, 0
    )


def test_schedule_interval():
    s = Schedule(
        minute="*/15",
    )
    assert s.next(datetime.datetime(2021, 1, 1, 8, 0)) == datetime.datetime(
        2021, 1, 1, 8, 15
    )
    assert s.next(datetime.datetime(2021, 1, 1, 8, 15)) == datetime.datetime(
        2021, 1, 1, 8, 30
    )
    assert s.next(datetime.datetime(2021, 1, 1, 8, 30)) == datetime.datetime(
        2021, 1, 1, 8, 45
    )
    assert s.next(datetime.datetime(2021, 1, 1, 8, 45)) == datetime.datetime(
        2021, 1, 1, 9, 0
    )


def test_schedule_asterisk():
    s = Schedule(
        minute="*",
        hour="*",
        day_of_month="*",
        month="*",
        day_of_week="*",
    )
    assert s.next(datetime.datetime(2021, 1, 1, 8, 0)) == datetime.datetime(
        2021, 1, 1, 8, 1
    )


def test_complex_combinations():
    s = Schedule(minute=15, hour=15, day_of_week=1)  # Every Monday at 15:15
    next_run = s.next(datetime.datetime(2021, 6, 1))  # Check from June 1, 2021
    assert next_run == datetime.datetime(2021, 6, 7, 15, 15)  # Next Monday


def test_invalid_date_handling():
    s = Schedule(day_of_month=31, month=2)  # February 31st does not exist
    with pytest.raises(ValueError, match="No valid schedule match"):
        s.next(datetime.datetime(2021, 1, 1))


def test_non_matching_schedule():
    with pytest.raises(ValueError, match="Schedule component should be between"):
        Schedule(hour=25)  # Invalid hour, used as example for handling


def test_boundary_transition():
    s = Schedule(
        minute=0, hour=23, day_of_month=31, month=12
    )  # New Year's Eve at 23:00
    next_run = s.next(datetime.datetime(2021, 12, 31, 22, 0))
    assert next_run == datetime.datetime(2021, 12, 31, 23, 0)
    next_run = s.next(datetime.datetime(2021, 12, 31, 23, 0))
    assert next_run == datetime.datetime(2022, 12, 31, 23, 0)  # Next year


# def test_daylight_saving_time():
#     # Assuming you are in a region that uses DST and your datetime objects are timezone-aware
#     s = Schedule(hour=2)  # 2 AM, a time that might be skipped on DST start in some regions
#     start_time = datetime.datetime(2021, 3, 14, 1, 59, tzinfo=datetime.timezone.utc)  # DST start in many regions
#     next_run = s.next(start_time)
#     assert next_run.hour == 3  # Depending on how your timezone data handles DST, this may need adjustment


def test_schedule_comma():
    s = Schedule(minute=0, hour="9,12")  # 9 AM and 12 PM
    assert s.next(datetime.datetime(2021, 1, 1, 8, 0)) == datetime.datetime(
        2021, 1, 1, 9, 0
    )
    assert s.next(datetime.datetime(2021, 1, 1, 9, 0)) == datetime.datetime(
        2021, 1, 1, 12, 0
    )
    assert s.next(datetime.datetime(2021, 1, 1, 12, 0)) == datetime.datetime(
        2021, 1, 2, 9, 0
    )


def test_schedule_comma_ranges():
    s = Schedule(minute=0, hour="9-11,12-14")  # 9-11 AM and 12-2 PM
    assert s.next(datetime.datetime(2021, 1, 1, 8, 0)) == datetime.datetime(
        2021, 1, 1, 9, 0
    )
    assert s.next(datetime.datetime(2021, 1, 1, 9, 0)) == datetime.datetime(
        2021, 1, 1, 10, 0
    )
    assert s.next(datetime.datetime(2021, 1, 1, 10, 0)) == datetime.datetime(
        2021, 1, 1, 11, 0
    )
    assert s.next(datetime.datetime(2021, 1, 1, 11, 0)) == datetime.datetime(
        2021, 1, 1, 12, 0
    )
    assert s.next(datetime.datetime(2021, 1, 1, 12, 0)) == datetime.datetime(
        2021, 1, 1, 13, 0
    )
    assert s.next(datetime.datetime(2021, 1, 1, 13, 0)) == datetime.datetime(
        2021, 1, 1, 14, 0
    )
    assert s.next(datetime.datetime(2021, 1, 1, 14, 0)) == datetime.datetime(
        2021, 1, 2, 9, 0
    )


def test_day_of_week_cron_numbering():
    # Standard cron numbers weekdays Sunday=0..Saturday=6 (and accepts 7 for
    # Sunday). June 1, 2021 is a Tuesday.
    tuesday = datetime.datetime(2021, 6, 1)
    expected = {
        0: datetime.datetime(2021, 6, 6),  # Sunday
        1: datetime.datetime(2021, 6, 7),  # Monday
        5: datetime.datetime(2021, 6, 4),  # Friday
        6: datetime.datetime(2021, 6, 5),  # Saturday
        7: datetime.datetime(2021, 6, 6),  # Sunday (7 is an alias for 0)
    }
    for day_of_week, expected_next in expected.items():
        s = Schedule(minute=0, hour=0, day_of_week=day_of_week)
        assert s.next(tuesday) == expected_next, day_of_week


def test_day_of_week_names():
    tuesday = datetime.datetime(2021, 6, 1)
    assert Schedule.from_cron("0 0 * * SUN").next(tuesday) == datetime.datetime(
        2021, 6, 6
    )
    assert Schedule.from_cron("0 0 * * MON").next(tuesday) == datetime.datetime(
        2021, 6, 7
    )
    assert Schedule.from_cron("0 0 * * FRI").next(tuesday) == datetime.datetime(
        2021, 6, 4
    )
    # Names and numbers agree.
    assert Schedule.from_cron("0 0 * * MON-FRI").day_of_week.values == [1, 2, 3, 4, 5]


def test_cron_combines_restricted_days_with_or():
    # When both day-of-month and day-of-week are restricted, standard cron runs
    # when *either* matches. "30 4 1,15 * 5" = 4:30 on the 1st and 15th, plus
    # every Friday.
    s = Schedule.from_cron("30 4 1,15 * 5")
    runs = []
    current = datetime.datetime(2021, 1, 1, 0, 0)
    for _ in range(6):
        current = s.next(current)
        runs.append(current)
    assert runs == [
        datetime.datetime(2021, 1, 1, 4, 30),  # Friday and the 1st
        datetime.datetime(2021, 1, 8, 4, 30),  # Friday
        datetime.datetime(2021, 1, 15, 4, 30),  # Friday and the 15th
        datetime.datetime(2021, 1, 22, 4, 30),  # Friday
        datetime.datetime(2021, 1, 29, 4, 30),  # Friday
        datetime.datetime(2021, 2, 1, 4, 30),  # the 1st (a Monday)
    ]


def test_day_of_week_folds_seven_without_duplicates():
    # 7 is an alias for Sunday (0); the two must collapse to a single value so
    # equality and value inspection aren't thrown off by a duplicate.
    assert Schedule(day_of_week="0,7").day_of_week.values == [0]
    assert Schedule(day_of_week="0-7").day_of_week.values == [0, 1, 2, 3, 4, 5, 6]
    assert Schedule(day_of_week="*").day_of_week.values == [0, 1, 2, 3, 4, 5, 6]
    # Equivalent ways of writing "every weekday" compare equal.
    assert (
        Schedule(day_of_week="*").day_of_week == Schedule(day_of_week="0-6").day_of_week
    )


def test_stepped_wildcard_day_is_unrestricted():
    # `*/1` contains a `*`, so cron treats it as unrestricted: the day-of-month
    # and day-of-week fields combine with AND, not OR. Without that, the 1,15
    # day-of-month would OR with an always-true weekday and fire every day.
    s = Schedule.from_cron("30 4 1,15 * */1")
    assert s.next(datetime.datetime(2021, 1, 2, 0, 0)) == datetime.datetime(
        2021, 1, 15, 4, 30
    )


def test_keyword_schedule_combines_days_with_and():
    # The keyword API keeps AND semantics: only days that are both the 1st and a
    # Friday match (unlike the cron-string OR rule above).
    s = Schedule(minute=30, hour=4, day_of_month=1, day_of_week=5)
    runs = []
    current = datetime.datetime(2021, 1, 1, 0, 0)
    for _ in range(3):
        current = s.next(current)
        runs.append(current)
    assert runs == [
        datetime.datetime(2021, 1, 1, 4, 30),
        datetime.datetime(2021, 10, 1, 4, 30),
        datetime.datetime(2022, 4, 1, 4, 30),
    ]
