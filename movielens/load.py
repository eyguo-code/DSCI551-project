import argparse
from decimal import InvalidOperation
from hashlib import sha256
from pathlib import Path
from zipfile import BadZipFile

from pymysql import MySQLError

from .dataset import read_dataset
from .db import connect


ROOT = Path(__file__).resolve().parents[1]
INSERTS = {
    "movies": "INSERT INTO movies (movie_id, title, release_year) VALUES (%s, %s, %s)",
    "users": "INSERT INTO users (user_id) VALUES (%s)",
    "genres": "INSERT INTO genres (genre_id, genre_name) VALUES (%s, %s)",
    "movie_genres": "INSERT INTO movie_genres (movie_id, genre_id) VALUES (%s, %s)",
    "ratings": "INSERT INTO ratings (user_id, movie_id, rating, rated_at) VALUES (%s, %s, %s, %s)",
    "tags": "INSERT INTO tags (user_id, movie_id, tag_text, tagged_at) VALUES (%s, %s, %s, %s)",
}


def load_snapshot(db, data):
    """Create the project tables and load a snapshot atomically into empty tables."""
    lock_name = sha256(db.db).hexdigest()
    with db.cursor() as cursor:
        cursor.execute("SELECT GET_LOCK(%s, 10) AS acquired", (lock_name,))
        if cursor.fetchone()["acquired"] != 1:
            raise ValueError("Another import is running for this database.")
        try:
            cursor.execute("SHOW TABLES")
            existing_tables = {next(iter(row.values())) for row in cursor.fetchall()}
            if existing_tables - INSERTS.keys():
                raise ValueError("Use a dedicated schema for this project. Other tables were found.")
            for table in existing_tables:
                cursor.execute(f"SELECT 1 FROM `{table}` LIMIT 1")
                if cursor.fetchone():
                    raise ValueError("The project tables already contain data. Use a fresh schema for another import.")

            for statement in (ROOT / "schema.sql").read_text(encoding="utf-8").split(";"):
                if statement.strip():
                    cursor.execute(statement)

            db.begin()
            try:
                for table, sql in INSERTS.items():
                    cursor.executemany(sql, data[table])
                db.commit()
            except BaseException:
                db.rollback()
                raise

            cursor.execute("ANALYZE TABLE movies, users, genres, movie_genres, ratings, tags")
            for row in cursor.fetchall():
                if row["Msg_type"] == "error":
                    raise ValueError(f"Imported rows, but could not refresh statistics for {row['Table']}: {row['Msg_text']}")
        finally:
            cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))


def main():
    parser = argparse.ArgumentParser(description="Load a MovieLens ZIP into an empty MySQL schema.")
    parser.add_argument("zip", type=Path, nargs="?", default=ROOT / "ml-latest-small.zip")
    args = parser.parse_args()
    try:
        data = read_dataset(args.zip)
        with connect() as db:
            load_snapshot(db, data)
    except (OSError, BadZipFile, InvalidOperation, ValueError, MySQLError) as error:
        parser.exit(1, f"Import failed: {error}\n")

    for table, rows in data.items():
        print(f"{table}: {len(rows):,} rows")


if __name__ == "__main__":
    main()
