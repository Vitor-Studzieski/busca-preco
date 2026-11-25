import sqlite3
from pathlib import Path

from pricing.market_data import MARKETS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "pricing" / "markets.sqlite3"

def main():
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("DROP TABLE IF EXISTS markets")
        connection.execute(
            """
            CREATE TABLE markets (
                id INTEGER PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                retailer TEXT NOT NULL,
                unit TEXT NOT NULL,
                url TEXT NOT NULL,
                active INTEGER NOT NULL,
                logo TEXT NOT NULL,
                display_order INTEGER NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO markets (slug, retailer, unit, url, active, logo, display_order)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            MARKETS,
        )


if __name__ == "__main__":
    main()
