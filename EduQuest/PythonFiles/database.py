

import os
import json
import sqlite3
from datetime import datetime

# Path to the database file lives inside the DB folder of the project root.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "DB", "eduquest.db")


# ===== Level & rating math =====
XP_PER_LEVEL = 100  # base value, kept for compatibility
XP_PER_COMPLETION = 50
RATING_PER_COMPLETION = 25
RATING_PER_CREATION = 100


def xp_for_level(level):
    """Return total XP needed to reach a given level from level 0.

    Level 0→1: 100 XP, 1→2: 200 XP, 2→3: 300 XP … N→N+1: (N+1)*100 XP.
    Total XP for level L = sum_{k=1}^{L} k*100 = 100 * L*(L+1)/2.

    Users start at level 0 with 0 XP.
    """
    if level <= 0:
        return 0
    return int(100 * level * (level + 1) / 2)


def compute_level(xp):
    if xp is None or xp < 0:
        return 0
    level = 0
    while xp_for_level(level + 1) <= xp:
        level += 1
    return level


def compute_xp_in_level(xp):
    """Return how much XP the user has within the current level."""
    if xp is None or xp < 0:
        return 0
    level = compute_level(xp)
    return int(xp - xp_for_level(level))


def compute_xp_for_next_level(xp):
    """Return XP required for the next level."""
    level = compute_level(xp or 0)
    return xp_for_level(level + 1) - xp_for_level(level)


def compute_rating(xp, completed_count, created_count):
    """Composite rating used for ranking the leaderboard."""
    return int((xp or 0) + (completed_count or 0) * RATING_PER_COMPLETION + (created_count or 0) * RATING_PER_CREATION)


def get_connection():
    """Open a new SQLite connection with row access by column name."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all required tables if they do not exist yet."""
    conn = get_connection()
    cur = conn.cursor()

    # Users
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_full_name     TEXT NOT NULL,
            user_email         TEXT NOT NULL UNIQUE,
            user_password_hash TEXT NOT NULL,
            user_avatar_path   TEXT,
            user_xp            INTEGER NOT NULL DEFAULT 0,
            user_streak_days   INTEGER NOT NULL DEFAULT 0,
            user_educoins      INTEGER NOT NULL DEFAULT 0,
            user_role          TEXT NOT NULL DEFAULT 'user',
            user_created_at    TEXT NOT NULL
        )
        """
    )

    # Categories (with optional parent for sub-categories)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            category_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            category_slug      TEXT NOT NULL UNIQUE,
            category_name      TEXT NOT NULL,
            category_parent_id INTEGER,
            FOREIGN KEY (category_parent_id) REFERENCES categories(category_id)
        )
        """
    )

    # Materials
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS materials (
            material_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            material_title           TEXT NOT NULL,
            material_description     TEXT NOT NULL DEFAULT '',
            material_type            TEXT NOT NULL,
            material_category_id     INTEGER,
            material_subcategory_id  INTEGER,
            material_difficulty      TEXT NOT NULL DEFAULT 'beginner',
            material_content         TEXT NOT NULL DEFAULT '',
            material_image_path      TEXT,
            material_youtube_url     TEXT,
            material_steps_json      TEXT NOT NULL DEFAULT '[]',
            material_author_id       INTEGER NOT NULL,
            material_views           INTEGER NOT NULL DEFAULT 0,
            material_status          TEXT NOT NULL DEFAULT 'pending',
            material_created_at      TEXT NOT NULL,
            FOREIGN KEY (material_author_id) REFERENCES users(user_id),
            FOREIGN KEY (material_category_id) REFERENCES categories(category_id),
            FOREIGN KEY (material_subcategory_id) REFERENCES categories(category_id)
        )
        """
    )

    # Per-user view log (one row per (user, material))
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS material_views_log (
            view_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            view_user_id      INTEGER NOT NULL,
            view_material_id  INTEGER NOT NULL,
            view_created_at   TEXT NOT NULL,
            UNIQUE(view_user_id, view_material_id),
            FOREIGN KEY (view_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (view_material_id) REFERENCES materials(material_id) ON DELETE CASCADE
        )
        """
    )

    # Per-user 5-star ratings
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS material_ratings (
            rating_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rating_user_id     INTEGER NOT NULL,
            rating_material_id INTEGER NOT NULL,
            rating_value       INTEGER NOT NULL,
            rating_created_at  TEXT NOT NULL,
            UNIQUE(rating_user_id, rating_material_id),
            FOREIGN KEY (rating_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (rating_material_id) REFERENCES materials(material_id) ON DELETE CASCADE
        )
        """
    )

    # Comments
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS comments (
            comment_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_material_id  INTEGER NOT NULL,
            comment_user_id      INTEGER NOT NULL,
            comment_text         TEXT NOT NULL,
            comment_created_at   TEXT NOT NULL,
            FOREIGN KEY (comment_material_id) REFERENCES materials(material_id) ON DELETE CASCADE,
            FOREIGN KEY (comment_user_id) REFERENCES users(user_id)
        )
        """
    )

    # Comment likes
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS comment_likes (
            like_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            like_comment_id  INTEGER NOT NULL,
            like_user_id     INTEGER NOT NULL,
            UNIQUE(like_comment_id, like_user_id),
            FOREIGN KEY (like_comment_id) REFERENCES comments(comment_id) ON DELETE CASCADE,
            FOREIGN KEY (like_user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
        """
    )

    # Comment dislikes
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS comment_dislikes (
            dislike_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            dislike_comment_id  INTEGER NOT NULL,
            dislike_user_id     INTEGER NOT NULL,
            UNIQUE(dislike_comment_id, dislike_user_id),
            FOREIGN KEY (dislike_comment_id) REFERENCES comments(comment_id) ON DELETE CASCADE,
            FOREIGN KEY (dislike_user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
        """
    )

    # Achievements catalog
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS achievements (
            achievement_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            achievement_code        TEXT NOT NULL UNIQUE,
            achievement_name        TEXT NOT NULL,
            achievement_description TEXT NOT NULL,
            achievement_icon        TEXT NOT NULL,
            achievement_color       TEXT NOT NULL DEFAULT 'green',
            achievement_order       INTEGER NOT NULL DEFAULT 0,
            achievement_requirement INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # User <-> achievements
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_achievements (
            ua_id             INTEGER PRIMARY KEY AUTOINCREMENT,
            ua_user_id        INTEGER NOT NULL,
            ua_achievement_id INTEGER NOT NULL,
            ua_earned_at      TEXT NOT NULL,
            UNIQUE(ua_user_id, ua_achievement_id),
            FOREIGN KEY (ua_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (ua_achievement_id) REFERENCES achievements(achievement_id) ON DELETE CASCADE
        )
        """
    )

    # Badges catalog
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS badges (
            badge_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            badge_code        TEXT NOT NULL UNIQUE,
            badge_name        TEXT NOT NULL,
            badge_description TEXT NOT NULL,
            badge_icon        TEXT NOT NULL,
            badge_order       INTEGER NOT NULL DEFAULT 0,
            badge_requirement INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # User <-> badges
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_badges (
            ub_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ub_user_id   INTEGER NOT NULL,
            ub_badge_id  INTEGER NOT NULL,
            ub_earned_at TEXT NOT NULL,
            UNIQUE(ub_user_id, ub_badge_id),
            FOREIGN KEY (ub_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (ub_badge_id) REFERENCES badges(badge_id) ON DELETE CASCADE
        )
        """
    )

    # Material progress (per user) — tracks current step and completion
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS material_progress (
            progress_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            progress_user_id      INTEGER NOT NULL,
            progress_material_id  INTEGER NOT NULL,
            progress_started      INTEGER NOT NULL DEFAULT 0,
            progress_step         INTEGER NOT NULL DEFAULT 0,
            progress_completed    INTEGER NOT NULL DEFAULT 0,
            progress_updated_at   TEXT NOT NULL,
            UNIQUE(progress_user_id, progress_material_id),
            FOREIGN KEY (progress_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (progress_material_id) REFERENCES materials(material_id) ON DELETE CASCADE
        )
        """
    )

    # Activity log (recent activity on profile)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_log (
            activity_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_user_id    INTEGER NOT NULL,
            activity_type       TEXT NOT NULL,
            activity_text       TEXT NOT NULL,
            activity_icon       TEXT NOT NULL DEFAULT 'star',
            activity_created_at TEXT NOT NULL,
            FOREIGN KEY (activity_user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
        """
    )

    # Shop items (frames, themes, badges)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_items (
            item_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type        TEXT NOT NULL,
            item_code        TEXT NOT NULL UNIQUE,
            item_name        TEXT NOT NULL,
            item_description TEXT NOT NULL,
            item_price       INTEGER NOT NULL,
            item_data        TEXT NOT NULL DEFAULT '{}',
            item_order       INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # User purchases
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_purchases (
            purchase_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_user_id INTEGER NOT NULL,
            purchase_item_id INTEGER NOT NULL,
            purchase_date    TEXT NOT NULL,
            UNIQUE(purchase_user_id, purchase_item_id),
            FOREIGN KEY (purchase_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (purchase_item_id) REFERENCES shop_items(item_id) ON DELETE CASCADE
        )
        """
    )

    # User settings
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            setting_id                INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_user_id           INTEGER NOT NULL UNIQUE,
            setting_theme             TEXT NOT NULL DEFAULT 'light',
            setting_language          TEXT NOT NULL DEFAULT 'ru',
            setting_notifications     INTEGER NOT NULL DEFAULT 1,
            setting_confetti          INTEGER NOT NULL DEFAULT 1,
            setting_hide_avatar       INTEGER NOT NULL DEFAULT 0,
            setting_hide_achievements INTEGER NOT NULL DEFAULT 0,
            setting_hide_badges       INTEGER NOT NULL DEFAULT 0,
            setting_hide_streak       INTEGER NOT NULL DEFAULT 0,
            setting_hide_stats        INTEGER NOT NULL DEFAULT 0,
            setting_hide_leaderboard  INTEGER NOT NULL DEFAULT 0,
            setting_hide_profile      INTEGER NOT NULL DEFAULT 0,
            setting_active_frame      TEXT,
            setting_active_theme      TEXT,
            setting_active_badge      TEXT,
            setting_active_earned_badge TEXT,
            setting_showcase_ach      TEXT,
            setting_showcase_badges   TEXT,
            FOREIGN KEY (setting_user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
        """
    )

    conn.commit()

    # --- Migrations: add columns if missing ---
    _migrate_add_column(conn, "users", "user_role", "TEXT NOT NULL DEFAULT 'user'")
    _migrate_add_column(conn, "materials", "material_status", "TEXT NOT NULL DEFAULT 'approved'")
    _migrate_add_column(conn, "user_settings", "setting_active_earned_badge", "TEXT")
    _migrate_add_column(conn, "user_settings", "setting_disable_all_notifications", "INTEGER NOT NULL DEFAULT 0")
    _migrate_add_column(conn, "user_settings", "setting_hide_level", "INTEGER NOT NULL DEFAULT 0")
    _migrate_add_column(conn, "user_settings", "setting_hide_xp", "INTEGER NOT NULL DEFAULT 0")
    _migrate_add_column(conn, "materials", "material_xp_reward", "INTEGER NOT NULL DEFAULT 0")
    _migrate_add_column(conn, "materials", "material_backup_json", "TEXT")

    seed_static_data(conn)
    conn.close()


# Three top-level categories with sub-categories.
DEFAULT_CATEGORY_TREE = [
    ("knowledge", "Знания", [
        ("math",         "Математика"),
        ("programming",  "Программирование"),
        ("science",      "Наука"),
        ("languages",    "Иностранные языки"),
        ("business",     "Бизнес"),
    ]),
    ("skills", "Навыки", [
        ("design",       "Дизайн"),
        ("cooking",      "Кулинария"),
        ("photo-video",  "Фото и видео"),
        ("life-skills",  "Бытовые навыки"),
        ("music",        "Музыка"),
    ]),
    ("development", "Развитие", [
        ("health",            "Здоровье"),
        ("sport",             "Спорт"),
        ("creativity",        "Творчество"),
        ("self-development",  "Саморазвитие"),
    ]),
]

# 12 generic, platform-wide achievements.
DEFAULT_ACHIEVEMENTS = [
    ("first_steps",     "Первые шаги",        "Завершите свой первый материал",          "book",     "green",   1),
    ("ten_done",        "Уверенный учащийся", "Завершите 10 материалов",                 "medal",    "blue",    2),
    ("fifty_done",      "Эксперт",            "Завершите 50 материалов",                 "award",    "purple",  3),
    ("author",          "Автор",              "Опубликуйте свой первый материал",        "edit",     "blue",    4),
    ("mentor",          "Наставник",          "Создайте 5 обучающих материалов",         "users",    "purple",  5),
    ("knowledge_keeper","Хранитель знаний",   "Создайте 20 обучающих материалов",        "shield",   "",        6),
    ("focused",         "Целеустремлённый",   "Поддерживайте серию 7 дней",              "target",   "blue",    7),
    ("marathoner",      "Марафонец",          "Поддерживайте серию 30 дней",             "flag",     "purple",  8),
    ("commenter",       "Активный участник",  "Оставьте 25 комментариев",                "message",  "green",   9),
    ("rising_star",     "Восходящая звезда",  "Достигните уровня 5",                     "star",     "blue",    10),
    ("legend",          "Легенда",            "Достигните уровня 20",                    "crown",    "",        11),
    ("champion",        "Чемпион",            "Войдите в топ-10 рейтинга",               "trophy",   "",        12),
]

# 9 generic, platform-wide badges.
DEFAULT_BADGES = [
    ("novice",    "Новичок",            "Достигните уровня 3",                "spark",    1),
    ("apprentice","Ученик",             "Достигните уровня 10",               "graduate", 2),
    ("master",    "Мастер",             "Достигните уровня 25",               "crown",    3),
    ("learner_5", "Любознательный",     "Завершите 5 материалов",             "book",     4),
    ("learner_25","Знаток",             "Завершите 25 материалов",            "library",  5),
    ("creator_3", "Создатель",          "Создайте 3 материала",               "pen",      6),
    ("creator_15","Производитель",      "Создайте 15 материалов",             "factory",  7),
    ("streak_3",  "Стартовый темп",     "Серия 3 дня",                        "zap",      8),
    ("streak_14", "Постоянство",        "Серия 14 дней",                      "flame",    9),
]


def seed_static_data(conn):
    """Insert default categories, achievements and badges if missing."""
    cur = conn.cursor()

    # Categories tree
    cur.execute("SELECT COUNT(*) AS c FROM categories")
    if cur.fetchone()["c"] == 0:
        for slug, name, subs in DEFAULT_CATEGORY_TREE:
            cur.execute(
                "INSERT INTO categories (category_slug, category_name, category_parent_id) VALUES (?, ?, NULL)",
                (slug, name),
            )
            parent_id = cur.lastrowid
            for sub_slug, sub_name in subs:
                cur.execute(
                    "INSERT INTO categories (category_slug, category_name, category_parent_id) VALUES (?, ?, ?)",
                    (sub_slug, sub_name, parent_id),
                )

    # Achievements: replace catalog every start so updates roll out.
    cur.execute("SELECT COUNT(*) AS c FROM achievements")
    if cur.fetchone()["c"] == 0:
        cur.executemany(
            """INSERT INTO achievements
               (achievement_code, achievement_name, achievement_description,
                achievement_icon, achievement_color, achievement_order)
               VALUES (?, ?, ?, ?, ?, ?)""",
            DEFAULT_ACHIEVEMENTS,
        )

    cur.execute("SELECT COUNT(*) AS c FROM badges")
    if cur.fetchone()["c"] == 0:
        cur.executemany(
            """INSERT INTO badges (badge_code, badge_name, badge_description, badge_icon, badge_order)
               VALUES (?, ?, ?, ?, ?)""",
            DEFAULT_BADGES,
        )

    # Shop items
    cur.execute("SELECT COUNT(*) AS c FROM shop_items")
    if cur.fetchone()["c"] == 0:
        shop_items = [
            # Frames (type, code, name, description, price, data, order)
            ("frame", "frame_gold", "Золотая рамка", "Элегантная золотая обводка", 2, '{"color":"#FFD700"}', 1),
            ("frame", "frame_silver", "Серебряная рамка", "Стильная серебряная обводка", 1, '{"color":"#C0C0C0"}', 2),
            ("frame", "frame_bronze", "Бронзовая рамка", "Классическая бронзовая обводка", 1, '{"color":"#CD7F32"}', 3),
            ("frame", "frame_rainbow", "Радужная рамка", "Яркая радужная обводка", 3, '{"gradient":"linear-gradient(45deg, red, orange, yellow, green, blue, indigo, violet)"}', 4),
            ("frame", "frame_fire", "Огненная рамка", "Пылающая красно-оранжевая обводка", 3, '{"gradient":"linear-gradient(45deg, #ff0000, #ff7f00)"}', 5),
            ("frame", "frame_ice", "Ледяная рамка", "Холодная сине-голубая обводка", 3, '{"gradient":"linear-gradient(45deg, #00bfff, #87ceeb)"}', 6),
            ("frame", "frame_neon", "Неоновая рамка", "Светящаяся неоновая обводка", 4, '{"color":"#39FF14","glow":"0 0 10px #39FF14"}', 7),
            ("frame", "frame_galaxy", "Галактическая рамка", "Космическая обводка", 5, '{"gradient":"linear-gradient(45deg, #1a1a2e, #16213e, #0f3460)"}', 8),
            ("frame", "frame_emerald", "Изумрудная рамка", "Роскошная зелёная обводка", 4, '{"color":"#50C878"}', 9),
            ("frame", "frame_royal", "Королевская рамка", "Величественная фиолетовая обводка", 5, '{"gradient":"linear-gradient(45deg, #6a0dad, #9370db)"}', 10),

            # Profile themes
            ("theme", "theme_sunset", "Закат", "Тёплые оранжево-розовые тона", 3, '{"bg":"linear-gradient(135deg, #ff6b6b, #feca57)","panel":"rgba(255,255,255,0.9)"}', 1),
            ("theme", "theme_ocean", "Океан", "Глубокие сине-бирюзовые тона", 3, '{"bg":"linear-gradient(135deg, #667eea, #764ba2)","panel":"rgba(255,255,255,0.9)"}', 2),
            ("theme", "theme_forest", "Лес", "Свежие зелёные тона", 2, '{"bg":"linear-gradient(135deg, #11998e, #38ef7d)","panel":"rgba(255,255,255,0.9)"}', 3),
            ("theme", "theme_night", "Ночь", "Тёмные звёздные тона", 4, '{"bg":"linear-gradient(135deg, #0f2027, #203a43, #2c5364)","panel":"rgba(30,30,30,0.9)","text":"#ffffff"}', 4),
            ("theme", "theme_cherry", "Вишня", "Нежные розовые тона", 3, '{"bg":"linear-gradient(135deg, #f093fb, #f5576c)","panel":"rgba(255,255,255,0.9)"}', 5),
            ("theme", "theme_mint", "Мята", "Освежающие мятные тона", 2, '{"bg":"linear-gradient(135deg, #4facfe, #00f2fe)","panel":"rgba(255,255,255,0.9)"}', 6),
            ("theme", "theme_autumn", "Осень", "Тёплые осенние тона", 3, '{"bg":"linear-gradient(135deg, #fa709a, #fee140)","panel":"rgba(255,255,255,0.9)"}', 7),
            ("theme", "theme_lavender", "Лаванда", "Спокойные фиолетовые тона", 4, '{"bg":"linear-gradient(135deg, #a8edea, #fed6e3)","panel":"rgba(255,255,255,0.9)"}', 8),
            ("theme", "theme_gold", "Золото", "Роскошные золотые тона", 5, '{"bg":"linear-gradient(135deg, #f7971e, #ffd200)","panel":"rgba(255,255,255,0.9)"}', 9),
            ("theme", "theme_cosmic", "Космос", "Галактические тона", 6, '{"bg":"linear-gradient(135deg, #1e3c72, #2a5298, #7e22ce)","panel":"rgba(20,20,40,0.9)","text":"#ffffff"}', 10),

            # Special badges
            ("badge", "badge_star", "Звезда", "Значок звезды возле ника", 1, '{"icon":"⭐"}', 1),
            ("badge", "badge_fire", "Огонь", "Значок огня возле ника", 2, '{"icon":"🔥"}', 2),
            ("badge", "badge_crown", "Корона", "Значок короны возле ника", 3, '{"icon":"👑"}', 3),
            ("badge", "badge_gem", "Алмаз", "Значок алмаза возле ника", 3, '{"icon":"💎"}', 4),
            ("badge", "badge_rocket", "Ракета", "Значок ракеты возле ника", 2, '{"icon":"🚀"}', 5),
            ("badge", "badge_trophy", "Трофей", "Значок трофея возле ника", 4, '{"icon":"🏆"}', 6),
            ("badge", "badge_lightning", "Молния", "Значок молнии возле ника", 3, '{"icon":"⚡"}', 7),
            ("badge", "badge_heart", "Сердце", "Значок сердца возле ника", 2, '{"icon":"❤️"}', 8),
            ("badge", "badge_rainbow", "Радуга", "Флаг ЛГБТ возле ника", 1, '{"icon":"🏳️‍🌈"}', 9),
            ("badge", "badge_wizard", "Волшебник", "Значок волшебника возле ника", 5, '{"icon":"🧙"}', 10),
        ]
        cur.executemany(
            """INSERT INTO shop_items (item_type, item_code, item_name, item_description, item_price, item_data, item_order)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            shop_items,
        )

    conn.commit()

    # Ensure moderator account exists
    _seed_moderator(conn)


def _migrate_add_column(conn, table, column, col_type):
    """Add a column to a table if it doesn't exist yet."""
    cur = conn.cursor()
    cols = [row[1] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()


def _seed_moderator(conn):
    """Create the default moderator account if it doesn't exist."""
    from werkzeug.security import generate_password_hash
    cur = conn.cursor()
    row = cur.execute("SELECT user_id FROM users WHERE user_email = ?", ('mrmcrizzatu@mail.ru',)).fetchone()
    if not row:
        cur.execute(
            """INSERT INTO users (user_full_name, user_email, user_password_hash, user_role, user_created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ('Модератор', 'mrmcrizzatu@mail.ru', generate_password_hash('admin'), 'moderator', now_iso()),
        )
        conn.commit()
    else:
        # Ensure existing account has moderator role
        cur.execute("UPDATE users SET user_role = 'moderator' WHERE user_email = ?", ('mrmcrizzatu@mail.ru',))
        conn.commit()


# ===== Helpers =====
def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")


def fetch_top_categories():
    """Return top-level categories (parent IS NULL)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT category_id, category_slug, category_name
           FROM categories
           WHERE category_parent_id IS NULL
           ORDER BY category_id"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_subcategories(parent_slug=None, parent_id=None):
    """Return sub-categories of a given parent (by slug or id)."""
    conn = get_connection()
    if parent_id is None and parent_slug:
        row = conn.execute(
            "SELECT category_id FROM categories WHERE category_slug = ?", (parent_slug,)
        ).fetchone()
        if not row:
            conn.close()
            return []
        parent_id = row["category_id"]
    if parent_id is None:
        conn.close()
        return []
    rows = conn.execute(
        """SELECT category_id, category_slug, category_name, category_parent_id
           FROM categories
           WHERE category_parent_id = ?
           ORDER BY category_name""",
        (parent_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_category_by_slug(slug):
    if not slug:
        return None
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM categories WHERE category_slug = ?", (slug,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def fetch_user_by_email(email):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE user_email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def fetch_user_by_id(user_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(full_name, email, password_hash):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO users (user_full_name, user_email, user_password_hash, user_created_at)
           VALUES (?, ?, ?, ?)""",
        (full_name, email, password_hash, now_iso()),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def update_user_name(user_id, new_name):
    conn = get_connection()
    conn.execute(
        "UPDATE users SET user_full_name = ? WHERE user_id = ?",
        (new_name, user_id),
    )
    conn.commit()
    conn.close()


def update_user_email(user_id, new_email):
    conn = get_connection()
    conn.execute(
        "UPDATE users SET user_email = ? WHERE user_id = ?",
        (new_email, user_id),
    )
    conn.commit()
    conn.close()


def update_user_password(user_id, new_password_hash):
    conn = get_connection()
    conn.execute(
        "UPDATE users SET user_password_hash = ? WHERE user_id = ?",
        (new_password_hash, user_id),
    )
    conn.commit()
    conn.close()


def update_user_avatar(user_id, avatar_path):
    conn = get_connection()
    conn.execute(
        "UPDATE users SET user_avatar_path = ? WHERE user_id = ?",
        (avatar_path, user_id),
    )
    conn.commit()
    conn.close()


def add_user_xp(user_id, amount):
    """Increase XP and return new totals and level_up info."""
    conn = get_connection()
    old_xp = conn.execute(
        "SELECT user_xp FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    old_xp_val = old_xp["user_xp"] if old_xp else 0

    conn.execute(
        "UPDATE users SET user_xp = user_xp + ? WHERE user_id = ?",
        (int(amount), user_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT user_xp FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    new_xp = row["user_xp"] if row else 0
    conn.close()

    new_level = check_level_rewards(user_id, old_xp_val, new_xp)
    return {"xp": new_xp, "level_up": new_level}


def fetch_materials(top_category_slug=None, sub_category_slug=None, sort="trending", search=None, author_id=None):
    """List materials with filters."""
    conn = get_connection()
    sql = """
        SELECT
            m.material_id,
            m.material_title,
            m.material_description,
            m.material_type,
            m.material_difficulty,
            m.material_image_path,
            m.material_youtube_url,
            m.material_views,
            m.material_created_at,
            u.user_id          AS author_id,
            u.user_full_name   AS author_name,
            u.user_avatar_path AS author_avatar,
            cs.category_slug   AS sub_slug,
            cs.category_name   AS sub_name,
            ct.category_slug   AS top_slug,
            ct.category_name   AS top_name,
            (SELECT AVG(rating_value) FROM material_ratings r WHERE r.rating_material_id = m.material_id) AS avg_rating,
            (SELECT COUNT(*)        FROM material_ratings r WHERE r.rating_material_id = m.material_id) AS rating_count
        FROM materials m
        JOIN users u ON u.user_id = m.material_author_id
        LEFT JOIN categories cs ON cs.category_id = m.material_subcategory_id
        LEFT JOIN categories ct ON ct.category_id = m.material_category_id
        WHERE m.material_status = 'approved'
    """
    params = []
    if top_category_slug:
        sql += " AND ct.category_slug = ?"
        params.append(top_category_slug)
    if sub_category_slug:
        sql += " AND cs.category_slug = ?"
        params.append(sub_category_slug)
    if author_id:
        sql += " AND m.material_author_id = ?"
        params.append(author_id)
    if search:
        sql += """ AND (
            m.material_title LIKE ? OR
            m.material_description LIKE ? OR
            u.user_full_name LIKE ?
        )"""
        like = f"%{search}%"
        params.extend([like, like, like])

    if sort == "new":
        sql += " ORDER BY m.material_created_at DESC"
    elif sort == "rating":
        sql += " ORDER BY avg_rating DESC NULLS LAST, m.material_views DESC"
    elif sort == "old":
        sql += " ORDER BY m.material_created_at ASC"
    else:
        sql += " ORDER BY m.material_views DESC, m.material_created_at DESC"

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_material(material_id):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT m.*,
               u.user_full_name   AS author_name,
               u.user_avatar_path AS author_avatar,
               cs.category_name   AS sub_name,
               cs.category_slug   AS sub_slug,
               ct.category_name   AS top_name,
               ct.category_slug   AS top_slug,
               (SELECT AVG(rating_value) FROM material_ratings r WHERE r.rating_material_id = m.material_id) AS avg_rating,
               (SELECT COUNT(*)        FROM material_ratings r WHERE r.rating_material_id = m.material_id) AS rating_count
        FROM materials m
        JOIN users u ON u.user_id = m.material_author_id
        LEFT JOIN categories cs ON cs.category_id = m.material_subcategory_id
        LEFT JOIN categories ct ON ct.category_id = m.material_category_id
        WHERE m.material_id = ?
        """,
        (material_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def fetch_material_steps(material_id):
    """Fetch steps for a material from material_steps_json."""
    material = fetch_material(material_id)
    if not material:
        return []
    try:
        steps_json = material.get("material_steps_json", "[]")
        return json.loads(steps_json) if steps_json else []
    except Exception:
        return []


def register_view(user_id, material_id):
    """Record a unique view; increment material_views only the first time.

    If user_id is None (anonymous), just increment views.
    """
    conn = get_connection()
    cur = conn.cursor()
    if user_id:
        existing = cur.execute(
            "SELECT view_id FROM material_views_log WHERE view_user_id = ? AND view_material_id = ?",
            (user_id, material_id),
        ).fetchone()
        if existing:
            conn.close()
            return False
        cur.execute(
            """INSERT INTO material_views_log (view_user_id, view_material_id, view_created_at)
               VALUES (?, ?, ?)""",
            (user_id, material_id, now_iso()),
        )
        cur.execute(
            "UPDATE materials SET material_views = material_views + 1 WHERE material_id = ?",
            (material_id,),
        )
        conn.commit()
        conn.close()
        return True
    cur.execute(
        "UPDATE materials SET material_views = material_views + 1 WHERE material_id = ?",
        (material_id,),
    )
    conn.commit()
    conn.close()
    return True


def create_material(data):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO materials
           (material_title, material_description, material_type, material_category_id, material_subcategory_id,
            material_difficulty, material_content, material_image_path, material_youtube_url,
            material_steps_json, material_author_id, material_status, material_created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["title"],
            data.get("description", ""),
            data["type"],
            data.get("category_id"),
            data.get("subcategory_id"),
            data.get("difficulty", "beginner"),
            data.get("content", ""),
            data.get("image_path"),
            data.get("youtube_url"),
            data.get("steps_json", "[]"),
            data["author_id"],
            data.get("status", "pending"),
            now_iso(),
        ),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def update_material(material_id, data):
    conn = get_connection()
    fields = [
        "material_title = ?",
        "material_description = ?",
        "material_type = ?",
        "material_category_id = ?",
        "material_subcategory_id = ?",
        "material_difficulty = ?",
        "material_content = ?",
        "material_youtube_url = ?",
        "material_steps_json = ?",
    ]
    params = [
        data["title"],
        data.get("description", ""),
        data["type"],
        data.get("category_id"),
        data.get("subcategory_id"),
        data.get("difficulty", "beginner"),
        data.get("content", ""),
        data.get("youtube_url"),
        data.get("steps_json", "[]"),
    ]
    if "image_path" in data and data["image_path"] is not None:
        fields.append("material_image_path = ?")
        params.append(data["image_path"])
    if "status" in data:
        fields.append("material_status = ?")
        params.append(data["status"])
    if "backup_json" in data:
        fields.append("material_backup_json = ?")
        params.append(data["backup_json"])
    params.append(material_id)
    conn.execute(
        f"UPDATE materials SET {', '.join(fields)} WHERE material_id = ?", params
    )
    conn.commit()
    conn.close()


def delete_material(material_id):
    conn = get_connection()
    conn.execute("DELETE FROM materials WHERE material_id = ?", (material_id,))
    conn.commit()
    conn.close()


# ===== Ratings =====
def upsert_rating(user_id, material_id, value):
    value = max(1, min(5, int(value)))
    conn = get_connection()
    cur = conn.cursor()
    existing = cur.execute(
        "SELECT rating_id FROM material_ratings WHERE rating_user_id = ? AND rating_material_id = ?",
        (user_id, material_id),
    ).fetchone()
    if existing:
        cur.execute(
            "UPDATE material_ratings SET rating_value = ?, rating_created_at = ? WHERE rating_id = ?",
            (value, now_iso(), existing["rating_id"]),
        )
    else:
        cur.execute(
            """INSERT INTO material_ratings
               (rating_user_id, rating_material_id, rating_value, rating_created_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, material_id, value, now_iso()),
        )
    conn.commit()
    conn.close()


def fetch_user_rating_for(user_id, material_id):
    if not user_id:
        return 0
    conn = get_connection()
    row = conn.execute(
        "SELECT rating_value FROM material_ratings WHERE rating_user_id = ? AND rating_material_id = ?",
        (user_id, material_id),
    ).fetchone()
    conn.close()
    return row["rating_value"] if row else 0


# ===== Comments =====
def fetch_comments_for(material_id):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT c.comment_id, c.comment_text, c.comment_created_at,
               u.user_id, u.user_full_name, u.user_avatar_path,
               (SELECT COUNT(*) FROM comment_likes l WHERE l.like_comment_id = c.comment_id) AS likes,
               (SELECT COUNT(*) FROM comment_dislikes d WHERE d.dislike_comment_id = c.comment_id) AS dislikes
        FROM comments c
        JOIN users u ON u.user_id = c.comment_user_id
        WHERE c.comment_material_id = ?
        ORDER BY c.comment_created_at DESC
        """,
        (material_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_comment(material_id, user_id, text):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO comments (comment_material_id, comment_user_id, comment_text, comment_created_at)
           VALUES (?, ?, ?, ?)""",
        (material_id, user_id, text, now_iso()),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def delete_comment(comment_id, user_id, is_moderator=False):
    """Delete comment if user is the author or a moderator."""
    conn = get_connection()
    cur = conn.cursor()
    comment = cur.execute(
        "SELECT comment_user_id, comment_text FROM comments WHERE comment_id = ?", (comment_id,)
    ).fetchone()
    if not comment:
        conn.close()
        return False
    if comment["comment_user_id"] != user_id and not is_moderator:
        conn.close()
        return False

    # If moderator deletes someone else's comment, send notification
    if is_moderator and comment["comment_user_id"] != user_id:
        comment_preview = comment["comment_text"][:50] + "..." if len(comment["comment_text"]) > 50 else comment["comment_text"]
        add_activity(
            comment["comment_user_id"],
            "comment_deleted",
            f'Ваш комментарий был удалён модератором: "{comment_preview}"',
            "warning"
        )

    cur.execute("DELETE FROM comments WHERE comment_id = ?", (comment_id,))
    conn.commit()
    conn.close()
    return True


def count_user_comments(user_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM comments WHERE comment_user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["c"]


def toggle_comment_like(comment_id, user_id):
    conn = get_connection()
    cur = conn.cursor()
    existing = cur.execute(
        "SELECT like_id FROM comment_likes WHERE like_comment_id = ? AND like_user_id = ?",
        (comment_id, user_id),
    ).fetchone()
    if existing:
        cur.execute("DELETE FROM comment_likes WHERE like_id = ?", (existing["like_id"],))
        conn.commit()
        # Get updated counts
        likes = cur.execute("SELECT COUNT(*) AS c FROM comment_likes WHERE like_comment_id = ?", (comment_id,)).fetchone()["c"]
        dislikes = cur.execute("SELECT COUNT(*) AS c FROM comment_dislikes WHERE dislike_comment_id = ?", (comment_id,)).fetchone()["c"]
        conn.close()
        return {"liked": False, "removed_dislike": False, "likes": likes, "dislikes": dislikes}
    # Remove dislike if exists when liking
    had_dislike = cur.execute(
        "SELECT dislike_id FROM comment_dislikes WHERE dislike_comment_id = ? AND dislike_user_id = ?",
        (comment_id, user_id),
    ).fetchone()
    if had_dislike:
        cur.execute(
            "DELETE FROM comment_dislikes WHERE dislike_comment_id = ? AND dislike_user_id = ?",
            (comment_id, user_id),
        )
    cur.execute(
        "INSERT INTO comment_likes (like_comment_id, like_user_id) VALUES (?, ?)",
        (comment_id, user_id),
    )
    conn.commit()
    # Get updated counts
    likes = cur.execute("SELECT COUNT(*) AS c FROM comment_likes WHERE like_comment_id = ?", (comment_id,)).fetchone()["c"]
    dislikes = cur.execute("SELECT COUNT(*) AS c FROM comment_dislikes WHERE dislike_comment_id = ?", (comment_id,)).fetchone()["c"]
    conn.close()
    return {"liked": True, "removed_dislike": bool(had_dislike), "likes": likes, "dislikes": dislikes}


def toggle_comment_dislike(comment_id, user_id):
    conn = get_connection()
    cur = conn.cursor()
    existing = cur.execute(
        "SELECT dislike_id FROM comment_dislikes WHERE dislike_comment_id = ? AND dislike_user_id = ?",
        (comment_id, user_id),
    ).fetchone()
    if existing:
        cur.execute("DELETE FROM comment_dislikes WHERE dislike_id = ?", (existing["dislike_id"],))
        conn.commit()
        # Get updated counts
        likes = cur.execute("SELECT COUNT(*) AS c FROM comment_likes WHERE like_comment_id = ?", (comment_id,)).fetchone()["c"]
        dislikes = cur.execute("SELECT COUNT(*) AS c FROM comment_dislikes WHERE dislike_comment_id = ?", (comment_id,)).fetchone()["c"]
        conn.close()
        return {"disliked": False, "removed_like": False, "likes": likes, "dislikes": dislikes}
    # Remove like if exists when disliking
    had_like = cur.execute(
        "SELECT like_id FROM comment_likes WHERE like_comment_id = ? AND like_user_id = ?",
        (comment_id, user_id),
    ).fetchone()
    if had_like:
        cur.execute(
            "DELETE FROM comment_likes WHERE like_comment_id = ? AND like_user_id = ?",
            (comment_id, user_id),
        )
    cur.execute(
        "INSERT INTO comment_dislikes (dislike_comment_id, dislike_user_id) VALUES (?, ?)",
        (comment_id, user_id),
    )
    conn.commit()
    # Get updated counts
    likes = cur.execute("SELECT COUNT(*) AS c FROM comment_likes WHERE like_comment_id = ?", (comment_id,)).fetchone()["c"]
    dislikes = cur.execute("SELECT COUNT(*) AS c FROM comment_dislikes WHERE dislike_comment_id = ?", (comment_id,)).fetchone()["c"]
    conn.close()
    return {"disliked": True, "removed_like": bool(had_like), "likes": likes, "dislikes": dislikes}


# ===== Progress =====
def get_progress(user_id, material_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM material_progress WHERE progress_user_id = ? AND progress_material_id = ?",
        (user_id, material_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def start_progress(user_id, material_id):
    conn = get_connection()
    cur = conn.cursor()
    existing = cur.execute(
        "SELECT progress_id FROM material_progress WHERE progress_user_id = ? AND progress_material_id = ?",
        (user_id, material_id),
    ).fetchone()
    if existing:
        cur.execute(
            """UPDATE material_progress
               SET progress_started = 1, progress_step = 0, progress_completed = 0,
                   progress_updated_at = ?
               WHERE progress_id = ?""",
            (now_iso(), existing["progress_id"]),
        )
    else:
        cur.execute(
            """INSERT INTO material_progress
               (progress_user_id, progress_material_id, progress_started, progress_step,
                progress_completed, progress_updated_at)
               VALUES (?, ?, 1, 0, 0, ?)""",
            (user_id, material_id, now_iso()),
        )
    conn.commit()
    conn.close()


def advance_progress(user_id, material_id):
    conn = get_connection()
    cur = conn.cursor()
    existing = cur.execute(
        "SELECT progress_id, progress_step FROM material_progress WHERE progress_user_id = ? AND progress_material_id = ?",
        (user_id, material_id),
    ).fetchone()
    if existing:
        cur.execute(
            """UPDATE material_progress
               SET progress_step = ?, progress_updated_at = ?
               WHERE progress_id = ?""",
            (existing["progress_step"] + 1, now_iso(), existing["progress_id"]),
        )
    conn.commit()
    conn.close()


def complete_progress(user_id, material_id):
    """Mark completed. Returns True if newly completed (XP should be awarded)."""
    conn = get_connection()
    cur = conn.cursor()
    existing = cur.execute(
        "SELECT progress_id, progress_completed FROM material_progress WHERE progress_user_id = ? AND progress_material_id = ?",
        (user_id, material_id),
    ).fetchone()
    if existing and existing["progress_completed"]:
        conn.close()
        return False
    if existing:
        cur.execute(
            """UPDATE material_progress
               SET progress_completed = 1, progress_started = 1, progress_updated_at = ?
               WHERE progress_id = ?""",
            (now_iso(), existing["progress_id"]),
        )
    else:
        cur.execute(
            """INSERT INTO material_progress
               (progress_user_id, progress_material_id, progress_started, progress_step,
                progress_completed, progress_updated_at)
               VALUES (?, ?, 1, 0, 1, ?)""",
            (user_id, material_id, now_iso()),
        )
    conn.commit()
    conn.close()
    return True


def fetch_user_in_progress(user_id):
    """Materials user started but not completed yet."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT m.material_id, m.material_title, m.material_image_path,
                  m.material_type, m.material_views, m.material_difficulty, p.progress_step, p.progress_updated_at,
                  u.user_full_name AS author_name,
                  c.category_name AS top_name,
                  c.category_slug AS top_slug,
                  sc.category_name AS sub_name,
                  sc.category_slug AS sub_slug
           FROM material_progress p
           JOIN materials m ON m.material_id = p.progress_material_id
           JOIN users u ON u.user_id = m.material_author_id
           LEFT JOIN categories c ON c.category_id = m.material_category_id
           LEFT JOIN categories sc ON sc.category_id = m.material_subcategory_id
           WHERE p.progress_user_id = ? AND p.progress_started = 1 AND p.progress_completed = 0
           ORDER BY p.progress_updated_at DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_user_completed(user_id):
    conn = get_connection()
    rows = conn.execute(
        """SELECT m.material_id, m.material_title, m.material_image_path,
                  m.material_type, m.material_views, m.material_difficulty, p.progress_updated_at,
                  u.user_full_name AS author_name,
                  c.category_name AS top_name,
                  c.category_slug AS top_slug,
                  sc.category_name AS sub_name,
                  sc.category_slug AS sub_slug
           FROM material_progress p
           JOIN materials m ON m.material_id = p.progress_material_id
           JOIN users u ON u.user_id = m.material_author_id
           LEFT JOIN categories c ON c.category_id = m.material_category_id
           LEFT JOIN categories sc ON sc.category_id = m.material_subcategory_id
           WHERE p.progress_user_id = ? AND p.progress_completed = 1
           ORDER BY p.progress_updated_at DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_user_completed(user_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM material_progress WHERE progress_user_id = ? AND progress_completed = 1",
        (user_id,),
    ).fetchone()
    conn.close()
    return row["c"] if row else 0


# ===== Leaderboard =====
def fetch_leaderboard(sort="rating", limit=10, exclude_hidden=False):
    """Sort options: 'rating' (default), 'level' (xp), 'completed', 'created'."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            u.user_id,
            u.user_full_name,
            u.user_avatar_path,
            u.user_xp,
            (SELECT COUNT(*) FROM material_progress p WHERE p.progress_user_id = u.user_id AND p.progress_completed = 1) AS completed_count,
            (SELECT COUNT(*) FROM materials m WHERE m.material_author_id = u.user_id) AS created_count,
            s.setting_hide_leaderboard,
            s.setting_hide_profile,
            s.setting_hide_avatar,
            s.setting_hide_level,
            s.setting_hide_xp
            FROM users u
            LEFT JOIN user_settings s ON u.user_id = s.setting_user_id

        """
    ).fetchall()

    leaders = []
    for r in rows:
        d = dict(r)
        if exclude_hidden and (d.get("setting_hide_leaderboard") or d.get("setting_hide_profile")):
            continue
        if d.get("setting_hide_leaderboard") or d.get("setting_hide_profile") or d.get("setting_hide_avatar"):
            d["user_avatar_path"] = None
        d["level"] = compute_level(d["user_xp"])
        d["xp_in_level"] = compute_xp_in_level(d["user_xp"])
        d["rating"] = compute_rating(d["user_xp"], d["completed_count"], d["created_count"])
        leaders.append(d)

    if sort == "level":
        leaders.sort(key=lambda x: (-x["user_xp"], -x["rating"]))
    elif sort == "completed":
        leaders.sort(key=lambda x: (-x["completed_count"], -x["rating"]))
    elif sort == "created":
        leaders.sort(key=lambda x: (-x["created_count"], -x["rating"]))
    else:
        leaders.sort(key=lambda x: (-x["rating"], -x["user_xp"]))

    conn.close()
    return leaders[:limit]


def fetch_total_users():
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    conn.close()
    return row["c"]


def fetch_user_position(user_id, sort="rating"):
    """Position of the user given a sort order (1-based)."""
    leaders = fetch_leaderboard(sort=sort, limit=10000)
    for i, l in enumerate(leaders, start=1):
        if l["user_id"] == user_id:
            return i
    return None


# ===== Achievements / badges =====
def fetch_achievements_for(user_id):
    conn = get_connection()

    # Get user stats for progress calculation
    user = fetch_user_by_id(user_id)
    if not user:
        conn.close()
        return []

    xp = user.get("user_xp", 0)
    level = compute_level(xp)
    completed_count = count_user_completed(user_id)
    created_count = fetch_user_materials_count(user_id)

    rows = conn.execute(
        """
        SELECT a.*,
               CASE WHEN ua.ua_id IS NOT NULL THEN 1 ELSE 0 END AS earned,
               ua.ua_earned_at
        FROM achievements a
        LEFT JOIN user_achievements ua
               ON ua.ua_achievement_id = a.achievement_id AND ua.ua_user_id = ?
        ORDER BY a.achievement_order ASC, a.achievement_id ASC
        """,
        (user_id,),
    ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        # Calculate progress based on achievement code
        code = d.get("achievement_code", "")
        if not d.get("earned"):
            if code.startswith("level_"):
                d["user_progress"] = level
            elif code.startswith("complete_"):
                d["user_progress"] = completed_count
            elif code.startswith("create_"):
                d["user_progress"] = created_count
            else:
                d["user_progress"] = 0
        result.append(d)

    conn.close()
    return result


def fetch_badges_for(user_id):
    conn = get_connection()

    # Get user stats for progress calculation
    user = fetch_user_by_id(user_id)
    if not user:
        conn.close()
        return []

    streak = user.get("user_streak_days", 0)

    # Get comment count
    comment_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM comments WHERE comment_user_id = ?",
        (user_id,)
    ).fetchone()["cnt"]

    rows = conn.execute(
        """
        SELECT b.*,
               CASE WHEN ub.ub_id IS NOT NULL THEN 1 ELSE 0 END AS earned,
               ub.ub_earned_at
        FROM badges b
        LEFT JOIN user_badges ub
               ON ub.ub_badge_id = b.badge_id AND ub.ub_user_id = ?
        ORDER BY b.badge_order ASC, b.badge_id ASC
        """,
        (user_id,),
    ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        # Calculate progress based on badge code
        code = d.get("badge_code", "")
        if not d.get("earned"):
            if code.startswith("streak_"):
                d["user_progress"] = streak
            elif code.startswith("comment_"):
                d["user_progress"] = comment_count
            else:
                d["user_progress"] = 0
        result.append(d)

    conn.close()
    return result


def grant_achievement(user_id, code):
    conn = get_connection()
    cur = conn.cursor()
    a = cur.execute(
        "SELECT achievement_id, achievement_name FROM achievements WHERE achievement_code = ?",
        (code,),
    ).fetchone()
    if not a:
        conn.close()
        return None
    existing = cur.execute(
        "SELECT ua_id FROM user_achievements WHERE ua_user_id = ? AND ua_achievement_id = ?",
        (user_id, a["achievement_id"]),
    ).fetchone()
    if existing:
        conn.close()
        return None
    cur.execute(
        """INSERT INTO user_achievements (ua_user_id, ua_achievement_id, ua_earned_at)
           VALUES (?, ?, ?)""",
        (user_id, a["achievement_id"], now_iso()),
    )
    conn.commit()
    conn.close()
    add_activity(user_id, "achievement", f'Получено достижение: «{a["achievement_name"]}»', "trophy")
    return a["achievement_name"]


def grant_badge(user_id, code):
    conn = get_connection()
    cur = conn.cursor()
    b = cur.execute(
        "SELECT badge_id, badge_name FROM badges WHERE badge_code = ?", (code,)
    ).fetchone()
    if not b:
        conn.close()
        return None
    existing = cur.execute(
        "SELECT ub_id FROM user_badges WHERE ub_user_id = ? AND ub_badge_id = ?",
        (user_id, b["badge_id"]),
    ).fetchone()
    if existing:
        conn.close()
        return None
    cur.execute(
        """INSERT INTO user_badges (ub_user_id, ub_badge_id, ub_earned_at)
           VALUES (?, ?, ?)""",
        (user_id, b["badge_id"], now_iso()),
    )
    conn.commit()
    conn.close()
    add_activity(user_id, "badge", f'Получен значок: «{b["badge_name"]}»', "star")
    return b["badge_name"]


def recalc_user_awards(user_id):
    """Re-evaluate all achievement/badge rules for a user and grant any newly qualifying ones. Returns dict with new awards."""
    user = fetch_user_by_id(user_id)
    if not user:
        return {"achievements": [], "badges": []}
    xp = user.get("user_xp", 0)
    level = compute_level(xp)
    streak = user.get("user_streak_days", 0)
    completed = count_user_completed(user_id)
    created = fetch_user_materials_count(user_id)
    comments = count_user_comments(user_id)
    position = fetch_user_position(user_id, sort="rating")

    new_achievements = []
    new_badges = []

    # Achievements
    ach = grant_achievement(user_id, "first_steps") if completed >= 1 else None
    if ach: new_achievements.append(ach)
    ach = grant_achievement(user_id, "ten_done") if completed >= 10 else None
    if ach: new_achievements.append(ach)
    ach = grant_achievement(user_id, "fifty_done") if completed >= 50 else None
    if ach: new_achievements.append(ach)
    ach = grant_achievement(user_id, "author") if created >= 1 else None
    if ach: new_achievements.append(ach)
    ach = grant_achievement(user_id, "mentor") if created >= 5 else None
    if ach: new_achievements.append(ach)
    ach = grant_achievement(user_id, "knowledge_keeper") if created >= 20 else None
    if ach: new_achievements.append(ach)
    ach = grant_achievement(user_id, "focused") if streak >= 7 else None
    if ach: new_achievements.append(ach)
    ach = grant_achievement(user_id, "marathoner") if streak >= 30 else None
    if ach: new_achievements.append(ach)
    ach = grant_achievement(user_id, "commenter") if comments >= 25 else None
    if ach: new_achievements.append(ach)
    ach = grant_achievement(user_id, "rising_star") if level >= 5 else None
    if ach: new_achievements.append(ach)
    ach = grant_achievement(user_id, "legend") if level >= 20 else None
    if ach: new_achievements.append(ach)
    ach = grant_achievement(user_id, "champion") if position and position <= 10 else None
    if ach: new_achievements.append(ach)

    # Badges
    bdg = grant_badge(user_id, "novice") if level >= 3 else None
    if bdg: new_badges.append(bdg)
    bdg = grant_badge(user_id, "apprentice") if level >= 10 else None
    if bdg: new_badges.append(bdg)
    bdg = grant_badge(user_id, "master") if level >= 25 else None
    if bdg: new_badges.append(bdg)
    bdg = grant_badge(user_id, "learner_5") if completed >= 5 else None
    if bdg: new_badges.append(bdg)
    bdg = grant_badge(user_id, "learner_25") if completed >= 25 else None
    if bdg: new_badges.append(bdg)
    bdg = grant_badge(user_id, "creator_3") if created >= 3 else None
    if bdg: new_badges.append(bdg)
    bdg = grant_badge(user_id, "creator_15") if created >= 15 else None
    if bdg: new_badges.append(bdg)
    bdg = grant_badge(user_id, "streak_3") if streak >= 3 else None
    if bdg: new_badges.append(bdg)
    bdg = grant_badge(user_id, "streak_14") if streak >= 14 else None
    if bdg: new_badges.append(bdg)

    return {"achievements": new_achievements, "badges": new_badges}


# ===== Activity =====
def fetch_activity_for(user_id, limit=50):
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM activity_log
           WHERE activity_user_id = ?
           ORDER BY activity_created_at DESC
           LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_activity(user_id, activity_type, text, icon="star"):
    conn = get_connection()
    conn.execute(
        """INSERT INTO activity_log
           (activity_user_id, activity_type, activity_text, activity_icon, activity_created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, activity_type, text, icon, now_iso()),
    )
    conn.commit()
    conn.close()


def fetch_user_materials_count(user_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM materials WHERE material_author_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return row["c"]


# ===== Moderation =====
def is_user_moderator(user_id):
    """Check whether a user has moderator role."""
    user = fetch_user_by_id(user_id)
    return user and user.get("user_role") == "moderator"


def fetch_pending_materials():
    """Return all materials awaiting moderation."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT m.*,
               u.user_full_name AS author_name,
               u.user_avatar_path AS author_avatar,
               cs.category_name AS sub_name,
               cs.category_slug AS sub_slug,
               ct.category_name AS top_name,
               ct.category_slug AS top_slug
        FROM materials m
        JOIN users u ON u.user_id = m.material_author_id
        LEFT JOIN categories cs ON cs.category_id = m.material_subcategory_id
        LEFT JOIN categories ct ON ct.category_id = m.material_category_id
        WHERE m.material_status = 'pending'
        ORDER BY m.material_created_at ASC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_user_pending_materials(user_id):
    """Return materials by a specific user that are pending review."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT m.*,
               cs.category_name AS sub_name,
               cs.category_slug AS sub_slug,
               ct.category_name AS top_name,
               ct.category_slug AS top_slug
        FROM materials m
        LEFT JOIN categories cs ON cs.category_id = m.material_subcategory_id
        LEFT JOIN categories ct ON ct.category_id = m.material_category_id
        WHERE m.material_author_id = ? AND m.material_status = 'pending'
        ORDER BY m.material_created_at DESC
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_material(material_id):
    """Approve a pending material."""
    conn = get_connection()
    conn.execute(
        "UPDATE materials SET material_status = 'approved', material_backup_json = NULL WHERE material_id = ?",
        (material_id,),
    )
    conn.commit()
    conn.close()


def reject_material(material_id):
    """Reject a pending material. If it was a re-moderation, restore backup."""
    material = fetch_material(material_id)
    if not material:
        return
    backup_str = material.get("material_backup_json")
    if backup_str:
        backup = json.loads(backup_str)
        if material.get("material_image_path") and material.get("material_image_path") != backup.get("material_image_path"):
            remove_local_asset(material.get("material_image_path"))
        conn = get_connection()
        conn.execute("""UPDATE materials SET
            material_title = ?, material_description = ?, material_type = ?,
            material_category_id = ?, material_subcategory_id = ?, material_difficulty = ?,
            material_content = ?, material_image_path = ?, material_youtube_url = ?,
            material_steps_json = ?, material_status = 'approved', material_backup_json = NULL
            WHERE material_id = ?""", (
            backup.get("material_title", ""), backup.get("material_description", ""), backup.get("material_type", ""),
            backup.get("material_category_id"), backup.get("material_subcategory_id"), backup.get("material_difficulty", "beginner"),
            backup.get("material_content", ""), backup.get("material_image_path"), backup.get("material_youtube_url", ""),
            backup.get("material_steps_json", "[]"), material_id
        ))
        conn.commit()
        conn.close()
        add_activity(material["material_author_id"], "moderation_rejected", f"Ваши изменения в материале «{backup.get('material_title', '')}» были отклонены модератором. Материал возвращён к исходному состоянию.", "warning")
    else:
        if material.get("material_image_path"):
            remove_local_asset(material["material_image_path"])
        conn = get_connection()
        conn.execute("DELETE FROM materials WHERE material_id = ?", (material_id,))
        conn.commit()
        conn.close()
        add_activity(material["material_author_id"], "moderation_rejected", f"Ваш материал «{material['material_title']}» был отклонён модератором.", "warning")


def fetch_all_users():
    """Return all users (for moderation)."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM users ORDER BY user_created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remove_local_asset(web_path):
    """Delete a file under Assets/* given a web path like /Assets/Uploads/x.png."""
    import os as _os
    if not web_path:
        return
    name = _os.path.basename(web_path)
    parent = _os.path.basename(_os.path.dirname(web_path))
    target_root = None
    if parent == "Avatars":
        target_root = _os.path.join(BASE_DIR, "Assets", "Avatars")
    elif parent == "Uploads":
        target_root = _os.path.join(BASE_DIR, "Assets", "Uploads")
    if target_root:
        p = _os.path.join(target_root, name)
        if _os.path.exists(p):
            try:
                _os.remove(p)
            except OSError:
                pass


def compute_rank_label(xp):
    """Map XP to a textual level label like 'Уровень N'."""
    return f"Уровень {compute_level(xp)}"


# ===== EduCoin functions =====
def add_educoins(user_id, amount):
    """Add educoins to user balance."""
    conn = get_connection()
    conn.execute(
        "UPDATE users SET user_educoins = user_educoins + ? WHERE user_id = ?",
        (int(amount), user_id),
    )
    conn.commit()
    conn.close()


def get_user_educoins(user_id):
    """Get user's educoin balance."""
    conn = get_connection()
    row = conn.execute(
        "SELECT user_educoins FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["user_educoins"] if row else 0


def check_level_rewards(user_id, old_xp, new_xp):
    """Check if user leveled up and award educoins for every 10 levels. Returns new level if leveled up."""
    old_level = compute_level(old_xp)
    new_level = compute_level(new_xp)
    if new_level > old_level:
        for lvl in range(old_level + 1, new_level + 1):
            if lvl % 10 == 0:
                add_educoins(user_id, 1)
                add_activity(user_id, "educoin", f"Получен 1 eduCoin за достижение {lvl} уровня", "star")
        return new_level
    return None


# ===== Shop functions =====
def fetch_shop_items(item_type=None):
    """Fetch shop items, optionally filtered by type."""
    conn = get_connection()
    if item_type:
        rows = conn.execute(
            "SELECT * FROM shop_items WHERE item_type = ? ORDER BY item_order, item_id",
            (item_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM shop_items ORDER BY item_type, item_order, item_id"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_user_purchases(user_id):
    """Get all items purchased by user."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT si.* FROM shop_items si
           JOIN user_purchases up ON up.purchase_item_id = si.item_id
           WHERE up.purchase_user_id = ?""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def purchase_item(user_id, item_id):
    """Purchase an item if user has enough educoins."""
    conn = get_connection()
    cur = conn.cursor()

    item = cur.execute("SELECT * FROM shop_items WHERE item_id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        return False, "Товар не найден"

    user = cur.execute("SELECT user_educoins FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return False, "Пользователь не найден"

    if user["user_educoins"] < item["item_price"]:
        conn.close()
        return False, "Недостаточно eduCoin"

    existing = cur.execute(
        "SELECT purchase_id FROM user_purchases WHERE purchase_user_id = ? AND purchase_item_id = ?",
        (user_id, item_id),
    ).fetchone()
    if existing:
        conn.close()
        return False, "Товар уже куплен"

    cur.execute(
        "UPDATE users SET user_educoins = user_educoins - ? WHERE user_id = ?",
        (item["item_price"], user_id),
    )
    cur.execute(
        "INSERT INTO user_purchases (purchase_user_id, purchase_item_id, purchase_date) VALUES (?, ?, ?)",
        (user_id, item_id, now_iso()),
    )
    conn.commit()
    conn.close()
    add_activity(user_id, "purchase", f'Куплен товар: «{item["item_name"]}» за {item["item_price"]} eduCoin', "star")
    return True, "Покупка успешна"


# ===== User settings =====
def get_user_settings(user_id):
    """Get user settings, create default if not exists."""
    conn = get_connection()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT * FROM user_settings WHERE setting_user_id = ?", (user_id,)
    ).fetchone()
    if not row:
        cur.execute(
            "INSERT INTO user_settings (setting_user_id) VALUES (?)", (user_id,)
        )
        conn.commit()
        row = cur.execute(
            "SELECT * FROM user_settings WHERE setting_user_id = ?", (user_id,)
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_settings(user_id, settings_dict):
    """Update user settings."""
    conn = get_connection()
    cur = conn.cursor()

    existing = cur.execute(
        "SELECT setting_id FROM user_settings WHERE setting_user_id = ?", (user_id,)
    ).fetchone()
    if not existing:
        cur.execute("INSERT INTO user_settings (setting_user_id) VALUES (?)", (user_id,))

    fields = []
    values = []
    for key, val in settings_dict.items():
        if key.startswith("setting_"):
            fields.append(f"{key} = ?")
            values.append(val)

    if fields:
        values.append(user_id)
        cur.execute(
            f"UPDATE user_settings SET {', '.join(fields)} WHERE setting_user_id = ?",
            values,
        )
    conn.commit()
    conn.close()


def delete_user_account(user_id):
    """Delete user account and all related data."""
    conn = get_connection()
    user = conn.execute("SELECT user_avatar_path FROM users WHERE user_id = ?", (user_id,)).fetchone()

    # Delete all related data first to avoid foreign key constraints
    conn.execute("DELETE FROM material_progress WHERE progress_user_id = ?", (user_id,))
    conn.execute("DELETE FROM material_ratings WHERE rating_user_id = ?", (user_id,))
    conn.execute("DELETE FROM material_views_log WHERE view_user_id = ?", (user_id,))
    conn.execute("DELETE FROM comments WHERE comment_user_id = ?", (user_id,))
    conn.execute("DELETE FROM comment_likes WHERE like_user_id = ?", (user_id,))
    conn.execute("DELETE FROM comment_dislikes WHERE dislike_user_id = ?", (user_id,))
    conn.execute("DELETE FROM user_achievements WHERE ua_user_id = ?", (user_id,))
    conn.execute("DELETE FROM user_badges WHERE ub_user_id = ?", (user_id,))
    conn.execute("DELETE FROM activity_log WHERE activity_user_id = ?", (user_id,))
    conn.execute("DELETE FROM user_purchases WHERE purchase_user_id = ?", (user_id,))
    conn.execute("DELETE FROM user_settings WHERE setting_user_id = ?", (user_id,))

    # Delete materials created by user
    materials = conn.execute("SELECT material_id, material_image_path FROM materials WHERE material_author_id = ?", (user_id,)).fetchall()
    for mat in materials:
        if mat["material_image_path"]:
            remove_local_asset(mat["material_image_path"])
        conn.execute("DELETE FROM materials WHERE material_id = ?", (mat["material_id"],))

    # Delete user avatar and user record
    if user and user["user_avatar_path"]:
        remove_local_asset(user["user_avatar_path"])
    conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()


def ensure_progress_started(user_id, material_id):
    """Ensure progress record exists with started=1 for tracking in 'My Learning'."""
    conn = get_connection()
    cur = conn.cursor()
    existing = cur.execute(
        "SELECT progress_id, progress_started FROM material_progress WHERE progress_user_id = ? AND progress_material_id = ?",
        (user_id, material_id),
    ).fetchone()
    if not existing:
        cur.execute(
            """INSERT INTO material_progress
               (progress_user_id, progress_material_id, progress_started, progress_step,
                progress_completed, progress_updated_at)
               VALUES (?, ?, 1, 0, 0, ?)""",
            (user_id, material_id, now_iso()),
        )
        conn.commit()
    elif not existing["progress_started"]:
        cur.execute(
            "UPDATE material_progress SET progress_started = 1, progress_updated_at = ? WHERE progress_id = ?",
            (now_iso(), existing["progress_id"]),
        )
        conn.commit()
    conn.close()


def set_material_xp_reward(material_id, xp_amount):
    """Set the XP reward that users get for completing this material."""
    conn = get_connection()
    conn.execute(
        "UPDATE materials SET material_xp_reward = ? WHERE material_id = ?",
        (int(xp_amount), material_id),
    )
    conn.commit()
    conn.close()


def get_material_xp_reward(material_id):
    """Get the XP reward for completing this material."""
    conn = get_connection()
    row = conn.execute(
        "SELECT material_xp_reward FROM materials WHERE material_id = ?", (material_id,)
    ).fetchone()
    conn.close()
    return row["material_xp_reward"] if row else 0
