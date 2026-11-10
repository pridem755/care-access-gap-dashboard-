"""Keep the documentation in step with the code."""
import pytest

from scripts import config
from scripts.validation.processed_files import expected_columns

DATA_DICTIONARY = (config.PROJECT_ROOT / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
METHODOLOGY = (config.PROJECT_ROOT / "docs" / "methodology.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("table, column", [(t, c) for t, cols in expected_columns().items() for c in cols])
def test_every_output_column_is_in_the_data_dictionary(table, column):
    assert f"## {table}.csv" in DATA_DICTIONARY
    assert f"`{column}`" in DATA_DICTIONARY


@pytest.mark.parametrize("value", [
    *config.HRSA_SUPPLY_RULES["site_type"],
    *config.HRSA_SUPPLY_RULES["location_type"],
    config.PLACES_DASHBOARD_VALUE_TYPE,
    config.ACS_RELEASE,
    f"{config.MOE_Z_SCORE}",
])
def test_methodology_states_the_configured_rules(value):
    assert value in METHODOLOGY
