import pytest

from scripts.collect_minute_bars_kiwoom import strip_sign


@pytest.mark.parametrize("raw,expected", [
    ("+279500", 279500.0),
    ("-1500", 1500.0),
    ("279500", 279500.0),
    ("", 0.0),
])
def test_strip_sign_removes_direction_prefix(raw, expected):
    assert strip_sign(raw) == expected
