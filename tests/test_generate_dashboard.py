import pytest

from scripts.generate_dashboard import _to_float


@pytest.mark.parametrize("raw,expected", [
    ("12345", 12345.0),
    ("-3.5", -3.5),
    ("", 0.0),
    (None, 0.0),
    ("abc", 0.0),
])
def test_to_float_handles_empty_and_invalid_kis_fields(raw, expected):
    assert _to_float(raw) == expected
