import json

from .db import select


def overview(db):
    return select(db, """
        SELECT (SELECT COUNT(*) FROM movies) AS movies,
               (SELECT COUNT(*) FROM ratings) AS ratings,
               (SELECT COUNT(*) FROM users) AS users,
               (SELECT COUNT(*) FROM tags) AS tags,
               (SELECT MIN(rated_at) FROM ratings) AS first_rating,
               (SELECT MAX(rated_at) FROM ratings) AS last_rating
    """)[0]


def genres(db):
    return [row["genre_name"] for row in select(db, "SELECT genre_name FROM genres ORDER BY genre_name")]


def year_bounds(db):
    row = select(db, "SELECT MIN(release_year) AS first_year, MAX(release_year) AS last_year FROM movies")[0]
    return row["first_year"], row["last_year"]


def search_query(title, genre=None, limit=50):
    # Escape LIKE wildcards so the user controls only the literal substring.
    literal = title.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return """
        SELECT m.movie_id, m.title, m.release_year,
               (SELECT JSON_ARRAYAGG(g.genre_name)
                FROM movie_genres AS mg JOIN genres AS g USING (genre_id)
                WHERE mg.movie_id = m.movie_id) AS genres,
               (SELECT JSON_ARRAYAGG(t.tag_text)
                FROM tags AS t WHERE t.movie_id = m.movie_id) AS tags
        FROM movies AS m
        WHERE m.title LIKE %s ESCAPE '!'
          AND (%s IS NULL OR EXISTS (
              SELECT 1 FROM movie_genres AS mg JOIN genres AS g USING (genre_id)
              WHERE mg.movie_id = m.movie_id AND g.genre_name = %s
          ))
        ORDER BY m.title, m.movie_id
        LIMIT %s
    """, (f"%{literal}%", genre, genre, limit)


def search(db, title, genre=None, limit=50):
    rows = select(db, *search_query(title, genre, limit))
    for row in rows:
        for field in ("genres", "tags"):
            if row[field] is not None:
                values = json.loads(row[field])
                row[field] = " · ".join(sorted(set(values), key=lambda value: (value.casefold(), value)))
    return rows


RANKINGS_SQL = """
        SELECT m.title, m.release_year, ROUND(AVG(r.rating), 3) AS average_rating,
               COUNT(*) AS rating_count
        FROM movies AS m JOIN ratings AS r USING (movie_id)
        WHERE (%s IS NULL OR EXISTS (
            SELECT 1 FROM movie_genres AS mg JOIN genres AS g USING (genre_id)
            WHERE mg.movie_id = m.movie_id AND g.genre_name = %s
        ))
          AND (%s IS NULL OR m.release_year >= %s)
          AND (%s IS NULL OR m.release_year <= %s)
        GROUP BY m.movie_id, m.title, m.release_year
        HAVING COUNT(*) >= %s
        ORDER BY AVG(r.rating) DESC, COUNT(*) DESC, m.title, m.movie_id
        LIMIT %s
"""


def rankings_query(minimum, genre=None, first_year=None, last_year=None, limit=25):
    return RANKINGS_SQL, (genre, genre, first_year, first_year, last_year, last_year, minimum, limit)


def rankings(db, minimum, genre=None, first_year=None, last_year=None, limit=25):
    return select(db, *rankings_query(minimum, genre, first_year, last_year, limit))


def ranking_plan(db, minimum, genre, first_year, last_year, limit=25):
    sql, params = rankings_query(minimum, genre, first_year, last_year, limit)
    rows = select(db, f"EXPLAIN ANALYZE FORMAT=TREE {sql}", params)
    return "\n".join(next(iter(row.values())) for row in rows)


GENRE_STATS_SQL = """
        SELECT g.genre_name, COUNT(r.rating) AS rating_count,
               ROUND(AVG(r.rating), 3) AS average_rating
        FROM genres AS g
        JOIN movie_genres AS mg USING (genre_id)
        LEFT JOIN ratings AS r USING (movie_id)
        GROUP BY g.genre_id, g.genre_name
        ORDER BY rating_count DESC, g.genre_name
"""


def genre_stats(db):
    return select(db, GENRE_STATS_SQL)


def active_users_query(limit=25):
    return """
        SELECT user_id, COUNT(*) AS rating_count, ROUND(AVG(rating), 3) AS average_rating
        FROM ratings
        GROUP BY user_id
        ORDER BY rating_count DESC, user_id
        LIMIT %s
    """, (limit,)


def active_users(db, limit=25):
    return select(db, *active_users_query(limit))


DATE_FILTER = "r.rated_at >= %s AND r.rated_at < %s"
DATE_ORDER = "r.rated_at, r.user_id, r.movie_id"


def rating_count_query(start, stop):
    return f"SELECT COUNT(*) AS matches FROM ratings AS r WHERE {DATE_FILTER}", (start, stop)


def rating_count(db, start, stop):
    return select(db, *rating_count_query(start, stop))[0]["matches"]


def rating_activity_query(start, stop, limit=250):
    return f"""
        SELECT r.rated_at, r.user_id, m.title, r.rating
        FROM ratings AS r JOIN movies AS m USING (movie_id)
        WHERE {DATE_FILTER}
        ORDER BY {DATE_ORDER}
        LIMIT %s
    """, (start, stop, limit)


def rating_activity(db, start, stop, limit=250):
    return select(db, *rating_activity_query(start, stop, limit))
