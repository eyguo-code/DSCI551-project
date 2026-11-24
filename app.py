from datetime import date, timedelta
from textwrap import dedent

import pandas as pd
import streamlit as st
from pymysql import MySQLError

from movielens import queries as q
from movielens.db import connect
from movielens.experiment import BENCHMARK_SQL, FORCED_BENCHMARK_SQL, compare


DAY = timedelta(days=1)
SECTIONS = ("Explore", "Rankings", "Rating activity", "Index lab")
INDEX_WINDOWS = {
    "7 days · Jan 2017": (date(2017, 1, 1), date(2017, 1, 8)),
    "1 year · 2017": (date(2017, 1, 1), date(2018, 1, 1)),
    "18 years · 2000–2017": (date(2000, 1, 1), date(2018, 1, 1)),
}
COLUMN_LABELS = {
    "title": "Movie",
    "release_year": "Year",
    "genres": "Genres",
    "tags": "User tags",
    "average_rating": "Average rating",
    "rating_count": "Ratings",
    "genre_name": "Genre",
    "user_id": "User ID",
    "rated_at": "Rated at (UTC)",
    "rating": "Rating",
}


def show_table(rows, empty_message="No results for these filters."):
    if not rows:
        st.info(empty_message)
        return
    frame = pd.DataFrame(rows).drop(columns="movie_id", errors="ignore")
    formats = {}
    if "release_year" in frame:
        frame["release_year"] = frame["release_year"].astype("Int64")
        formats["Year"] = st.column_config.NumberColumn(format="%d")
    if "average_rating" in frame:
        frame["average_rating"] = frame["average_rating"].astype(float)
        formats["Average rating"] = st.column_config.NumberColumn(format="%.3f")
    if "rating" in frame:
        frame["rating"] = frame["rating"].astype(float)
        formats["Rating"] = st.column_config.NumberColumn(format="%.1f")
    if "rated_at" in frame:
        formats["Rated at (UTC)"] = st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss")
    st.dataframe(frame.rename(columns=COLUMN_LABELS), hide_index=True, column_config=formats)


def show_sql(db, *queries):
    with st.expander("SQL queries"), db.cursor() as cursor:
        for label, (sql, params) in queries:
            if label:
                st.caption(label)
            st.code(dedent(cursor.mogrify(sql, params)).strip(), language="sql")


def explore(db):
    st.subheader("Find a movie")
    title_col, genre_col = st.columns([2, 1])
    title = title_col.text_input("Title contains", value="Toy Story", max_chars=255)
    genre = genre_col.selectbox("Genre", ["All genres", *q.genres(db)])
    selected_genre = None if genre == "All genres" else genre
    rows = q.search(db, title, selected_genre)
    show_table(rows, "No titles match this search.")
    if rows:
        st.caption("Up to 50 movies, ordered by title. Blank tag cells mean no tags in this snapshot.")
    show_sql(db, (None, q.search_query(title, selected_genre)))


def rankings(db):
    st.subheader("Movie rankings")
    overall, by_genre, summary = st.tabs(("Overall", "By genre and year", "Genre comparison"))
    with overall:
        minimum = st.number_input("Minimum ratings", min_value=1, value=20, step=1, key="overall_min")
        show_table(q.rankings(db, minimum))
        st.caption("Top 25 by average rating. Ties favor movies with more ratings.")
        show_sql(db, (None, q.rankings_query(minimum)))
    with by_genre:
        first, last = q.year_bounds(db)
        choices = q.genres(db)
        if first is None or not choices:
            st.info("Genre and release-year filters need records with this metadata.")
        else:
            genre_col, count_col = st.columns(2)
            genre = genre_col.selectbox("Genre", choices, index=choices.index("Drama") if "Drama" in choices else 0)
            minimum = count_col.number_input("Minimum ratings", min_value=1, value=20, step=1, key="genre_min")
            default_years = (1990, 1999) if first <= 1990 <= 1999 <= last else (first, last)
            if first == last:
                st.caption(f"Release year {first}")
                year_start, year_stop = first, last
            else:
                year_start, year_stop = st.slider("Release years", min_value=first, max_value=last,
                                                  value=default_years)
            filters = (minimum, genre, year_start, year_stop)
            show_table(q.rankings(db, *filters))
            st.caption("Top 25. Release-year filters exclude movies with an unknown year.")
            with st.expander("How MySQL executes this ranking"):
                if st.button("Run join plan"):
                    st.session_state["ranking_plan"] = (filters, q.ranking_plan(db, *filters))
                saved_plan = st.session_state.get("ranking_plan")
                if saved_plan and saved_plan[0] == filters:
                    st.code(saved_plan[1], language="text", wrap_lines=True)
            show_sql(db, (None, q.rankings_query(*filters)))
    with summary:
        rows = q.genre_stats(db)
        if rows:
            frame = pd.DataFrame(rows)
            st.bar_chart(frame, x="genre_name", y="rating_count", x_label="Genre", y_label="Ratings",
                         sort="-rating_count")
        show_table(rows)
        st.caption("A rating counts once in each of its movie’s genres. Genre totals overlap.")
        show_sql(db, (None, (q.GENRE_STATS_SQL, ())))


def rating_activity(db, stats):
    st.subheader("Rating activity")
    by_date, by_user = st.tabs(("By date", "Most active users"))
    with by_date:
        first, last = stats["first_rating"].date(), stats["last_rating"].date()
        sample = (date(2017, 1, 1), date(2017, 1, 7))
        default_window = sample if first <= sample[0] <= sample[1] <= last else (first, last)
        window = st.date_input("Rating dates (UTC)", default_window, min_value=first, max_value=last)
        if len(window) == 2:
            start, end = window
            stop = end + DAY
            count = q.rating_count(db, start, stop)
            st.caption(f"{count:,} matching ratings. Showing up to 250 in chronological order.")
            show_table(q.rating_activity(db, start, stop), "No ratings in this date range.")
            show_sql(db, ("Matching rating count", q.rating_count_query(start, stop)),
                     ("Rating activity", q.rating_activity_query(start, stop)))
        else:
            st.info("Select a start and end date.")
    with by_user:
        show_table(q.active_users(db))
        st.caption("Top 25 users by ratings submitted. MovieLens uses anonymized user IDs.")
        show_sql(db, (None, q.active_users_query()))


def index_lab(db, stats):
    st.subheader("Test the timestamp index")
    st.write("Compare the baseline plan with a plan that forces the timestamp index for the same date range.")
    window = st.selectbox("Date window (UTC)", list(INDEX_WINDOWS))
    start, stop = INDEX_WINDOWS[window]
    st.caption("The query returns the full matching date range. Timings are medians of five runs and include fetching rows.")
    if st.button("Run MySQL comparison", type="primary", key="run_index"):
        with st.spinner("Running both MySQL plans and timing the queries…"):
            st.session_state["forced_index_result"] = (window, compare(db, start, stop))

    with st.expander("SQL queries"):
        params = (f"'{start}'", f"'{stop}'")
        st.caption("Baseline query")
        st.code(BENCHMARK_SQL % params, language="sql")
        st.caption("Forced index query")
        st.code(FORCED_BENCHMARK_SQL % params, language="sql")
    saved = st.session_state.get("forced_index_result")
    if saved is None or saved[0] != window:
        return

    result = saved[1]
    baseline, candidate = result["baseline"], result["candidate"]
    match_col, baseline_col, candidate_col = st.columns(3)
    match_col.metric("Matching ratings", f"{result['matched']:,}")
    baseline_col.metric("Baseline median", f"{baseline['median_ms']:,.2f} ms")
    candidate_col.metric("Forced index median", f"{candidate['median_ms']:,.2f} ms")
    st.caption(f"The window matches {result['matched'] / stats['ratings']:.2%} of all ratings.")
    if candidate["used_timestamp_index"]:
        st.success("The candidate plan used the timestamp index.")
    else:
        st.warning("The candidate plan did not use the timestamp index.")

    before, after = st.tabs(("Baseline plan", "Forced index plan"))
    with before:
        st.code(baseline["plan"], language="text", wrap_lines=True)
    with after:
        st.code(candidate["plan"], language="text", wrap_lines=True)

    with st.expander("Ratings table indexes"):
        index_columns = ["Key_name", "Seq_in_index", "Column_name", "Visible"]
        indexes = pd.DataFrame(result["indexes"])[index_columns].rename(columns={
            "Key_name": "Index", "Seq_in_index": "Position", "Column_name": "Column", "Visible": "Normally visible",
        })
        st.dataframe(indexes, hide_index=True)


def main():
    st.set_page_config(page_title="MovieLens Analytics", page_icon="🎬", layout="wide")
    st.markdown("""
        <style>
            [data-testid="stAppViewContainer"] {
                background: radial-gradient(ellipse at 90% 0%, #273049 0%, transparent 45%), #11151f;
            }
            .block-container { padding-top: 2.7rem; max-width: 82rem; }
            [data-testid="stMetric"] {
                background: #1b2231;
                border: 1px solid #343d51;
                border-radius: 0.75rem;
                padding: 0.9rem 1.05rem;
            }
            @media (max-width: 760px) {
                .st-key-snapshot_metrics [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
                .st-key-snapshot_metrics [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
                    flex: 1 1 calc(50% - .5rem);
                    min-width: 0;
                    width: calc(50% - .5rem);
                }
            }
        </style>
    """, unsafe_allow_html=True)
    st.title("MovieLens Analytics")
    st.caption("MovieLens latest-small · Historical movie ratings and tags · MySQL")
    try:
        with connect() as db:
            stats = q.overview(db)
            if not stats["ratings"]:
                st.warning("The database is empty. Import the MovieLens snapshot to start the demo.")
                return
            with st.container(key="snapshot_metrics"):
                for column, (label, key) in zip(st.columns(4), (
                    ("Movies", "movies"), ("Ratings", "ratings"), ("Users", "users"), ("Tag applications", "tags"),
                )):
                    column.metric(label, f"{stats[key]:,}")

            section = st.radio("Section", SECTIONS, horizontal=True, label_visibility="collapsed", key="section")
            st.divider()
            if section == "Explore":
                explore(db)
            elif section == "Rankings":
                rankings(db)
            elif section == "Rating activity":
                rating_activity(db, stats)
            else:
                index_lab(db, stats)
    except MySQLError as error:
        code = error.args[0] if error.args else None
        if code in (1044, 1045, 1049, 1146, 2003):
            st.error("Could not open the MovieLens database. Check MySQL and follow the setup in README.md.")
        else:
            st.error(f"MySQL could not complete the operation (error {code}).")
    except ValueError as error:
        st.error(str(error))


if __name__ == "__main__":
    main()
