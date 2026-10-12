import json
import time

import pytest

from tools import calculate, lookup, run_tool


def test_lookup_returns_2025_population_with_source():
    result = lookup("Ossbridge", "population")
    assert result["value"] == 52904
    assert result["year"] == 2025
    assert result["source"] == "NR-01"
    assert "52,904" in result["evidence"]


def test_lookup_returns_2020_population():
    assert lookup("Tarnvale", "population", 2020)["value"] == 67214


def test_lookup_misspelled_name_suggests_without_guessing():
    result = lookup("Ossbrige", "population")
    assert "value" not in result
    assert "Ossbridge" in result["error"]
    assert "Ossford" in result["error"]


def test_lookup_keeps_similar_districts_apart():
    ossbridge = lookup("Ossbridge", "area_km2")
    ossford = lookup("Ossford", "area_km2")
    assert (ossbridge["value"], ossbridge["source"]) == (1284.6, "NR-01")
    assert (ossford["value"], ossford["source"]) == (846.2, "NR-02")


@pytest.mark.parametrize("district, field, current, archived", [
    ("Tarnvale", "schools", 29, 27),
    ("Kelmarsh", "pupils", 3268, 2944),
    ("Kelmarsh", "water_use_megalitres", 1739, 1652),
])
def test_lookup_ignores_archived_profiles(district, field, current, archived):
    result = lookup(district, field)
    assert result["value"] == current != archived
    assert result["source"] not in ("NR-13", "NR-14")


def test_lookup_refuses_archived_year():
    result = lookup("Kelmarsh", "population", 2019)
    assert "ARCHIVED" in result["error"]


def test_lookup_applies_correction_notice():
    result = lookup("Brightwater", "area_km2")
    assert result["value"] == 921.4
    assert result["source"] == "NR-16"
    assert "912.4" in result["note"]


def test_lookup_converts_cubic_metres_to_megalitres():
    result = lookup("Lindenmoor", "water_use_megalitres")
    assert result["value"] == 2151.4
    assert result["unit"] == "megalitres"
    assert "cubic metres" in result["note"]


def test_lookup_reads_each_sentence_template():
    assert lookup("Harrowfield", "paved_road_km")["value"] == 1037.2
    assert lookup("Millbrook", "paved_road_km")["value"] == 360.1
    assert lookup("Stonecairn", "population", 2020)["value"] == 15473
    assert lookup("Coldharbour", "founded_year")["value"] == 1845


def test_lookup_water_tariff():
    assert lookup("Redfen", "water_tariff_tenge_per_m3")["value"] == 142.35
    assert lookup("Redfen", "water_tariff_tenge_per_m3", 2024)["value"] == 131.8


@pytest.mark.parametrize("district, field, year", [
    ("Ossford", "density", 2025),
    ("", "population", 2025),
    (None, "population", 2025),
    pytest.param("x" * 500, "population", 2025, id="500-character-name"),
    ("Ossford", "population", "2025"),
    ("Ossford", "area_km2", 2020),
])
def test_lookup_never_crashes_on_bad_input(district, field, year):
    assert "error" in lookup(district, field, year)


def test_calculate_multiplication():
    assert calculate("48317 * 1.0947")["result"] == pytest.approx(52892.6199)


def test_calculate_density():
    assert calculate("44675 / 921.4")["result"] == pytest.approx(48.4859995659)


@pytest.mark.parametrize("expression", [
    "__import__('os').system('echo hi')",
    "(1).__class__",
    "9**9**9",
])
def test_calculate_refuses_dangerous_input_quickly(expression, capfd):
    start = time.perf_counter()
    result = calculate(expression)
    assert "error" in result
    assert time.perf_counter() - start < 1
    assert "hi" not in capfd.readouterr().out


@pytest.mark.parametrize("expression, message", [
    ("1 / 0", "division by zero"),
    ("10 ** 15 * 10", "too large"),
    ("44,675 / 2", "without commas"),
    ("abs(-1)", "not allowed"),
    ("x + 1", "not allowed"),
    ("'a' * 3", "not allowed"),
    ("1 +", "could not read"),
    pytest.param("1" * 400, "too long", id="400-character-expression"),
    ("(-8) ** 0.5", "not a real number"),
])
def test_calculate_returns_errors(expression, message):
    assert message in calculate(expression)["error"]


def test_run_tool_handles_bad_arguments():
    assert "not valid JSON" in run_tool("lookup", "{district: Ossford")["error"]
    assert "JSON object" in run_tool("calculate", json.dumps(["1+1"]))["error"]
    assert "missing" in run_tool("lookup", json.dumps({"district": "Ossford"}))["error"]
    assert "unknown tool" in run_tool("delete_files", "{}")["error"]
    assert run_tool("calculate", json.dumps({"expression": "2 + 3"}))["result"] == 5
