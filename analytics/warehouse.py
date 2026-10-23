
r"""
Small data warehouse (star schema) built from cleanup records, in SQLite.

Fact table: fact_cleanup
Dimensions: dim_location, dim_waste_type, dim_severity, dim_date, dim_cleaner

NOTE: Uses SYNTHETIC records only. Results are not real findings.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))
from records import generate_records

DB_PATH = os.path.join(os.path.dirname(__file__), "warehouse_demo.db")

SCHEMA = """
DROP TABLE IF EXISTS fact_cleanup;
DROP TABLE IF EXISTS dim_location;
DROP TABLE IF EXISTS dim_waste_type;
DROP TABLE IF EXISTS dim_severity;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_cleaner;

CREATE TABLE dim_location (
    location_key INTEGER PRIMARY KEY,
    name TEXT UNIQUE
);

CREATE TABLE dim_waste_type (
    waste_type_key INTEGER PRIMARY KEY,
    name TEXT UNIQUE
);

CREATE TABLE dim_severity (
    severity_key INTEGER PRIMARY KEY,
    name TEXT UNIQUE
);

CREATE TABLE dim_cleaner (
    cleaner_key INTEGER PRIMARY KEY,
    cleaner_id TEXT UNIQUE
);

CREATE TABLE dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date TEXT,
    year INTEGER,
    month INTEGER,
    week TEXT,
    day_of_week TEXT
);

CREATE TABLE fact_cleanup (
    cleanup_id INTEGER PRIMARY KEY,
    location_key INTEGER REFERENCES dim_location(location_key),
    waste_type_key INTEGER REFERENCES dim_waste_type(waste_type_key),
    severity_key INTEGER REFERENCES dim_severity(severity_key),
    date_key INTEGER REFERENCES dim_date(date_key),
    cleaner_key INTEGER REFERENCES dim_cleaner(cleaner_key),
    cleaning_minutes REAL,
    response_minutes REAL,
    source TEXT
);
"""


def key_for(con, table, key_col, name):
    """Insert a dimension value if needed and return its key."""
    con.execute(
        f"INSERT OR IGNORE INTO {table} (name) VALUES (?)",
        (name,),
    )
    return con.execute(
        f"SELECT {key_col} FROM {table} WHERE name = ?",
        (name,),
    ).fetchone()[0]


def cleaner_key_for(con, cleaner_id):
    """Insert a cleaner if needed and return its dimension key."""
    con.execute(
        "INSERT OR IGNORE INTO dim_cleaner (cleaner_id) VALUES (?)",
        (cleaner_id,),
    )
    return con.execute(
        "SELECT cleaner_key FROM dim_cleaner WHERE cleaner_id = ?",
        (cleaner_id,),
    ).fetchone()[0]


def build_warehouse(records, db_path=DB_PATH):
    con = sqlite3.connect(db_path)

    try:
        con.executescript(SCHEMA)

        for r in records:
            d = r.assigned_at
            iso = d.isocalendar()
            date_key = int(d.strftime("%Y%m%d"))

            con.execute(
                "INSERT OR IGNORE INTO dim_date VALUES (?, ?, ?, ?, ?, ?)",
                (
                    date_key,
                    d.date().isoformat(),
                    d.year,
                    d.month,
                    f"{iso[0]}-W{iso[1]:02d}",
                    d.strftime("%A"),
                ),
            )

            location_key = key_for(
                con, "dim_location", "location_key", r.location
            )
            waste_key = key_for(
                con, "dim_waste_type", "waste_type_key", r.waste_type
            )
            severity_key = key_for(
                con, "dim_severity", "severity_key", r.severity
            )
            cleaner_key = cleaner_key_for(
                con, getattr(r, "cleaner_id", "UNKNOWN")
            )

            con.execute(
                """
                INSERT INTO fact_cleanup (
                    cleanup_id, location_key, waste_type_key,
                    severity_key, date_key, cleaner_key,
                    cleaning_minutes, response_minutes, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.cleanup_id,
                    location_key,
                    waste_key,
                    severity_key,
                    date_key,
                    cleaner_key,
                    round(r.cleaning_minutes, 1),
                    round(r.response_minutes, 1),
                    r.source,
                ),
            )

        con.commit()
        return con

    except Exception:
        con.rollback()
        con.close()
        raise


def show(title, rows):
    print(f"\n{title}")
    for row in rows:
        print("  ", row)


if __name__ == "__main__":
    con = build_warehouse(generate_records(300))

    count = con.execute(
        "SELECT COUNT(*) FROM fact_cleanup"
    ).fetchone()[0]

    print(f"Warehouse built: {count} fact rows (SYNTHETIC)")
    print(f"Database: {DB_PATH}")

    show(
        "ROLL-UP: cleanups and average cleaning minutes per location",
        con.execute("""
            SELECT l.name, COUNT(*),
                   ROUND(AVG(f.cleaning_minutes), 1)
            FROM fact_cleanup f
            JOIN dim_location l USING (location_key)
            GROUP BY l.name
            ORDER BY l.name
        """),
    )

    show(
        "DRILL-DOWN: Dadar vs Wadala by waste type",
        con.execute("""
            SELECT l.name, w.name, COUNT(*)
            FROM fact_cleanup f
            JOIN dim_location l USING (location_key)
            JOIN dim_waste_type w USING (waste_type_key)
            WHERE l.name IN ('Dadar', 'Wadala')
            GROUP BY l.name, w.name
            ORDER BY l.name, w.name
        """),
    )

    show(
        "ROLL-UP OVER TIME: cleanups per month per location",
        con.execute("""
            SELECT d.year, d.month, l.name, COUNT(*)
            FROM fact_cleanup f
            JOIN dim_location l USING (location_key)
            JOIN dim_date d USING (date_key)
            GROUP BY d.year, d.month, l.name
            ORDER BY d.year, d.month, l.name
        """),
    )

    show(
        "CLEANER ANALYTICS: cleanup count and average cleaning time",
        con.execute("""
            SELECT c.cleaner_id, COUNT(*) AS cleanup_count,
                   ROUND(AVG(f.cleaning_minutes), 1) AS avg_minutes
            FROM fact_cleanup f
            JOIN dim_cleaner c USING (cleaner_key)
            GROUP BY c.cleaner_id
            ORDER BY c.cleaner_id
        """),
    )

    show(
        "DRILL-DOWN: cleaner performance by location",
        con.execute("""
            SELECT c.cleaner_id, l.name, COUNT(*),
                   ROUND(AVG(f.cleaning_minutes), 1)
            FROM fact_cleanup f
            JOIN dim_cleaner c USING (cleaner_key)
            JOIN dim_location l USING (location_key)
            GROUP BY c.cleaner_id, l.name
            ORDER BY c.cleaner_id, l.name
        """),
    )

    con.close()
