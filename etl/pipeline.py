"""Download Alberta's historical wildfire data, clean it, load it into SQLite,
and export the JSON files the dashboard reads."""

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
SOURCE_URL = (
    "https://open.alberta.ca/dataset/a221e7a0-4f46-4be7-9c5a-e29de9a3447e/resource/"
    "80480824-0c50-456c-9723-f9d4fc136141/download/fp-historical-wildfire-data-2006-2025.csv"
)
RAW_CSV = ROOT / "data" / "raw.csv"
DB_PATH = ROOT / "data" / "wildfires.db"
OUT_DIR = ROOT / "site" / "data"

# The first letter of a fire number is the forest area that responded to it
FOREST_AREAS = {
    "C": "Calgary", "E": "Edson", "G": "Grande Prairie", "H": "High Level", "L": "Lac La Biche",
    "M": "Fort McMurray", "P": "Peace River", "R": "Rocky Mountain House", "S": "Slave Lake",
    "W": "Whitecourt",
}


def download(url=SOURCE_URL, dest=RAW_CSV):
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"downloaded {len(resp.content) / 1e6:.1f} MB")


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({
        "fire_number": raw["FIRE_NUMBER"].str.strip(),
        "year": raw["YEAR"].astype(int),
        "name": raw["FIRE_NAME"].fillna("").str.strip(),
        "hectares": pd.to_numeric(raw["CURRENT_SIZE"], errors="coerce").fillna(0),
        "size_class": raw["SIZE_CLASS"],
        "lat": pd.to_numeric(raw["LATITUDE"], errors="coerce"),
        "lon": pd.to_numeric(raw["LONGITUDE"], errors="coerce"),
        "cause": raw["GENERAL_CAUSE"].fillna("Undetermined").str.strip(),
    })
    df["forest_area"] = df["fire_number"].str[0].map(FOREST_AREAS).fillna("Other")
    df["cause_group"] = df["cause"].map(
        lambda c: "Lightning" if c == "Lightning" else "Unknown" if c in ("Undetermined", "Under Investigation") else "Human"
    )

    started = pd.to_datetime(raw["FIRE_START_DATE"], errors="coerce")
    reported = pd.to_datetime(raw["REPORTED_DATE"], errors="coerce")
    arrived = pd.to_datetime(raw["IA_ARRIVAL_AT_FIRE_DATE"], errors="coerce")
    out = pd.to_datetime(raw["FIRST_EX_DATE"], errors="coerce")

    df["start_date"] = started.fillna(reported).dt.strftime("%Y-%m-%d")
    df["month"] = started.fillna(reported).dt.month
    # Minutes from the fire being reported to the first crew arriving
    response = (arrived - reported).dt.total_seconds() / 60
    df["response_minutes"] = response.where(response.between(0, 7 * 24 * 60)).round()
    days_out = (out - reported).dt.total_seconds() / 86400
    df["days_to_extinguish"] = days_out.where(days_out >= 0).round(1)

    # Drop rows with no usable location, and points outside Alberta
    df = df[df["lat"].between(48.9, 60.1) & df["lon"].between(-120.1, -109.9)]
    return df.drop_duplicates(["year", "fire_number"]).reset_index(drop=True)


SCHEMA = """
DROP TABLE IF EXISTS fires;
CREATE TABLE fires (
    fire_number         TEXT NOT NULL,
    year                INTEGER NOT NULL,
    name                TEXT,
    hectares            REAL NOT NULL CHECK (hectares >= 0),
    size_class          TEXT,
    lat                 REAL NOT NULL,
    lon                 REAL NOT NULL,
    cause               TEXT NOT NULL,
    forest_area         TEXT NOT NULL,
    cause_group         TEXT NOT NULL,
    start_date          TEXT,
    month               INTEGER,
    response_minutes    REAL,
    days_to_extinguish  REAL,
    PRIMARY KEY (year, fire_number)
);
CREATE INDEX idx_fires_year ON fires (year);
CREATE INDEX idx_fires_area ON fires (forest_area);
"""


def load(df: pd.DataFrame, conn: sqlite3.Connection):
    conn.executescript(SCHEMA)
    df.to_sql("fires", conn, if_exists="append", index=False)
    conn.commit()


QUERIES = {
    "by_year": """
        SELECT year,
               COUNT(*)                                            AS fires,
               ROUND(SUM(hectares))                                AS hectares,
               SUM(cause_group = 'Lightning')                      AS lightning,
               SUM(cause_group = 'Human')                          AS human
        FROM fires
        GROUP BY year
        ORDER BY year
    """,
    "largest": """
        SELECT year, fire_number, name, ROUND(hectares) AS hectares, cause, forest_area, start_date
        FROM fires
        ORDER BY hectares DESC
        LIMIT 15
    """,
    "by_area": """
        SELECT forest_area,
               COUNT(*)                         AS fires,
               ROUND(SUM(hectares))             AS hectares,
               ROUND(AVG(response_minutes))     AS avg_response_minutes
        FROM fires
        GROUP BY forest_area
        ORDER BY fires DESC
    """,
}


def export(conn: sqlite3.Connection, df: pd.DataFrame):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {name: pd.read_sql_query(sql, conn).to_dict(orient="records") for name, sql in QUERIES.items()}
    summary["source_rows"] = int(len(df))
    summary["years"] = [int(df["year"].min()), int(df["year"].max())]
    (OUT_DIR / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    # Compact per-fire rows for the map and filters: arrays instead of objects keeps the file small
    causes = sorted(df["cause"].unique())
    areas = sorted(df["forest_area"].unique())
    rows = [
        [int(r.year), int(r.month) if pd.notna(r.month) else 0, round(r.lat, 3), round(r.lon, 3),
         round(r.hectares, 2), causes.index(r.cause), areas.index(r.forest_area),
         int(r.response_minutes) if pd.notna(r.response_minutes) else None, r.name, r.fire_number]
        for r in df.itertuples()
    ]
    fires = {
        "columns": ["year", "month", "lat", "lon", "hectares", "cause", "area", "response", "name", "id"],
        "causes": causes,
        "areas": areas,
        "rows": rows,
    }
    (OUT_DIR / "fires.json").write_text(json.dumps(fires, separators=(",", ":")), encoding="utf-8")
    print(f"exported {len(rows):,} fires")


def main():
    if "--offline" not in sys.argv:
        download()
    df = clean(pd.read_csv(RAW_CSV, low_memory=False))
    with sqlite3.connect(DB_PATH) as conn:
        load(df, conn)
        export(conn, df)


if __name__ == "__main__":
    main()
