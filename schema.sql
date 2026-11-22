CREATE TABLE IF NOT EXISTS movies (
    movie_id INT UNSIGNED PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    release_year SMALLINT UNSIGNED
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS users (
    user_id INT UNSIGNED PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS genres (
    genre_id SMALLINT UNSIGNED PRIMARY KEY,
    genre_name VARCHAR(50) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS movie_genres (
    movie_id INT UNSIGNED NOT NULL,
    genre_id SMALLINT UNSIGNED NOT NULL,
    PRIMARY KEY (movie_id, genre_id),
    KEY idx_movie_genres_genre (genre_id, movie_id),
    FOREIGN KEY (movie_id) REFERENCES movies (movie_id),
    FOREIGN KEY (genre_id) REFERENCES genres (genre_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS ratings (
    user_id INT UNSIGNED NOT NULL,
    movie_id INT UNSIGNED NOT NULL,
    rating DECIMAL(2, 1) NOT NULL CHECK (rating BETWEEN 0.5 AND 5.0 AND MOD(rating * 2, 1) = 0),
    rated_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, movie_id),
    KEY idx_ratings_movie (movie_id),
    KEY idx_ratings_rated_at (rated_at) INVISIBLE,
    FOREIGN KEY (user_id) REFERENCES users (user_id),
    FOREIGN KEY (movie_id) REFERENCES movies (movie_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS tags (
    tag_id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id INT UNSIGNED NOT NULL,
    movie_id INT UNSIGNED NOT NULL,
    tag_text VARCHAR(255) NOT NULL,
    tagged_at DATETIME NOT NULL,
    KEY idx_tags_movie (movie_id),
    KEY idx_tags_user (user_id),
    FOREIGN KEY (user_id) REFERENCES users (user_id),
    FOREIGN KEY (movie_id) REFERENCES movies (movie_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
