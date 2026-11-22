import os

import pymysql
from pymysql.cursors import DictCursor


def connect():
    return pymysql.connect(
        host=os.getenv("MOVIELENS_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("MOVIELENS_DB_PORT", "3306")),
        user=os.getenv("MOVIELENS_DB_USER", "movielens"),
        password=os.getenv("MOVIELENS_DB_PASSWORD", ""),
        database=os.getenv("MOVIELENS_DB_NAME", "movielens_demo"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=5,
        read_timeout=45,
        write_timeout=45,
    )


def select(db, sql, params=()):
    with db.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() or []
