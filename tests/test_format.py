"""
test_format.py – unit tests for human-readable size formatter.
"""
import pytest
from booklib.utils.format import human_size, dash_if_none


@pytest.mark.parametrize("size,expected", [
    (0, "0 B"),
    (1, "1 B"),
    (512, "512 B"),
    (1023, "1023 B"),
    (1024, "1.0 KB"),
    (1536, "1.5 KB"),
    (1024 * 1024, "1.0 MB"),
    (int(4.2 * 1024 * 1024), "4.2 MB"),
    (1024 ** 3, "1.0 GB"),
    (None, "—"),
])
def test_human_size(size, expected):
    assert human_size(size) == expected


@pytest.mark.parametrize("value,expected", [
    (None, "—"),
    ("", "—"),
    ("   ", "—"),
    ("Hello", "Hello"),
    (42, "42"),
    (0, "0"),
])
def test_dash_if_none(value, expected):
    assert dash_if_none(value) == expected
