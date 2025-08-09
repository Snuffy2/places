"""Unit tests for helper functions in the places custom component.

This module tests:
- Folder creation and file operations for JSON files
- Type checking utilities
- Sensor data serialization
- String manipulation helpers
"""

from datetime import datetime
import json

import pytest

from custom_components.places.helpers import (
    clear_since_from_state,
    create_json_folder,
    get_dict_from_json_file,
    is_float,
    remove_json_file,
    safe_truncate,
    write_sensor_to_json,
)


def test_create_json_folder_creates(tmp_path):
    """Test that create_json_folder creates the specified folder."""
    folder = tmp_path / "json_folder"
    create_json_folder(str(folder))
    assert folder.exists() and folder.is_dir()


def test_create_json_folder_existing(tmp_path):
    """Test that create_json_folder does not raise when the folder already exists."""
    folder = tmp_path / "json_folder"
    folder.mkdir()
    create_json_folder(str(folder))  # Should not raise
    assert folder.exists()


def test_get_dict_from_json_file_reads(tmp_path):
    """Test that `get_dict_from_json_file` correctly reads and returns the contents of an existing JSON file as a dictionary."""
    folder = tmp_path
    filename = "test.json"
    data = {"a": 1, "b": "x"}
    file_path = folder / filename
    file_path.write_text(json.dumps(data))
    result = get_dict_from_json_file("test", filename, str(folder))
    assert result == data


def test_get_dict_from_json_file_missing(tmp_path):
    """Test that get_dict_from_json_file returns an empty dictionary when the JSON file is missing."""
    folder = tmp_path
    filename = "missing.json"
    result = get_dict_from_json_file("test", filename, str(folder))
    assert result == {}


def test_remove_json_file_removes(tmp_path):
    """Test that remove_json_file deletes the specified JSON file if it exists."""
    folder = tmp_path
    filename = "toremove.json"
    file_path = folder / filename
    file_path.write_text("test")
    assert file_path.exists()
    remove_json_file("test", filename, str(folder))
    assert not file_path.exists()


def test_remove_json_file_missing(tmp_path):
    """Test that remove_json_file does not raise when the specified JSON file is missing."""
    folder = tmp_path
    filename = "missing.json"
    # Should not raise
    remove_json_file("test", filename, str(folder))


def test_is_float_true_for_float():
    """Test that is_float returns True for valid float values and float-like strings."""
    assert is_float(1.23)
    assert is_float("2.34")
    assert is_float(0)
    assert is_float("0")
    assert is_float(-5.6)


def test_is_float_false_for_non_float():
    """Test that is_float returns False for values that are not floats or float-like strings."""
    assert not is_float(None)
    assert not is_float("abc")
    assert not is_float({})
    assert not is_float([])


def test_write_sensor_to_json_excludes_datetime(tmp_path):
    """Test that `write_sensor_to_json` writes a JSON file excluding dictionary entries with `datetime` values."""
    folder = tmp_path
    filename = "sensor.json"
    data = {"a": 1, "b": datetime.now(), "c": "ok"}
    write_sensor_to_json(data, "test", filename, str(folder))
    file_path = folder / filename
    assert file_path.exists()
    loaded = json.loads(file_path.read_text())
    assert "a" in loaded and "c" in loaded
    assert "b" not in loaded


def test_clear_since_from_state_removes_pattern():
    """Test that clear_since_from_state removes '(since ...)' patterns from strings."""
    s = "Home (since 12:34)"
    assert clear_since_from_state(s) == "Home"
    s2 = "Work (since 01/23)"
    assert clear_since_from_state(s2) == "Work"
    s3 = "Elsewhere"
    assert clear_since_from_state(s3) == "Elsewhere"


@pytest.mark.parametrize(
    "input_str,max_len,expected",
    [
        ("abc", 5, "abc"),  # shorter
        ("abcde", 5, "abcde"),  # exact
        ("abcdef", 4, "abcd"),  # longer
        (None, 3, ""),  # None
    ],
)
def test_safe_truncate(input_str, max_len, expected):
    """Test that safe_truncate returns the correct truncated string for various input scenarios."""
    assert safe_truncate(input_str, max_len) == expected
