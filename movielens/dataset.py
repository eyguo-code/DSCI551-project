import csv
import io
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import PurePosixPath
from zipfile import ZipFile


YEAR_AT_END = re.compile(r"\((\d{4})\)\s*$")
VALID_RATINGS = {Decimal(i) / 2 for i in range(1, 11)}


def _csv_rows(archive, filename, columns):
    matches = [entry for entry in archive.infolist()
               if not entry.is_dir() and PurePosixPath(entry.filename).name == filename]
    if len(matches) != 1:
        raise ValueError(f"The ZIP must contain exactly one {filename}.")

    with archive.open(matches[0]) as member:
        reader = csv.DictReader(io.TextIOWrapper(member, encoding="utf-8-sig", newline=""))
        if reader.fieldnames != columns.split(","):
            raise ValueError(f"{filename} has an unexpected header. Expected {columns}.")
        for row in reader:
            if None in row or not all(value and value.strip() for value in row.values()):
                raise ValueError(f"{filename}, line {reader.line_num}, has a missing or extra field.")
            yield row


def _utc_datetime(timestamp):
    # MySQL DATETIME has no timezone. Store the UTC wall-clock value.
    return datetime.fromtimestamp(int(timestamp), timezone.utc).replace(tzinfo=None)


def read_dataset(zip_path):
    """Read the MovieLens CSVs without extracting the ZIP onto disk."""
    with ZipFile(zip_path) as archive:
        movies, ratings, tags, movie_genres = [], [], [], []
        genre_ids = {}

        for row in _csv_rows(archive, "movies.csv", "movieId,title,genres"):
            movie_id = int(row["movieId"])
            title = row["title"].strip()
            year = YEAR_AT_END.search(title)
            movies.append((movie_id, title, int(year[1]) if year else None))
            if row["genres"] != "(no genres listed)":
                for genre in row["genres"].split("|"):
                    genre_id = genre_ids.setdefault(genre, len(genre_ids) + 1)
                    movie_genres.append((movie_id, genre_id))

        for row in _csv_rows(archive, "ratings.csv", "userId,movieId,rating,timestamp"):
            score = Decimal(row["rating"])
            if score not in VALID_RATINGS:
                raise ValueError(f"Invalid rating of {score} for movie {row['movieId']}.")
            ratings.append((int(row["userId"]), int(row["movieId"]), score,
                            _utc_datetime(row["timestamp"])))

        for row in _csv_rows(archive, "tags.csv", "userId,movieId,tag,timestamp"):
            tags.append((int(row["userId"]), int(row["movieId"]), row["tag"].strip(),
                         _utc_datetime(row["timestamp"])))

    if not movies or not ratings:
        raise ValueError("The MovieLens snapshot must include movies and ratings.")
    user_ids = {row[0] for row in ratings} | {row[0] for row in tags}
    return {
        "movies": movies,
        "users": [(user_id,) for user_id in sorted(user_ids)],
        "genres": [(genre_id, genre) for genre, genre_id in genre_ids.items()],
        "movie_genres": movie_genres,
        "ratings": ratings,
        "tags": tags,
    }
