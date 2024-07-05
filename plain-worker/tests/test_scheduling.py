import datetime

import pytest

from plain.worker.scheduling import Schedule


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
    ) == datetime.datetime(2021, 1, 4)
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
    s = Schedule(minute=15, hour=15, day_of_week=0)  # Every Monday at 15:15
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
