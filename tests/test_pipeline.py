import sqlite3

import pandas as pd

from etl.pipeline import QUERIES, clean, load


def raw_rows():
    base = {
        "FIRE_NAME": None, "SIZE_CLASS": "A", "FIRE_START_DATE": "2023-05-01 12:00",
        "REPORTED_DATE": "2023-05-01 13:00", "IA_ARRIVAL_AT_FIRE_DATE": "2023-05-01 13:45",
        "FIRST_EX_DATE": "2023-05-03 13:00",
    }
    return pd.DataFrame([
        {**base, "YEAR": 2023, "FIRE_NUMBER": "HWF001", "CURRENT_SIZE": 120.5, "LATITUDE": 58.1,
         "LONGITUDE": -117.2, "GENERAL_CAUSE": "Lightning"},
        {**base, "YEAR": 2023, "FIRE_NUMBER": "CWF002", "CURRENT_SIZE": 0.5, "LATITUDE": 51.0,
         "LONGITUDE": -114.5, "GENERAL_CAUSE": "Recreation"},
        # Duplicate of the first fire
        {**base, "YEAR": 2023, "FIRE_NUMBER": "HWF001", "CURRENT_SIZE": 120.5, "LATITUDE": 58.1,
         "LONGITUDE": -117.2, "GENERAL_CAUSE": "Lightning"},
        # Outside Alberta: should be dropped
        {**base, "YEAR": 2024, "FIRE_NUMBER": "SWF003", "CURRENT_SIZE": 10, "LATITUDE": 45.0,
         "LONGITUDE": -75.0, "GENERAL_CAUSE": "Resident"},
        # Crew "arrived" before the fire was reported: response time should be blank
        {**base, "YEAR": 2024, "FIRE_NUMBER": "MWF004", "CURRENT_SIZE": 5000, "LATITUDE": 56.7,
         "LONGITUDE": -111.4, "GENERAL_CAUSE": "Undetermined", "IA_ARRIVAL_AT_FIRE_DATE": "2023-04-01 10:00"},
    ])


def test_clean_maps_areas_and_causes():
    df = clean(raw_rows())
    assert len(df) == 3
    assert df.set_index("fire_number").loc["HWF001", "forest_area"] == "High Level"
    assert df.set_index("fire_number").loc["CWF002", "cause_group"] == "Human"
    assert df.set_index("fire_number").loc["MWF004", "cause_group"] == "Unknown"


def test_clean_computes_response_and_extinguish_times():
    df = clean(raw_rows()).set_index("fire_number")
    assert df.loc["HWF001", "response_minutes"] == 45
    assert df.loc["HWF001", "days_to_extinguish"] == 2.0
    assert pd.isna(df.loc["MWF004", "response_minutes"])
    assert df.loc["HWF001", "month"] == 5


def test_sql_summaries():
    conn = sqlite3.connect(":memory:")
    load(clean(raw_rows()), conn)
    by_year = pd.read_sql_query(QUERIES["by_year"], conn)
    assert by_year["fires"].tolist() == [2, 1]
    assert by_year.loc[0, "lightning"] == 1 and by_year.loc[0, "human"] == 1
    largest = pd.read_sql_query(QUERIES["largest"], conn)
    assert largest.loc[0, "fire_number"] == "MWF004"
