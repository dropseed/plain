import datetime

from plain.jobs.parameters import (
    DateParameter,
    DateTimeParameter,
    JobParameters,
    LegacyModelParameter,
    ModelParameter,
)


def test_date_parameter_serialization():
    """Test date serialization/deserialization."""
    test_date = datetime.date(2024, 1, 15)
    test_datetime = datetime.datetime(2024, 1, 15, 10, 30, 45)

    # Test DateParameter only handles dates, not datetimes
    assert DateParameter.serialize(test_date) is not None
    assert DateParameter.serialize(test_datetime) is None  # datetime is excluded
    assert DateParameter.serialize("not a date") is None

    # Test date serialization
    date_serialized = DateParameter.serialize(test_date)
    expected_date = "__plain://date/2024-01-15"
    assert date_serialized == expected_date

    # Test deserialization
    assert DateParameter.deserialize(date_serialized) is not None
    assert DateParameter.deserialize("__plain://datetime/2024-01-15T10:30:45") is None
    assert DateParameter.deserialize({"wrong": "format"}) is None

    # Test round trip
    assert DateParameter.deserialize(date_serialized) == test_date


def test_datetime_parameter_serialization():
    """Test datetime serialization/deserialization."""
    test_date = datetime.date(2024, 1, 15)
    test_datetime = datetime.datetime(2024, 1, 15, 10, 30, 45)
    test_datetime_tz = datetime.datetime(2024, 1, 15, 10, 30, 45, tzinfo=datetime.UTC)

    # Test DateTimeParameter only handles datetimes, not plain dates
    assert DateTimeParameter.serialize(test_date) is None  # plain date excluded
    assert DateTimeParameter.serialize(test_datetime) is not None
    assert DateTimeParameter.serialize(test_datetime_tz) is not None
    assert DateTimeParameter.serialize("not a datetime") is None

    # Test datetime serialization
    datetime_serialized = DateTimeParameter.serialize(test_datetime)
    datetime_tz_serialized = DateTimeParameter.serialize(test_datetime_tz)

    expected_datetime = "__plain://datetime/2024-01-15T10:30:45"
    expected_datetime_tz = "__plain://datetime/2024-01-15T10:30:45+00:00"

    assert datetime_serialized == expected_datetime
    assert datetime_tz_serialized == expected_datetime_tz

    # Test deserialization
    assert DateTimeParameter.deserialize(datetime_serialized) is not None
    assert DateTimeParameter.deserialize(datetime_tz_serialized) is not None
    assert DateTimeParameter.deserialize("__plain://date/2024-01-15") is None
    assert DateTimeParameter.deserialize({"wrong": "format"}) is None

    # Test round trip
    assert DateTimeParameter.deserialize(datetime_serialized) == test_datetime
    assert DateTimeParameter.deserialize(datetime_tz_serialized) == test_datetime_tz
    deserialized_tz = DateTimeParameter.deserialize(datetime_tz_serialized)
    assert deserialized_tz is not None
    assert deserialized_tz.tzinfo == datetime.UTC


def test_job_parameters_integration():
    """Test the JobParameters interface with mixed types."""
    test_date = datetime.date(2024, 1, 15)
    test_datetime = datetime.datetime(2024, 1, 15, 10, 30, 45)

    # Test args and kwargs
    serialized = JobParameters.to_json(
        (42, "hello", test_date),
        {"name": "test", "scheduled_at": test_datetime, "count": 5},
    )

    expected_args = [
        42,
        "hello",
        "__plain://date/2024-01-15",
    ]
    expected_kwargs = {
        "name": "test",
        "scheduled_at": "__plain://datetime/2024-01-15T10:30:45",
        "count": 5,
    }

    assert serialized["args"] == expected_args
    assert serialized["kwargs"] == expected_kwargs

    # Test deserialization
    args, kwargs = JobParameters.from_json(serialized)

    assert len(args) == 3
    assert args[0] == 42
    assert args[1] == "hello"
    assert isinstance(args[2], datetime.date)
    assert args[2] == test_date

    assert len(kwargs) == 3
    assert kwargs["name"] == "test"
    assert isinstance(kwargs["scheduled_at"], datetime.datetime)
    assert kwargs["scheduled_at"] == test_datetime
    assert kwargs["count"] == 5


def test_model_parameter_formats():
    """Test model parameter format detection."""
    # Test format validation (these will return None due to non-existent models, but we can test invalid formats)
    assert ModelParameter.deserialize("wrong format") is None
    assert ModelParameter.deserialize("gid://old/format/123") is None
    assert ModelParameter.deserialize("__plain://model/") is None  # Empty
    assert (
        ModelParameter.deserialize("__plain://model/incomplete") is None
    )  # Not enough parts

    # Test legacy format detection (these will also return None due to non-existent models)
    assert LegacyModelParameter.deserialize({"new": "format"}) is None
    assert LegacyModelParameter.deserialize("not-a-gid") is None
    assert LegacyModelParameter.deserialize("gid://") is None  # Empty

    # Legacy doesn't serialize new instances
    assert LegacyModelParameter.serialize("anything") is None


def test_round_trip_integrity():
    """Test that multiple serialization cycles preserve data."""
    original_args = (datetime.date(2024, 1, 15), "string", 42)
    original_kwargs = {
        "dt": datetime.datetime(2024, 1, 15, 10, 30, 45, 123456),
        "num": 100,
    }

    # First round trip
    serialized1 = JobParameters.to_json(original_args, original_kwargs)
    args1, kwargs1 = JobParameters.from_json(serialized1)

    # Second round trip
    serialized2 = JobParameters.to_json(args1, kwargs1)
    args2, kwargs2 = JobParameters.from_json(serialized2)

    # Verify data integrity
    assert args1 == args2
    assert kwargs1 == kwargs2
    assert args2[0] == original_args[0]
    assert args2[1] == original_args[1]
    assert args2[2] == original_args[2]
    assert kwargs2["dt"] == original_kwargs["dt"]
    assert kwargs2["num"] == original_kwargs["num"]
