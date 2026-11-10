"""Single source of truth for every raw dataset the pipeline downloads."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DOWNLOAD_LOG_PATH = RAW_DIR / "download_log.csv"
SUPERSEDED_DIR_NAME = "superseded"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
VALIDATION_REPORT_PATH = PROJECT_ROOT / "docs" / "validation_report.md"
LOCALITY_TABLES = ("dim_geography", "acs_va", "places_va", "fact_supply")
SITE_TABLE = "hrsa_sites_va"

CENSUS_KEY_ENV = "CENSUS_API_KEY"
USER_AGENT = "care-access-gap-dashboard/0.1 (data pipeline)"
TIMEOUT_SECONDS = (10, 120)
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0

STATE_FIPS = "51"
STATE_ABBR = "VA"
STATE_COUNTY_COUNT = 133
STATE_LOCALITY_TYPE_COUNTS = {"County": 95, "City": 38}
STATE_BOUNDING_BOX = {"latitude": (36.4, 39.6), "longitude": (-83.8, -75.1)}

ACS_END_YEAR = 2024
ACS_RELEASE = f"{ACS_END_YEAR - 4}-{ACS_END_YEAR}"
ACS_SUBJECT_URL = f"https://api.census.gov/data/{ACS_END_YEAR}/acs/acs5/subject"
ACS_ID_FIELDS = ("NAME", "GEO_ID")
ACS_S2701_VARIABLES = {
    "S2701_C01_001E": "insurance_universe",
    "S2701_C04_001E": "uninsured",
    "S2701_C05_001E": "uninsured_pct",
}
ACS_S1701_VARIABLES = {
    "S1701_C01_001E": "poverty_universe",
    "S1701_C02_001E": "below_poverty",
    "S1701_C03_001E": "below_poverty_pct",
}
MOE_Z_SCORE = 1.645

PLACES_RELEASE = "2025"
PLACES_DATASET_ID = "swc5-untb"
PLACES_URL = f"https://data.cdc.gov/resource/{PLACES_DATASET_ID}.csv"
PLACES_COUNT_URL = f"https://data.cdc.gov/resource/{PLACES_DATASET_ID}.json"
PLACES_METADATA_URL = f"https://data.cdc.gov/api/views/{PLACES_DATASET_ID}.json"
PLACES_PAGE_SIZE = 50_000
PLACES_ORDER_BY = ":id"
PLACES_MEASURES = {"DIABETES": "diabetes", "BPHIGH": "high_blood_pressure"}
PLACES_VALUE_TYPES = ("CrdPrv", "AgeAdjPrv")
PLACES_DASHBOARD_VALUE_TYPE = "AgeAdjPrv"

BOUNDARY_YEAR = ACS_END_YEAR
BOUNDARY_URL = (
    f"https://www2.census.gov/geo/tiger/GENZ{BOUNDARY_YEAR}/shp/"
    f"cb_{BOUNDARY_YEAR}_us_county_500k.zip"
)
BOUNDARY_STATE_COLUMN = "STATEFP"
BOUNDARY_FIPS_COLUMN = "GEOID"
BOUNDARY_LOCALITY_TYPES = {"06": "County", "25": "City"}
SQUARE_METERS_PER_SQUARE_MILE = 2_589_988.110336

HRSA_URL = (
    "https://data.hrsa.gov/DataDownload/DD_Files/"
    "Health_Center_Service_Delivery_and_LookAlike_Sites.csv"
)
HRSA_COLUMNS = {
    "site_id": "BPHC Assigned Number",
    "state": "Site State Abbreviation",
    "county_fips": "State and County Federal Information Processing Standard Code",
    "status": "Site Status Description",
    "site_type": "Health Center Type Description",
    "location_type": "Health Center Location Type Description",
    "latitude": "Geocoding Artifact Address Primary Y Coordinate",
    "longitude": "Geocoding Artifact Address Primary X Coordinate",
}
HRSA_SITE_FIELDS = {
    "BPHC Assigned Number": "site_id",
    "Site Name": "site_name",
    "Health Center Name": "health_center_name",
    "Health Center Type": "program_type",
    "Site Status Description": "status",
    "Health Center Type Description": "site_type",
    "Health Center Location Type Description": "location_type",
    "Site Address": "address",
    "Site City": "city",
    "Site Postal Code": "postal_code",
    "State and County Federal Information Processing Standard Code": "fips",
    "Geocoding Artifact Address Primary Y Coordinate": "latitude",
    "Geocoding Artifact Address Primary X Coordinate": "longitude",
}
HRSA_SUPPLY_RULES = {
    "status": ("Active",),
    "location_type": ("Permanent",),
    "site_type": ("Service Delivery Site", "Administrative/Service Delivery Site"),
}
HRSA_VALID_VALUES = {
    "status": ("Unknown", "Active", "Pending Verification", "Terminated"),
    "site_type": ("Administrative", "Administrative/Service Delivery Site", "Service Delivery Site"),
    "location_type": ("Unknown", "Mobile Van", "Permanent", "Seasonal"),
}

RUCC_YEAR = "2023"
RUCC_URL = "https://www.ers.usda.gov/media/5768/2023-rural-urban-continuum-codes.csv"
RUCC_COLUMNS = ("FIPS", "State", "County_Name", "Attribute", "Value")
RUCC_ATTRIBUTE = f"RUCC_{RUCC_YEAR}"
RUCC_VALID_CODES = tuple(str(code) for code in range(1, 10))
RUCC_METRO_CODES = ("1", "2", "3")
RUCC_FIELDS = {RUCC_ATTRIBUTE: "rucc_code", "Description": "rucc_description", "Population_2020": "population_2020"}

FIPS_PATTERN = rf"{STATE_FIPS}\d{{3}}"


def with_moe(estimates: tuple[str, ...]) -> tuple[str, ...]:
    """Return each estimate code followed by its margin-of-error code."""
    codes: list[str] = []
    for code in estimates:
        if not code.endswith("E"):
            raise ValueError(f"ACS estimate code must end in 'E': {code}")
        codes += [code, code[:-1] + "M"]
    return tuple(codes)


def acs_params(estimates: tuple[str, ...]) -> dict[str, str]:
    """Build Census API query parameters for all counties in the state."""
    return {
        "get": ",".join(ACS_ID_FIELDS + with_moe(estimates)),
        "for": "county:*",
        "in": f"state:{STATE_FIPS}",
    }


@dataclass(frozen=True)
class Source:
    """One raw dataset: where it comes from and how its file is named."""

    name: str
    prefix: str
    content: str
    version: str
    extension: str
    url: str | None
    params: dict[str, str] = field(default_factory=dict)
    manual_allowed: bool = False

    def filename(self, on: date) -> str:
        """Return the file name for a download made on the given day."""
        return f"{self.prefix}_{self.content}_{self.version}_{on:%Y%m%d}.{self.extension}"


SOURCES: dict[str, Source] = {
    s.name: s
    for s in (
        Source(
            name="acs_s2701",
            prefix="acs",
            content="s2701",
            version=ACS_RELEASE,
            extension="json",
            url=ACS_SUBJECT_URL,
            params=acs_params(tuple(ACS_S2701_VARIABLES)),
        ),
        Source(
            name="acs_s1701",
            prefix="acs",
            content="s1701",
            version=ACS_RELEASE,
            extension="json",
            url=ACS_SUBJECT_URL,
            params=acs_params(tuple(ACS_S1701_VARIABLES)),
        ),
        Source(
            name="places",
            prefix="places",
            content="county",
            version=PLACES_RELEASE,
            extension="csv",
            url=PLACES_URL,
        ),
        Source(
            name="boundaries",
            prefix="boundaries",
            content="county500k",
            version=str(BOUNDARY_YEAR),
            extension="zip",
            url=BOUNDARY_URL,
        ),
        Source(
            name="hrsa",
            prefix="hrsa",
            content="sites",
            version="current",
            extension="csv",
            url=HRSA_URL,
            manual_allowed=True,
        ),
        Source(
            name="rucc",
            prefix="rucc",
            content="codes",
            version=RUCC_YEAR,
            extension="csv",
            url=RUCC_URL,
            manual_allowed=True,
        ),
    )
}
