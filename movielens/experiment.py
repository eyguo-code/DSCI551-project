from statistics import median
from time import perf_counter

from .db import select
from .queries import DATE_FILTER, DATE_ORDER


INDEX_NAME = "idx_ratings_rated_at"
BENCHMARK_SQL = (
    "SELECT r.user_id, r.movie_id, r.rating, r.rated_at\n"
    "FROM ratings AS r\n"
    f"WHERE {DATE_FILTER}\n"
    f"ORDER BY {DATE_ORDER}"
)


def compare(db, start, stop, repeats=5):
    """Compare the same MySQL query with and without an eligible timestamp index."""
    if start >= stop or repeats < 1:
        raise ValueError("Use a nonempty date window and at least one timing run.")

    indexes = select(db, "SHOW INDEX FROM ratings")
    invisible = {row["Key_name"] for row in indexes if row["Visible"] == "NO"}
    if invisible != {INDEX_NAME}:
        raise ValueError(f"Expected {INDEX_NAME} to be the only invisible index on ratings.")

    original = select(db, "SELECT @@SESSION.optimizer_switch AS options")[0]["options"]
    params = (start, stop)
    switches = {"baseline": "off", "candidate": "on"}
    result = {mode: {"samples": []} for mode in switches}
    with db.cursor() as cursor:
        def set_mode(mode):
            cursor.execute("SET SESSION optimizer_switch = %s", (f"use_invisible_indexes={switches[mode]}",))

        try:
            warmup_rows = {}
            for mode in switches:
                set_mode(mode)
                warmup_rows[mode] = select(db, BENCHMARK_SQL, params)
                plan = select(db, f"EXPLAIN ANALYZE FORMAT=TREE {BENCHMARK_SQL}", params)
                result[mode]["plan"] = "\n".join(next(iter(row.values())) for row in plan)

            if warmup_rows["baseline"] != warmup_rows["candidate"]:
                raise ValueError("The experiment returned different rows. Check for concurrent writes and retry.")
            result["matched"] = len(warmup_rows["baseline"])
            for mode in switches:
                result[mode]["used_timestamp_index"] = INDEX_NAME in result[mode]["plan"]

            for attempt in range(repeats):
                order = tuple(switches) if attempt % 2 == 0 else tuple(reversed(switches))
                for mode in order:
                    set_mode(mode)
                    started = perf_counter()
                    select(db, BENCHMARK_SQL, params)
                    result[mode]["samples"].append((perf_counter() - started) * 1000)
        finally:
            cursor.execute("SET SESSION optimizer_switch = %s", (original,))

    for mode in switches:
        result[mode]["median_ms"] = median(result[mode]["samples"])
    result["indexes"] = indexes
    return result
