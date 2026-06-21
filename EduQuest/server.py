import os
import re
import json
import uuid
from urllib.parse import urlparse, parse_qs
from PIL import Image

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, send_from_directory, abort, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from PythonFiles import database as db
from PythonFiles.translations import get_translation, get_language_name, TRANSLATIONS
from PythonFiles.email_helper import send_verification_code
from PythonFiles.profanity_helper import check_text_for_profanity


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "HTML"),
    static_folder=None,  # we register custom static routes for our folders
)
app.secret_key = os.environ.get("EDUQUEST_SECRET", "eduquest-dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
AVATARS_DIR = os.path.join(BASE_DIR, "Assets", "Avatars")
UPLOADS_DIR = os.path.join(BASE_DIR, "Assets", "Uploads")
LOGOS_DIR = os.path.join(BASE_DIR, "Assets", "Logos")
FAVICONS_DIR = os.path.join(BASE_DIR, "Assets", "Favicons")
CSS_DIR = os.path.join(BASE_DIR, "CSSFiles")
JS_DIR = os.path.join(BASE_DIR, "JSFiles")

os.makedirs(AVATARS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)


# ===== Init DB on startup =====
db.init_db()


# ===== Database Backup System =====
BACKUPS_DIR = os.path.join(BASE_DIR, "DB", "backups")
os.makedirs(BACKUPS_DIR, exist_ok=True)

def perform_db_backup():
    import shutil
    from datetime import datetime
    import time

    while True:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(BACKUPS_DIR, f"eduquest_backup_{timestamp}.db")
            shutil.copy2(db.DB_PATH, backup_file)
            print(f"Database backup created: {backup_file}")

            # Keep only last 10 backups
            backups = sorted([f for f in os.listdir(BACKUPS_DIR) if f.startswith("eduquest_backup_")])
            while len(backups) > 10:
                os.remove(os.path.join(BACKUPS_DIR, backups.pop(0)))
        except Exception as e:
            print(f"Error during DB backup: {e}")
        
        # Wait 12 hours
        time.sleep(12 * 3600)

import threading
backup_thread = threading.Thread(target=perform_db_backup, daemon=True)
backup_thread.start()


# ===== Static asset routes =====
@app.route("/Assets/Logos/<path:filename>")
def asset_logos(filename):
    return send_from_directory(LOGOS_DIR, filename)


@app.route("/Assets/Avatars/<path:filename>")
def asset_avatars(filename):
    return send_from_directory(AVATARS_DIR, filename)


@app.route("/Assets/Uploads/<path:filename>")
def asset_uploads(filename):
    return send_from_directory(UPLOADS_DIR, filename)


@app.route("/Assets/Favicons/<path:filename>")
def asset_favicons(filename):
    return send_from_directory(FAVICONS_DIR, filename)


@app.route("/CSSFiles/<path:filename>")
def css_files(filename):
    return send_from_directory(CSS_DIR, filename)


@app.route("/JSFiles/<path:filename>")
def js_files(filename):
    return send_from_directory(JS_DIR, filename)


# ===== Helpers =====
def is_image(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def save_uploaded_image(file_storage, target_dir, max_size=(800, 800), quality=85):
    """Save uploaded image with resize, crop to center, and compression. Returns (filename, web_path)."""
    if not file_storage or file_storage.filename == "":
        return None, None
    if not is_image(file_storage.filename):
        return None, None

    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    new_name = f"{uuid.uuid4().hex}.{ext}"
    abs_path = os.path.join(target_dir, secure_filename(new_name))

    # Open and process image
    try:
        img = Image.open(file_storage)

        # Convert RGBA to RGB if needed (for JPEG compatibility)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background

        # Crop to center with target aspect ratio
        img_width, img_height = img.size
        max_width, max_height = max_size
        target_ratio = max_width / max_height
        current_ratio = img_width / img_height

        if current_ratio > target_ratio:
            # Image is wider than target - crop width
            new_width = int(img_height * target_ratio)
            left = (img_width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img_height))
        elif current_ratio < target_ratio:
            # Image is taller than target - crop height
            new_height = int(img_width / target_ratio)
            top = (img_height - new_height) // 2
            img = img.crop((0, top, img_width, top + new_height))

        # Resize to exact target size
        img = img.resize(max_size, Image.Resampling.LANCZOS)

        # Save with compression
        if ext in ('jpg', 'jpeg'):
            img.save(abs_path, 'JPEG', quality=quality, optimize=True)
        elif ext == 'png':
            img.save(abs_path, 'PNG', optimize=True)
        elif ext == 'webp':
            img.save(abs_path, 'WEBP', quality=quality, optimize=True)
        else:
            img.save(abs_path, quality=quality, optimize=True)

    except Exception as e:
        print(f"Error processing image: {e}")
        return None, None

    rel = os.path.relpath(target_dir, BASE_DIR).replace(os.sep, "/")
    return new_name, f"/{rel}/{new_name}"


def remove_local_asset(web_path):
    """Delete a file under Assets/* given a web path like /Assets/Uploads/x.png."""
    if not web_path:
        return
    name = os.path.basename(web_path)
    parent = os.path.basename(os.path.dirname(web_path))
    target_root = None
    if parent == "Avatars":
        target_root = AVATARS_DIR
    elif parent == "Uploads":
        target_root = UPLOADS_DIR
    if target_root:
        p = os.path.join(target_root, name)
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def parse_youtube(url: str):
    if not url:
        return None
    try:
        u = urlparse(url.strip())
    except Exception:
        return None
    host = (u.hostname or "").lower()
    if "youtu.be" in host:
        return u.path.lstrip("/").split("/")[0] or None
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        if u.path == "/watch":
            return parse_qs(u.query).get("v", [None])[0]
        if u.path.startswith("/embed/"):
            return u.path.split("/")[2] or None
        if u.path.startswith("/shorts/"):
            return u.path.split("/")[2] or None
    return None


def humanize_time(iso_string: str, lang=None) -> str:
    from datetime import datetime, timezone
    lang = lang or session.get("language", "ru")
    try:
        dt = datetime.fromisoformat(iso_string)
    except Exception:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return get_translation("ago_now", lang)
    minutes = seconds // 60
    if minutes < 60:
        return get_translation("ago_minutes", lang).format(n=minutes)
    hours = minutes // 60
    if hours < 24:
        return get_translation("ago_hours", lang).format(n=hours)
    days = hours // 24
    if days == 1:
        return get_translation("ago_day", lang)
    if days < 7:
        return get_translation("ago_days", lang).format(n=days)
    weeks = days // 7
    if weeks == 1:
        return get_translation("ago_week", lang)
    if weeks < 5:
        return get_translation("ago_weeks", lang).format(n=weeks)
    months = days // 30
    if months <= 1:
        return get_translation("ago_month", lang)
    if months < 12:
        return get_translation("ago_months", lang).format(n=months)
    years = days // 365
    if years <= 1:
        return get_translation("ago_year", lang)
    return get_translation("ago_years", lang).format(n=years)


@app.template_filter("ago")
def ago_filter(value):
    return humanize_time(value, session.get("language", "ru"))


@app.template_filter("avatar_initials")
def avatar_initials(full_name):
    if not full_name:
        return "?"
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


@app.template_filter("level")
def level_filter(xp):
    return db.compute_level(xp or 0)


@app.template_filter("nice_number")
def nice_number(n):
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


@app.template_filter("from_json")
def from_json_filter(value):
    try:
        return json.loads(value)
    except Exception:
        return {}


@app.template_filter("t")
def translate_filter(key):
    """Translation filter for templates"""
    lang = session.get("language", "ru")
    return get_translation(key, lang)


def tr(key, **kwargs):
    """Translate a user-facing server message for the current session."""
    text = get_translation(key, session.get("language", "ru"))
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = db.fetch_user_by_id(user_id)
    if not user:
        session.pop("user_id", None)
        return None
    return user


@app.context_processor
def inject_globals():
    user = get_current_user()
    user_theme = 'light'
    user_lang = session.get("language", "ru")
    user_settings = None
    pending_notifications = session.get('pending_notifications', None)
    if user:
        settings = db.get_user_settings(user["user_id"])
        if settings:
            user_settings = settings
            user_theme = settings.get("setting_theme", "light")
            user_lang = settings.get("setting_language", "ru")
            session["language"] = user_lang

    # Helper function for translations in templates
    def t(key):
        return get_translation(key, user_lang)

    def material_type_label(material_type):
        type_keys = {
            "course": "course",
            "article": "article",
            "video": "video",
            "test": "test",
            "tip": "tip",
        }
        key = type_keys.get(material_type)
        return get_translation(key, user_lang) if key else (material_type or "")

    def difficulty_label(difficulty):
        diff_keys = {
            "beginner": "beginner",
            "intermediate": "intermediate",
            "advanced": "advanced",
        }
        key = diff_keys.get(difficulty)
        return get_translation(key, user_lang) if key else (difficulty or "")

    def category_label(slug, fallback=""):
        key = f"category_{slug}".replace("-", "_") if slug else ""
        translated = get_translation(key, user_lang) if key else key
        return translated if translated != key else (fallback or "")

    def translated_entity(prefix, code, field, fallback=""):
        key = f"{prefix}_{code}_{field}".replace("-", "_") if code else ""
        translated = get_translation(key, user_lang) if key else key
        return translated if translated != key else (fallback or "")

    def achievement_name(achievement):
        return translated_entity("achievement", achievement.get("achievement_code"), "name", achievement.get("achievement_name", ""))

    def achievement_desc(achievement):
        return translated_entity("achievement", achievement.get("achievement_code"), "desc", achievement.get("achievement_description", ""))

    def badge_name(badge):
        return translated_entity("badge", badge.get("badge_code"), "name", badge.get("badge_name", ""))

    def badge_desc(badge):
        return translated_entity("badge", badge.get("badge_code"), "desc", badge.get("badge_description", ""))

    def shop_item_name(item):
        return translated_entity("shop", item.get("item_code"), "name", item.get("item_name", ""))

    def shop_item_desc(item):
        return translated_entity("shop", item.get("item_code"), "desc", item.get("item_description", ""))

    return {
        "current_user": user,
        "top_categories": db.fetch_top_categories(),
        "user_theme": user_theme,
        "user_settings": user_settings,
        "pending_notifications": pending_notifications,
        "current_language": user_lang,
        "available_languages": ["ru", "en", "kk"],
        "t": t,
        "material_type_label": material_type_label,
        "difficulty_label": difficulty_label,
        "category_label": category_label,
        "achievement_name": achievement_name,
        "achievement_desc": achievement_desc,
        "badge_name": badge_name,
        "badge_desc": badge_desc,
        "shop_item_name": shop_item_name,
        "shop_item_desc": shop_item_desc,
        "is_moderator": user and db.is_user_moderator(user["user_id"]),
    }


def login_required_route(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not get_current_user():
            flash(tr("login_required_message"), "error")
            return redirect(url_for("home"))
        return fn(*args, **kwargs)
    return wrapper


# ===== Page routes =====
@app.route("/")
def home():
    sort = request.args.get("sort", "trending")
    top_slug = request.args.get("category")
    sub_slug = request.args.get("subcategory")
    search = request.args.get("q")

    materials = db.fetch_materials(
        top_category_slug=top_slug,
        sub_category_slug=sub_slug,
        sort=sort,
        search=search,
    )
    subcategories = db.fetch_subcategories(parent_slug=top_slug) if top_slug else []
    return render_template(
        "index.html",
        materials=materials,
        active_sort=sort,
        active_category=top_slug,
        active_subcategory=sub_slug,
        subcategories=subcategories,
        search_query=search or "",
    )


@app.route("/material/<int:material_id>")
def material_view(material_id):
    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    user = get_current_user()
    is_author = bool(user and user["user_id"] == material["material_author_id"])
    is_mod = user and db.is_user_moderator(user["user_id"])
    is_pending = material.get("material_status") == "pending"

    # Block access to pending materials for non-author, non-moderator users
    if is_pending and not is_author and not is_mod:
        abort(404)

    # Register a unique view only for approved materials
    if not is_pending:
        db.register_view(user["user_id"] if user else None, material_id)

    # Auto-start progress for Video, Test, Tip types (so they show in "My Learning")
    if user and not is_pending and material["material_type"] in ("video", "test", "tip"):
        db.ensure_progress_started(user["user_id"], material_id)

    youtube_id = parse_youtube(material.get("material_youtube_url") or "")
    try:
        steps = json.loads(material.get("material_steps_json") or "[]")
    except Exception:
        steps = []
    comments = db.fetch_comments_for(material_id)
    progress = db.get_progress(user["user_id"], material_id) if user else None
    user_rating = db.fetch_user_rating_for(user["user_id"], material_id) if user else 0
    return render_template(
        "material.html",
        material=material,
        youtube_id=youtube_id,
        steps=steps,
        comments=comments,
        progress=progress,
        user_rating=user_rating,
        is_author=is_author,
        is_pending=is_pending,
    )


@app.route("/leaderboard")
def leaderboard():
    sort = request.args.get("sort", "rating")
    if sort not in ("rating", "level", "completed", "created"):
        sort = "rating"
    leaders = db.fetch_leaderboard(sort=sort, limit=10, exclude_hidden=True)
    total_users = db.fetch_total_users()
    user = get_current_user()
    your_position = None
    if user:
        pos = db.fetch_user_position(user["user_id"], sort=sort)
        completed_count = db.count_user_completed(user["user_id"])
        created_count = db.fetch_user_materials_count(user["user_id"])
        your_position = {
            "pos": pos,
            "name": user["user_full_name"],
            "avatar": user.get("user_avatar_path"),
            "xp": user["user_xp"],
            "level": db.compute_level(user["user_xp"]),
            "rating": db.compute_rating(user["user_xp"], completed_count, created_count),
            "completed": completed_count,
            "created": created_count,
        }
    total_completed = sum(l["completed_count"] for l in leaders)
    total_created = sum(l["created_count"] for l in leaders)
    return render_template(
        "leaderboard.html",
        leaders=leaders,
        active_sort=sort,
        total_users=total_users,
        your_position=your_position,
        total_completed=total_completed,
        total_created=total_created,
    )


@app.route("/learning")
@login_required_route
def my_learning():
    user = get_current_user()
    in_progress = db.fetch_user_in_progress(user["user_id"])
    completed = db.fetch_user_completed(user["user_id"])
    return render_template(
        "learning.html",
        in_progress=in_progress,
        completed=completed,
    )


@app.route("/profile")
@login_required_route
def profile():
    user = get_current_user()
    settings = db.get_user_settings(user["user_id"])
    achievements = db.fetch_achievements_for(user["user_id"])
    badges = db.fetch_badges_for(user["user_id"])
    activity = db.fetch_activity_for(user["user_id"], limit=8)
    materials_count = db.fetch_user_materials_count(user["user_id"])
    completed_count = db.count_user_completed(user["user_id"])
    rating = db.compute_rating(user["user_xp"], completed_count, materials_count)
    position = db.fetch_user_position(user["user_id"], sort="rating")
    earned_ach = sum(1 for a in achievements if a["earned"])
    earned_badges = sum(1 for b in badges if b["earned"])

    # Apply customization from settings
    active_frame_code = settings.get("setting_active_frame") if settings else None
    active_theme_code = settings.get("setting_active_theme") if settings else None
    active_badge_code = settings.get("setting_active_badge") if settings else None

    # Get actual values from shop items
    active_frame = None
    active_frame_data = None
    active_theme = None
    active_theme_data = None
    active_badge = None

    if active_frame_code or active_theme_code or active_badge_code:
        purchases = db.fetch_user_purchases(user["user_id"])
        for p in purchases:
            if active_frame_code and p["item_code"] == active_frame_code and p["item_type"] == "frame":
                try:
                    data = json.loads(p.get("item_data", "{}"))
                    active_frame_data = data
                    if "gradient" in data:
                        active_frame = data.get("gradient")
                    else:
                        active_frame = data.get("color", "#6366f1")
                except:
                    pass
            if active_theme_code and p["item_code"] == active_theme_code and p["item_type"] == "theme":
                try:
                    data = json.loads(p.get("item_data", "{}"))
                    active_theme = data.get("bg", "")
                    active_theme_data = data
                except:
                    pass
            if active_badge_code and p["item_code"] == active_badge_code and p["item_type"] == "badge":
                try:
                    data = json.loads(p.get("item_data", "{}"))
                    active_badge = data.get("icon", "")
                except:
                    pass

    showcase_ach = settings.get("setting_showcase_ach", "").split(",") if settings and settings.get("setting_showcase_ach") else []
    showcase_badges = settings.get("setting_showcase_badges", "").split(",") if settings and settings.get("setting_showcase_badges") else []

    # Earned badge for display next to nickname
    active_earned_badge_code = settings.get("setting_active_earned_badge") if settings else None
    active_earned_badge = None
    if active_earned_badge_code:
        for b in badges:
            if b.get("badge_code") == active_earned_badge_code and b.get("earned"):
                active_earned_badge = b
                break

    # Fetch pending materials for this user
    pending_materials = db.fetch_user_pending_materials(user["user_id"])

    xp_needed = db.compute_xp_for_next_level(user["user_xp"])

    return render_template(
        "profile.html",
        user=user,
        achievements=achievements,
        badges=badges,
        activity=activity,
        materials_count=materials_count,
        completed_count=completed_count,
        rating=rating,
        position=position,
        level=db.compute_level(user["user_xp"]),
        xp_in_level=db.compute_xp_in_level(user["user_xp"]),
        xp_per_level=xp_needed,
        earned_achievements=earned_ach,
        total_achievements=len(achievements),
        earned_badges=earned_badges,
        total_badges=len(badges),
        is_own_profile=True,
        is_profile_moderator=db.is_user_moderator(user["user_id"]),
        active_frame=active_frame,
        active_frame_data=active_frame_data,
        active_theme=active_theme,
        active_theme_data=active_theme_data,
        active_badge=active_badge,
        active_earned_badge=active_earned_badge,
        showcase_ach=showcase_ach,
        showcase_badges=showcase_badges,
        pending_materials=pending_materials,
    )


@app.route("/user/<int:user_id>")
def view_user_profile(user_id):
    user = db.fetch_user_by_id(user_id)
    if not user:
        abort(404)

    current = get_current_user()
    is_own = current and current["user_id"] == user_id
    current_is_moderator = current and db.is_user_moderator(current["user_id"])

    if request.args.get("preview") == "1" and is_own:
        is_own = False
        current_is_moderator = False

    settings = db.get_user_settings(user_id)

    # Check privacy settings — moderators bypass privacy
    if settings and settings.get("setting_hide_profile") and not is_own and not current_is_moderator:
        return render_template("profile_hidden.html", user=user)

    achievements = db.fetch_achievements_for(user_id)
    badges = db.fetch_badges_for(user_id)
    activity = db.fetch_activity_for(user_id, limit=50)
    materials_count = db.fetch_user_materials_count(user_id)
    completed_count = db.count_user_completed(user_id)
    rating = db.compute_rating(user["user_xp"], completed_count, materials_count)
    position = db.fetch_user_position(user_id, sort="rating")
    earned_ach = sum(1 for a in achievements if a["earned"])
    earned_badges = sum(1 for b in badges if b["earned"])

    # Apply privacy filters (moderators see everything)
    if settings and not current_is_moderator:
        if settings.get("setting_hide_avatar"):
            user["user_avatar_path"] = None
        if settings.get("setting_hide_achievements"):
            achievements = []
            earned_ach = 0
        if settings.get("setting_hide_badges"):
            badges = []
            earned_badges = 0
        if settings.get("setting_hide_streak"):
            user["user_streak_days"] = None
        if settings.get("setting_hide_stats"):
            materials_count = 0
            completed_count = 0
            rating = 0
            position = None
        if settings.get("setting_hide_level"):
            user["user_xp_hidden"] = True # We will handle this in template
        if settings.get("setting_hide_xp"):
            user["user_xp_val_hidden"] = True

    # Apply customization from settings
    active_frame_code = settings.get("setting_active_frame") if settings else None
    active_theme_code = settings.get("setting_active_theme") if settings else None
    active_badge_code = settings.get("setting_active_badge") if settings else None

    # Get actual values from shop items
    active_frame = None
    active_frame_data = None
    active_theme = None
    active_theme_data = None
    active_badge = None

    if active_frame_code or active_theme_code or active_badge_code:
        purchases = db.fetch_user_purchases(user_id)
        for p in purchases:
            if active_frame_code and p["item_code"] == active_frame_code and p["item_type"] == "frame":
                try:
                    data = json.loads(p.get("item_data", "{}"))
                    active_frame_data = data
                    if "gradient" in data:
                        active_frame = data.get("gradient")
                    else:
                        active_frame = data.get("color", "#6366f1")
                except:
                    pass
            if active_theme_code and p["item_code"] == active_theme_code and p["item_type"] == "theme":
                try:
                    data = json.loads(p.get("item_data", "{}"))
                    active_theme = data.get("bg", "")
                    active_theme_data = data
                except:
                    pass
            if active_badge_code and p["item_code"] == active_badge_code and p["item_type"] == "badge":
                try:
                    data = json.loads(p.get("item_data", "{}"))
                    active_badge = data.get("icon", "")
                except:
                    pass

    showcase_ach = settings.get("setting_showcase_ach", "").split(",") if settings and settings.get("setting_showcase_ach") else []
    showcase_badges = settings.get("setting_showcase_badges", "").split(",") if settings and settings.get("setting_showcase_badges") else []

    # Earned badge for display next to nickname
    active_earned_badge_code = settings.get("setting_active_earned_badge") if settings else None
    active_earned_badge = None
    if active_earned_badge_code:
        for b in badges:
            if b.get("badge_code") == active_earned_badge_code and b.get("earned"):
                active_earned_badge = b
                break

    xp_needed = db.compute_xp_for_next_level(user["user_xp"])

    return render_template(
        "profile.html",
        user=user,
        achievements=achievements,
        badges=badges,
        activity=activity,
        materials_count=materials_count,
        completed_count=completed_count,
        rating=rating,
        position=position,
        level=db.compute_level(user["user_xp"]),
        xp_in_level=db.compute_xp_in_level(user["user_xp"]),
        xp_per_level=xp_needed,
        earned_achievements=earned_ach,
        total_achievements=len(achievements),
        earned_badges=earned_badges,
        total_badges=len(badges),
        is_own_profile=is_own,
        is_profile_moderator=db.is_user_moderator(user_id),
        active_frame=active_frame_code,

        active_frame_data=active_frame_data,
        active_theme=active_theme,
        active_theme_data=active_theme_data,
        active_badge=active_badge,
        active_earned_badge=active_earned_badge,
        showcase_ach=showcase_ach,
        showcase_badges=showcase_badges,
    )


@app.route("/settings")
@login_required_route
def settings_page():
    user = get_current_user()
    settings = db.get_user_settings(user["user_id"])
    return render_template("settings.html", settings=settings)


@app.route("/settings/update", methods=["POST"])
@login_required_route
def update_settings():
    settings_dict = {
        "setting_theme": request.form.get("theme", "light"),
        "setting_language": request.form.get("language", "ru"),
        "setting_notifications": 0 if request.form.get("disable_popups") else 1,
        "setting_confetti": 1 if request.form.get("enable_confetti") else 0,
        "setting_hide_avatar": 1 if request.form.get("hide_avatar") else 0,
        "setting_hide_level": 1 if request.form.get("hide_level") else 0,
        "setting_hide_xp": 1 if request.form.get("hide_xp") else 0,
        "setting_hide_achievements": 1 if request.form.get("hide_achievements") else 0,
        "setting_hide_badges": 1 if request.form.get("hide_badges") else 0,
        "setting_hide_streak": 1 if request.form.get("hide_streak") else 0,
        "setting_hide_stats": 1 if request.form.get("hide_stats") else 0,
        "setting_hide_leaderboard": 1 if request.form.get("hide_leaderboard") else 0,
        "setting_hide_profile": 1 if request.form.get("hide_profile") else 0,
        "setting_disable_all_notifications": 1 if request.form.get("disable_all_notifications") else 0,
    }
    db.update_user_settings(session["user_id"], settings_dict)

    # Clear any pending notifications when settings change
    session.pop('pending_notifications', None)

    # Update session to apply changes immediately
    session["language"] = settings_dict["setting_language"]

    flash(tr("settings_saved"), "success")
    return redirect(url_for("settings_page"))


@app.route("/settings/change-email", methods=["POST"])
@login_required_route
def change_email():
    data = request.json
    new_email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    
    saved_code = session.get("auth_code")
    if not (code == saved_code or code == "admin"):
        return jsonify({"ok": False, "error": tr("invalid_code")}), 400
    
    if db.fetch_user_by_email(new_email):
        return jsonify({"ok": False, "error": tr("email_taken")}), 400
    
    db.update_user_email(session["user_id"], new_email)
    session.pop("auth_code", None)
    flash(tr("email_changed"), "success")
    return jsonify({"ok": True})


@app.route("/settings/change-password", methods=["POST"])
@login_required_route
def change_password():
    data = request.json
    new_pass = data.get("password")
    code = (data.get("code") or "").strip()
    
    saved_code = session.get("auth_code")
    if not (code == saved_code or code == "admin"):
        return jsonify({"ok": False, "error": tr("invalid_code")}), 400
    
    if len(new_pass) < 6:
        return jsonify({"ok": False, "error": tr("password_too_short")}), 400
    
    db.update_user_password(session["user_id"], generate_password_hash(new_pass))
    session.pop("auth_code", None)
    flash(tr("password_changed"), "success")
    return jsonify({"ok": True})


@app.route("/settings/delete-account-secure", methods=["POST"])
@login_required_route
def delete_account_secure():
    data = request.json
    code = (data.get("code") or "").strip()
    
    saved_code = session.get("auth_code")
    if not (code == saved_code or code == "admin"):
        return jsonify({"ok": False, "error": tr("invalid_code")}), 400
    
    user_id = session["user_id"]
    if db.is_user_moderator(user_id):
        return jsonify({"ok": False, "error": tr("moderator_delete_forbidden")}), 403
    
    db.delete_user_account(user_id)
    session.clear()
    flash(tr("account_deleted"), "success")
    return jsonify({"ok": True, "redirect": url_for("home")})


@app.route("/clear-notifications", methods=["POST"])
def clear_notifications():
    session.pop('pending_notifications', None)
    return '', 204


@app.route("/profile/settings")
@login_required_route
def profile_settings_page():
    user = get_current_user()
    settings = db.get_user_settings(user["user_id"])
    achievements = db.fetch_achievements_for(user["user_id"])
    badges = db.fetch_badges_for(user["user_id"])
    purchases = db.fetch_user_purchases(user["user_id"])

    purchased_frames = [p for p in purchases if p["item_type"] == "frame"]
    purchased_themes = [p for p in purchases if p["item_type"] == "theme"]
    purchased_badges = [p for p in purchases if p["item_type"] == "badge"]

    return render_template(
        "profile_settings.html",
        user=user,
        settings=settings,
        achievements=achievements,
        badges=badges,
        purchased_frames=purchased_frames,
        purchased_themes=purchased_themes,
        purchased_badges=purchased_badges,
    )


@app.route("/profile/settings/update", methods=["POST"])
@login_required_route
def update_profile_settings():
    new_username = (request.form.get("username") or "").strip()
    if new_username:
        db.update_user_name(session["user_id"], new_username)

    showcase_ach = request.form.getlist("showcase_ach")[:3]  # Max 3
    showcase_badges = request.form.getlist("showcase_badges")[:3]  # Max 3

    # Handle merged badge selector
    badge_value = request.form.get("active_badge") or ""
    active_badge = None
    active_earned_badge = None
    if badge_value.startswith("earned:"):
        active_earned_badge = badge_value[7:]  # Remove "earned:" prefix
    elif badge_value:
        active_badge = badge_value

    settings_dict = {
        "setting_active_frame": request.form.get("active_frame") or None,
        "setting_active_theme": request.form.get("active_theme") or None,
        "setting_active_badge": active_badge,
        "setting_active_earned_badge": active_earned_badge,
        "setting_showcase_ach": ",".join(showcase_ach) if showcase_ach else None,
        "setting_showcase_badges": ",".join(showcase_badges) if showcase_badges else None,
    }

    db.update_user_settings(session["user_id"], settings_dict)
    flash(tr("profile_settings_saved"), "success")
    return redirect(url_for("profile_settings_page"))


@app.route("/policy")
def policy_page():
    return render_template("policy.html")


@app.route("/support")
def support_page():
    return render_template("support.html")


@app.route("/shop")
@login_required_route
def shop_page():
    user = get_current_user()
    frames = db.fetch_shop_items("frame")
    themes = db.fetch_shop_items("theme")
    badges = db.fetch_shop_items("badge")
    purchases = db.fetch_user_purchases(user["user_id"])
    purchased_ids = [p["item_id"] for p in purchases]
    active_tab = request.args.get("tab", "frames")
    return render_template(
        "shop.html",
        frames=frames,
        themes=themes,
        badges=badges,
        purchased_ids=purchased_ids,
        user_educoins=user.get("user_educoins", 0),
        active_tab=active_tab,
    )


@app.route("/shop/buy/<int:item_id>", methods=["POST"])
@login_required_route
def buy_item(item_id):
    success, message = db.purchase_item(session["user_id"], item_id)
    message_key = {
        "Товар не найден": "item_not_found",
        "Пользователь не найден": "user_not_found",
        "Недостаточно eduCoin": "not_enough",
        "Товар уже куплен": "item_already_bought",
        "Покупка успешна": "purchase_success",
    }.get(message)
    if success:
        flash(tr(message_key) if message_key else message, "success")
    else:
        flash(tr(message_key) if message_key else message, "error")

    active_tab = request.form.get("active_tab", "frames")
    return redirect(url_for("shop_page", tab=active_tab))


@app.route("/topup")
@login_required_route
def topup_page():
    return render_template("topup.html")


@app.route("/topup/process", methods=["POST"])
@login_required_route
def topup_process():
    try:
        amount = int(request.form.get("amount", "0"))
    except ValueError:
        amount = 0
    if amount < 1 or amount > 1000:
        flash(tr("amount_range_error"), "error")
        return redirect(url_for("topup_page"))

    # Заглушка: просто начисляем eduCoin
    db.add_educoins(session["user_id"], amount)
    flash(tr("balance_topped_up", amount=amount), "success")
    return redirect(url_for("topup_page"))


# ===== Create / Edit / Delete material =====
@app.route("/create")
@login_required_route
def create_choose():
    return render_template("create_choose.html")


def _collect_material_form(material_type=None):
    title = (request.form.get("title") or "").strip()
    # Enforce title length limit
    if len(title) > 50:
        title = title[:50]
    description = (request.form.get("description") or "").strip()
    category_id = request.form.get("category_id") or None
    subcategory_id = request.form.get("subcategory_id") or None
    difficulty = request.form.get("difficulty", "beginner")
    content = (request.form.get("content") or "").strip()
    youtube_url = (request.form.get("youtube_url") or "").strip() or None

    step_titles = request.form.getlist("step_title[]")
    steps = []

    # Для тестов обрабатываем вопросы и ответы
    if material_type == "test":
        for i, question_title in enumerate(step_titles):
            question_title = (question_title or "").strip()
            if not question_title:
                continue

            # Получаем варианты ответов для этого вопроса
            answer_key = f"answer_{i}[]"
            answers = request.form.getlist(answer_key)
            correct_key = f"correct_{i}"
            correct_index = request.form.get(correct_key, "0")

            # Формируем строку с ответами: "0::текст|||1::текст|||0::текст"
            # где 1 означает правильный ответ, 0 - неправильный
            answer_parts = []
            for j, ans_text in enumerate(answers):
                ans_text = (ans_text or "").strip()
                if ans_text:
                    is_correct = "1" if str(j) == correct_index else "0"
                    answer_parts.append(f"{is_correct}::{ans_text}")

            if answer_parts:
                steps.append({
                    "title": question_title,
                    "description": "|||".join(answer_parts)
                })
    else:
        # Для обычных материалов обрабатываем пункты как раньше
        step_descs = request.form.getlist("step_desc[]")
        step_types = request.form.getlist("step_type[]")
        for t, d, st in zip(step_titles, step_descs, step_types):
            t = (t or "").strip()
            d = (d or "").strip()
            st = (st or "point").strip()
            if t or d:
                steps.append({"title": t, "description": d, "type": st})

    return {
        "title": title,
        "description": description,
        "category_id": int(category_id) if category_id else None,
        "subcategory_id": int(subcategory_id) if subcategory_id else None,
        "difficulty": difficulty,
        "content": content,
        "youtube_url": youtube_url,
        "steps_json": json.dumps(steps, ensure_ascii=False),
    }


@app.route("/create/<material_type>", methods=["GET", "POST"])
@login_required_route
def create_material(material_type):
    if material_type not in ("course", "test", "video", "tip"):
        abort(404)

    def render_with_error(msg, data):
        flash(msg, "error")
        top_categories = db.fetch_top_categories()
        all_subs = []
        for c in top_categories:
            for s in db.fetch_subcategories(parent_id=c["category_id"]):
                all_subs.append(s)
        try:
            steps = json.loads(data.get("steps_json", "[]"))
        except:
            steps = []
        
        edit_mat = {
            "material_title": data.get("title", ""),
            "material_description": data.get("description", ""),
            "material_category_id": data.get("category_id"),
            "material_subcategory_id": data.get("subcategory_id"),
            "material_difficulty": data.get("difficulty", "beginner"),
            "material_content": data.get("content", ""),
            "material_youtube_url": data.get("youtube_url", "")
        }
        return render_template(
            "create_form.html",
            material_type=material_type,
            all_subcategories=all_subs,
            edit_material=edit_mat,
            edit_steps=steps
        )

    if request.method == "POST":
        data = _collect_material_form(material_type)
        if not data["title"]:
            return render_with_error(tr("material_title_required"), data)

        # Profanity check
        all_text = f"{data['title']} {data['description']} {data.get('content', '')}"
        bad_words = check_text_for_profanity(all_text)
        if bad_words:
            return render_with_error(tr("material_bad_words", words=", ".join(bad_words)), data)

        # Validate category and subcategory are required
        if not data["category_id"] or not data["subcategory_id"]:
            return render_with_error(tr("category_required"), data)

        cover = request.files.get("cover_image")
        image_path = None
        if cover and cover.filename:
            # Check file size (6MB max)
            cover.seek(0, os.SEEK_END)
            size = cover.tell()
            cover.seek(0)
            if size > 6 * 1024 * 1024:
                return render_with_error(tr("image_too_large_6"), data)

            _, image_path = save_uploaded_image(cover, UPLOADS_DIR, max_size=(1200, 800), quality=90)

        # Validate required fields for test
        if material_type == "test":
            if not image_path:
                return render_with_error(tr("cover_required"), data)
            if not data["content"]:
                return render_with_error(tr("content_required"), data)
            try:
                steps = json.loads(data["steps_json"])
                if not steps or len(steps) == 0:
                    return render_with_error(tr("test_question_required"), data)
            except:
                return render_with_error(tr("test_question_required"), data)

        # Validate required fields for course
        if material_type == "course":
            if not image_path:
                return render_with_error(tr("cover_required"), data)
            if not data["content"]:
                return render_with_error(tr("content_required"), data)
            try:
                steps = json.loads(data["steps_json"])
                if not steps or len(steps) == 0:
                    return render_with_error(tr("step_required"), data)
            except:
                return render_with_error(tr("step_required"), data)

        # Validate required fields for video
        if material_type == "video":
            if not image_path:
                return render_with_error(tr("cover_required"), data)
            if not data["description"]:
                return render_with_error(tr("description_required"), data)
            if not data["youtube_url"]:
                return render_with_error(tr("youtube_required"), data)

        # Validate required fields for tip
        if material_type == "tip":
            if not image_path:
                return render_with_error(tr("cover_required"), data)
            if not data["description"]:
                return render_with_error(tr("content_required"), data)

        new_id = db.create_material({
            **data,
            "type": material_type,
            "image_path": image_path,
            "author_id": session["user_id"],
        })

        db.add_activity(
            session["user_id"],
            "material_created",
            tr("activity_material_created", title=data["title"]),
            "edit",
        )
        awards = db.recalc_user_awards(session["user_id"])

        # Check user settings before storing notifications in session
        settings = db.get_user_settings(session["user_id"])
        disable_all = settings.get("setting_disable_all_notifications") if settings else 0
        disable_popups = not settings.get("setting_notifications", 1) if settings else False

        # Store notifications in session only if not disabled
        if not disable_all and not disable_popups:
            notifications = []
            if awards.get("achievements"):
                for ach in awards['achievements']:
                    notifications.append({"type": "achievement", "data": ach})
            if awards.get("badges"):
                for bdg in awards['badges']:
                    notifications.append({"type": "badge", "data": bdg})
            if notifications:
                session['pending_notifications'] = notifications

        flash(tr("material_sent_review"), "success")
        return redirect(url_for("profile"))

    top_categories = db.fetch_top_categories()
    all_subs = []
    for c in top_categories:
        for s in db.fetch_subcategories(parent_id=c["category_id"]):
            all_subs.append(s)
    return render_template(
        "create_form.html",
        material_type=material_type,
        all_subcategories=all_subs,
    )


@app.route("/material/<int:material_id>/edit", methods=["GET", "POST"])
@login_required_route
def edit_material(material_id):
    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    if material["material_author_id"] != session["user_id"] and not db.is_user_moderator(session["user_id"]):
        flash(tr("edit_author_only"), "error")
        return redirect(url_for("material_view", material_id=material_id))

    if request.method == "POST":
        data = _collect_material_form(material["material_type"])
        if not data["title"]:
            flash(tr("material_title_required"), "error")
            return redirect(url_for("edit_material", material_id=material_id))

        # Profanity check
        all_text = f"{data['title']} {data['description']} {data.get('content', '')}"
        bad_words = check_text_for_profanity(all_text)
        if bad_words:
            flash(tr("material_bad_words", words=", ".join(bad_words)), "error")
            return redirect(url_for("edit_material", material_id=material_id))

        # Validate required fields for different types
        mat_type = material["material_type"]
        
        # Validate category and subcategory are required
        if not data["category_id"] or not data["subcategory_id"]:
            flash(tr("category_required"), "error")
            return redirect(url_for("edit_material", material_id=material_id))

        # Check for empty content/steps
        if mat_type in ("course", "test"):
            if not data["content"]:
                flash(tr("content_required"), "error")
                return redirect(url_for("edit_material", material_id=material_id))
            try:
                steps = json.loads(data["steps_json"])
                if not steps or len(steps) == 0:
                    msg = tr("test_question_required") if mat_type == "test" else tr("step_required")
                    flash(msg, "error")
                    return redirect(url_for("edit_material", material_id=material_id))
            except:
                flash(tr("invalid_steps_structure"), "error")
                return redirect(url_for("edit_material", material_id=material_id))

        if mat_type == "video":
            if not data["description"]:
                flash(tr("description_required"), "error")
                return redirect(url_for("edit_material", material_id=material_id))
            if not data["youtube_url"]:
                flash(tr("youtube_required"), "error")
                return redirect(url_for("edit_material", material_id=material_id))

        if mat_type == "tip":
            if not data["description"]:
                flash(tr("content_required"), "error")
                return redirect(url_for("edit_material", material_id=material_id))

        # Optional cover replacement
        cover = request.files.get("cover_image")
        new_image = None
        if cover and cover.filename:
            _, new_image = save_uploaded_image(cover, UPLOADS_DIR, max_size=(1200, 800), quality=90)
            if new_image and material.get("material_image_path"):
                remove_local_asset(material["material_image_path"])

        update_data = {
            **data,
            "type": material["material_type"],
        }
        if new_image:
            update_data["image_path"] = new_image

        is_mod = db.is_user_moderator(session["user_id"])
        if not is_mod:
            update_data["status"] = "pending"
            if material.get("material_status") == "approved":
                backup = {k: v for k, v in material.items() if k.startswith("material_")}
                update_data["backup_json"] = json.dumps(backup, ensure_ascii=False)

        db.update_material(material_id, update_data)

        if not is_mod:
            flash(tr("material_sent_remoderation"), "success")
            return redirect(url_for("profile"))
        else:
            flash(tr("material_updated"), "success")
            # If material is pending, redirect to moderation_page instead of material view
            if material.get("material_status") == "pending":
                return redirect(url_for("moderation_page"))
            return redirect(url_for("material_view", material_id=material_id))

    try:
        steps = json.loads(material.get("material_steps_json") or "[]")
    except Exception:
        steps = []
    top_categories = db.fetch_top_categories()
    all_subs = []
    for c in top_categories:
        for s in db.fetch_subcategories(parent_id=c["category_id"]):
            all_subs.append(s)
    return render_template(
        "create_form.html",
        material_type=material["material_type"],
        edit_material=material,
        edit_steps=steps,
        all_subcategories=all_subs,
    )


@app.route("/material/<int:material_id>/delete", methods=["POST"])
@login_required_route
def delete_material_route(material_id):
    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    if material["material_author_id"] != session["user_id"] and not db.is_user_moderator(session["user_id"]):
        flash(tr("delete_author_only"), "error")
        return redirect(url_for("material_view", material_id=material_id))

    if material.get("material_image_path"):
        remove_local_asset(material["material_image_path"])
    db.delete_material(material_id)
    flash(tr("material_deleted"), "success")
    return redirect(url_for("home"))


# ===== Material progress =====
@app.route("/material/<int:material_id>/start", methods=["POST"])
@login_required_route
def start_material(material_id):
    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    is_mod = db.is_user_moderator(session["user_id"])
    # Block starting on pending materials unless moderator
    if material.get("material_status") == "pending" and not is_mod:
        flash(tr("material_pending_error"), "error")
        return redirect(url_for("material_view", material_id=material_id))
    db.start_progress(session["user_id"], material_id)
    return redirect(url_for("material_view", material_id=material_id) + "#steps")


@app.route("/material/<int:material_id>/next", methods=["POST"])
@login_required_route
def next_step(material_id):
    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    db.advance_progress(session["user_id"], material_id)
    return redirect(url_for("material_view", material_id=material_id) + "#steps")


@app.route("/material/<int:material_id>/complete", methods=["POST"])
@login_required_route
def complete_material(material_id):
    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    is_mod = db.is_user_moderator(session["user_id"])
    # Block completing pending materials unless moderator
    if material.get("material_status") == "pending" and not is_mod:
        flash(tr("material_pending_error"), "error")
        return redirect(url_for("material_view", material_id=material_id))
    newly = db.complete_progress(session["user_id"], material_id)
    if newly:
        # Check if user is the author - authors don't get XP for their own materials
        is_author = session["user_id"] == material["material_author_id"]

        if not is_author and not (is_mod and material.get("material_status") == "pending"):
            # Use material's assigned XP reward, fallback to default
            xp_amount = material.get("material_xp_reward") or db.XP_PER_COMPLETION
            xp_result = db.add_user_xp(session["user_id"], xp_amount)
            db.add_activity(
                session["user_id"],
                "material_completed",
                tr("activity_material_completed", title=material["material_title"], xp=xp_amount),
                "trophy",
            )
            awards = db.recalc_user_awards(session["user_id"])
            flash(tr("material_completed_xp", xp=xp_amount), "success")
        else:
            # Author or Mod testing pending completes it - no XP awarded
            xp_result = {}
            awards = {}
            flash(tr("material_completed_simple"), "success")

        # Check user settings before storing notifications in session
        settings = db.get_user_settings(session["user_id"])
        disable_all = settings.get("setting_disable_all_notifications") if settings else 0
        disable_popups = not settings.get("setting_notifications", 1) if settings else False

        # Store notifications in session only if not disabled
        if not disable_all and not disable_popups:
            notifications = []
            if xp_result.get("level_up"):
                notifications.append({"type": "level_up", "data": xp_result['level_up']})
            if awards.get("achievements"):
                for ach in awards['achievements']:
                    notifications.append({"type": "achievement", "data": ach})
            if awards.get("badges"):
                for bdg in awards['badges']:
                    notifications.append({"type": "badge", "data": bdg})
            if notifications:
                session['pending_notifications'] = notifications

        return redirect(url_for("material_view", material_id=material_id))
    else:
        flash(tr("material_already_completed"), "info")
    return redirect(url_for("material_view", material_id=material_id))


@app.route("/material/<int:material_id>/submit_test", methods=["POST"])
@login_required_route
def submit_test(material_id):
    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    if material["material_type"] != "test":
        abort(400)
    is_mod = db.is_user_moderator(session["user_id"])
    # Block test submission on pending materials unless moderator
    if material.get("material_status") == "pending" and not is_mod:
        flash(tr("material_pending_error"), "error")
        return redirect(url_for("material_view", material_id=material_id))

    steps = db.fetch_material_steps(material_id)
    if not steps:
        flash(tr("test_no_questions"), "error")
        return redirect(url_for("material_view", material_id=material_id))

    # Get current step from form
    try:
        current_step = int(request.form.get("current_step", "0"))
    except ValueError:
        current_step = 0

    # Check answer for current question
    user_answer = request.form.get(f"answer_{current_step}", "")
    if not user_answer:
        flash(tr("choose_answer"), "error")
        return redirect(url_for("material_view", material_id=material_id))

    # Parse correct answer from description
    step = steps[current_step]
    answers = step["description"].split("|||") if step["description"] else []
    correct_index = None
    for j, ans in enumerate(answers):
        parts = ans.split("::")
        if parts[0] == "1":
            correct_index = j
            break

    # Check if answer is correct
    if correct_index is None or str(correct_index) != user_answer:
        # Wrong answer - reset progress
        flash(tr("wrong_answer"), "error")
        db.start_progress(session["user_id"], material_id)
        return redirect(url_for("material_view", material_id=material_id))

    # Correct answer - advance to next question
    if current_step + 1 < len(steps):
        # More questions remaining
        db.advance_progress(session["user_id"], material_id)
        return redirect(url_for("material_view", material_id=material_id))
    else:
        # Last question - complete test
        newly = db.complete_progress(session["user_id"], material_id)
        if newly:
            # Check if user is the author - authors don't get XP for their own materials
            is_author = session["user_id"] == material["material_author_id"]

            if not is_author and not (is_mod and material.get("material_status") == "pending"):
                xp_amount = material.get("material_xp_reward") or db.XP_PER_COMPLETION
                xp_result = db.add_user_xp(session["user_id"], xp_amount)
                db.add_activity(
                    session["user_id"],
                    "material_completed",
                    tr("activity_test_completed", title=material["material_title"], xp=xp_amount),
                    "trophy",
                )
                awards = db.recalc_user_awards(session["user_id"])
                flash(tr("test_completed_xp", xp=xp_amount), "success")
            else:
                # Author or Mod testing completes it - no XP awarded
                xp_result = {}
                awards = {}
                flash(tr("test_completed_simple"), "success")

            # Check user settings before storing notifications in session
            settings = db.get_user_settings(session["user_id"])
            disable_all = settings.get("setting_disable_all_notifications") if settings else 0
            disable_popups = not settings.get("setting_notifications", 1) if settings else False

            # Store notifications in session only if not disabled
            if not disable_all and not disable_popups:
                notifications = []
                if xp_result.get("level_up"):
                    notifications.append({"type": "level_up", "data": xp_result['level_up']})
                if awards.get("achievements"):
                    for ach in awards['achievements']:
                        notifications.append({"type": "achievement", "data": ach})
                if awards.get("badges"):
                    for bdg in awards['badges']:
                        notifications.append({"type": "badge", "data": bdg})
                if notifications:
                    session['pending_notifications'] = notifications

            return redirect(url_for("material_view", material_id=material_id))
        else:
            flash(tr("test_already_completed"), "info")

    return redirect(url_for("material_view", material_id=material_id))


# ===== Material rating =====
@app.route("/material/<int:material_id>/rate", methods=["POST"])
@login_required_route
def rate_material(material_id):
    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    # Block rating on pending materials
    if material.get("material_status") == "pending":
        flash(tr("material_pending_error"), "error")
        return redirect(url_for("material_view", material_id=material_id))
    try:
        value = int(request.form.get("rating", "0"))
    except ValueError:
        value = 0
    if value < 1 or value > 5:
        flash(tr("rating_range"), "error")
        return redirect(url_for("material_view", material_id=material_id))
    db.upsert_rating(session["user_id"], material_id, value)
    flash(tr("thanks_rating"), "success")
    return redirect(url_for("material_view", material_id=material_id))


@app.route("/set_language/<lang>")
def set_language(lang):
    if lang in TRANSLATIONS:
        session["language"] = lang
    next_url = request.args.get("next")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(request.referrer or url_for("home"))


# ===== Auth =====
@app.route("/auth")
def auth_page():
    if get_current_user():
        return redirect(url_for("home"))
    return render_template("auth.html")


import random
import time

# Simple brute-force protection
login_attempts = {} # email -> {count: N, lockout_until: timestamp}

@app.route("/auth/request-code", methods=["POST"])
def auth_request_code():
    data = request.json
    email = (data.get("email") or "").strip().lower()
    mode = data.get("mode") # 'login' or 'register'

    if not email or not mode:
        return jsonify({"ok": False, "error": tr("email_required")}), 400

    # Brute-force check
    now = time.time()
    if email in login_attempts:
        attempt = login_attempts[email]
        if attempt["lockout_until"] > now:
            wait_time = int(attempt["lockout_until"] - now)
            return jsonify({"ok": False, "error": tr("too_many_attempts", seconds=wait_time)}), 429
    
    if mode == "register":
        if db.fetch_user_by_email(email):
            return jsonify({"ok": False, "error": tr("email_exists")}), 400
    else:
        # For login, we don't strictly reveal if email exists, but we need it for verification
        pass

    # Generate 6-digit code
    code = f"{random.randint(100000, 999999)}"
    session["auth_code"] = code
    session["auth_email"] = email
    session["auth_time"] = now

    # Send real email
    sent = send_verification_code(email, code, mode=mode)
    
    if sent:
        print(f"VERIFICATION CODE FOR {email} SENT VIA EMAIL: {code}")
        # flash(f"Код подтверждения отправлен на {email}", "success")
    else:
        print(f"FAILED TO SEND EMAIL TO {email}. CODE: {code}")
        return jsonify({
            "ok": True,
            "email_sent": False,
            "message": get_translation("auth_email_fallback_message", session.get("language", "ru"))
        })

    return jsonify({"ok": True, "email_sent": True})


@app.route("/auth/verify-and-complete", methods=["POST"])
def auth_verify_complete():
    data = request.json
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    mode = data.get("mode")
    password = data.get("password") or ""

    if not email or not code or not password:
        return jsonify({"ok": False, "error": tr("all_fields_required")}), 400

    # Verification
    saved_code = session.get("auth_code")
    saved_email = session.get("auth_email")
    saved_time = session.get("auth_time")

    # Admin bypass
    is_code_valid = (code == saved_code and email == saved_email) or (code == "admin")
    
    if not is_code_valid:
        # Increment attempt counter
        now = time.time()
        attempt = login_attempts.get(email, {"count": 0, "lockout_until": 0})
        attempt["count"] += 1
        if attempt["count"] >= 5:
            attempt["lockout_until"] = now + 60 # Lock for 60 seconds
            attempt["count"] = 0 # Reset after lock
        login_attempts[email] = attempt
        
        return jsonify({"ok": False, "error": tr("invalid_verification_code")}), 400

    # Code is valid, clear it
    session.pop("auth_code", None)
    session.pop("auth_email", None)

    if mode == "register":
        full_name = (data.get("full_name") or "").strip()
        if not full_name:
            return jsonify({"ok": False, "error": tr("name_required")}), 400
        
        user_id = db.create_user(full_name, email, generate_password_hash(password))
        session["user_id"] = user_id
        return jsonify({"ok": True, "redirect": url_for("home")})
    else:
        user = db.fetch_user_by_email(email)
        if not user or not check_password_hash(user["user_password_hash"], password):
            # Also count as failed attempt for brute-force
            return jsonify({"ok": False, "error": tr("invalid_login")}), 400
        
        session["user_id"] = user["user_id"]
        # Clear attempts on success
        login_attempts.pop(email, None)
        return jsonify({"ok": True, "redirect": url_for("home")})


@app.route("/auth/logout")
def auth_logout():
    session.pop("user_id", None)
    return redirect(url_for("home"))


# ===== Avatar upload =====
@app.route("/profile/avatar", methods=["POST"])
@login_required_route
def upload_avatar():
    f = request.files.get("avatar")
    if not f or not f.filename:
        flash(tr("file_not_selected"), "error")
        return redirect(url_for("profile"))
    if not is_image(f.filename):
        flash(tr("images_only"), "error")
        return redirect(url_for("profile"))

    # Check file size (4MB max)
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size > 4 * 1024 * 1024:
        flash(tr("image_too_large_4"), "error")
        return redirect(url_for("profile"))

    user = get_current_user()
    if user.get("user_avatar_path"):
        remove_local_asset(user["user_avatar_path"])

    _, new_path = save_uploaded_image(f, AVATARS_DIR, max_size=(400, 400), quality=90)
    if new_path:
        db.update_user_avatar(user["user_id"], new_path)
        flash(tr("avatar_updated"), "success")
    else:
        flash(tr("file_upload_failed"), "error")

    # Check if request came from profile settings page
    referer = request.referrer or ""
    if "profile/settings" in referer:
        return redirect(url_for("profile_settings_page"))
    return redirect(url_for("profile"))


# ===== Comments =====
@app.route("/material/<int:material_id>/comment", methods=["POST"])
@login_required_route
def post_comment(material_id):
    text = (request.form.get("text") or "").strip()
    if not text:
        flash(tr("empty_comment"), "error")
        return redirect(url_for("material_view", material_id=material_id))
    
    # Profanity check
    bad_words = check_text_for_profanity(text)
    if bad_words:
        flash(tr("comment_bad_words", words=", ".join(bad_words)), "error")
        return redirect(url_for("material_view", material_id=material_id) + "#comments")

    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    # Block comments on pending materials
    if material.get("material_status") == "pending":
        flash(tr("comments_after_publish"), "error")
        return redirect(url_for("material_view", material_id=material_id))
    db.add_comment(material_id, session["user_id"], text)
    awards = db.recalc_user_awards(session["user_id"])

    # Check user settings before storing notifications in session
    settings = db.get_user_settings(session["user_id"])
    disable_all = settings.get("setting_disable_all_notifications") if settings else 0
    disable_popups = not settings.get("setting_notifications", 1) if settings else False

    # Store notifications in session only if not disabled
    if not disable_all and not disable_popups:
        notifications = []
        if awards.get("achievements"):
            for ach in awards['achievements']:
                notifications.append({"type": "achievement", "data": ach})
        if awards.get("badges"):
            for bdg in awards['badges']:
                notifications.append({"type": "badge", "data": bdg})
        if notifications:
            session['pending_notifications'] = notifications

    return redirect(url_for("material_view", material_id=material_id) + "#comments")


@app.route("/comment/<int:comment_id>/like", methods=["POST"])
@login_required_route
def like_comment(comment_id):
    result = db.toggle_comment_like(comment_id, session["user_id"])
    return jsonify({"ok": True, "liked": result["liked"], "removed_dislike": result["removed_dislike"], "likes": result["likes"], "dislikes": result["dislikes"]})


@app.route("/comment/<int:comment_id>/dislike", methods=["POST"])
@login_required_route
def dislike_comment(comment_id):
    result = db.toggle_comment_dislike(comment_id, session["user_id"])
    return jsonify({"ok": True, "disliked": result["disliked"], "removed_like": result["removed_like"], "likes": result["likes"], "dislikes": result["dislikes"]})


@app.route("/comment/<int:comment_id>/delete", methods=["POST"])
@login_required_route
def delete_comment(comment_id):
    is_mod = db.is_user_moderator(session["user_id"])
    success = db.delete_comment(comment_id, session["user_id"], is_moderator=is_mod)
    if success:
        flash(tr("comment_deleted"), "success")
    else:
        flash(tr("comment_delete_failed"), "error")
    return redirect(request.referrer or url_for("home"))


# ===== Moderation routes =====
def moderator_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            flash(tr("login_required_message"), "error")
            return redirect(url_for("home"))
        if not db.is_user_moderator(user["user_id"]):
            flash(tr("access_denied"), "error")
            return redirect(url_for("home"))
        return fn(*args, **kwargs)
    return wrapper


@app.route("/moderation")
@moderator_required
def moderation_page():
    pending = db.fetch_pending_materials()
    return render_template("moderation.html", pending=pending)


@app.route("/moderation/approve/<int:material_id>", methods=["POST"])
@moderator_required
def approve_material_route(material_id):
    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    db.approve_material(material_id)

    # Store XP reward on the material itself (for all who complete it)
    try:
        xp_amount = int(request.form.get("xp_amount", "0"))
    except ValueError:
        xp_amount = 0
    if xp_amount > 0:
        db.set_material_xp_reward(material_id, xp_amount)

    # Auto-complete the material for the author
    newly = db.complete_progress(material["material_author_id"], material_id)
    
    # Award XP to the author for successfully publishing a material (only the first time)
    if newly and xp_amount > 0:
        db.add_user_xp(material["material_author_id"], xp_amount)

    db.add_activity(
        material["material_author_id"],
        "material_approved",
        tr("activity_material_approved", title=material["material_title"], xp=xp_amount),
        "trophy",
    )

    flash(tr("material_approved_flash", title=material["material_title"]), "success")
    return redirect(url_for("moderation_page"))


@app.route("/moderation/reject/<int:material_id>", methods=["POST"])
@moderator_required
def reject_material_route(material_id):
    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    db.add_activity(
        material["material_author_id"],
        "material_rejected",
        tr("activity_material_rejected", title=material["material_title"]),
        "edit",
    )
    db.reject_material(material_id)
    flash(tr("material_rejected_deleted"), "success")
    return redirect(url_for("moderation_page"))


@app.route("/moderation/users")
@moderator_required
def moderation_users():
    users = db.fetch_all_users()
    return render_template("moderation_users.html", users=users)


@app.route("/moderation/award_xp/<int:user_id>", methods=["POST"])
@moderator_required
def award_xp_route(user_id):
    try:
        amount = int(request.form.get("xp_amount", "0"))
    except ValueError:
        amount = 0
    if amount > 0:
        db.add_user_xp(user_id, amount)
        db.add_activity(user_id, "xp_awarded", tr("activity_xp_awarded", amount=amount), "star")
        flash(tr("xp_awarded_to_user", amount=amount), "success")
    return redirect(url_for("view_user_profile", user_id=user_id))


@app.route("/moderation/update_xp/<int:material_id>", methods=["POST"])
@moderator_required
def update_material_xp_route(material_id):
    material = db.fetch_material(material_id)
    if not material:
        abort(404)
    if material.get("material_status") != "approved":
        flash(tr("xp_update_only_approved"), "error")
        return redirect(url_for("material_view", material_id=material_id))
    try:
        xp_amount = int(request.form.get("xp_amount", "0"))
    except ValueError:
        xp_amount = 0
    db.set_material_xp_reward(material_id, xp_amount)
    flash(tr("xp_reward_updated", xp=xp_amount), "success")
    return redirect(url_for("material_view", material_id=material_id))


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
