from datetime import datetime
from pathlib import Path

COOKIES_FILE = Path("info\cookies.json")
SCROLL_PAUSE = (0.5, 1.2)  # (min, max) seconds between scrolls, slightly faster
SCROLL_RANDOM_DELAY = (2.5, 7.0)  # Occasional longer pauses to appear human-like
RETRY_DELAY = (1.0, 3.0)  # (min, max) seconds between retries
MAX_RETRIES = 3
RESULTS_DIR = Path("collected_data")
RESULTS_DIR.mkdir(exist_ok=True)

# Stats tracking
START_TIME = datetime.now()
CSV_HEADERS = ["post_id", "author_name", "author_profile", "timestamp", "content", 
              "reactions", "comments", "shares", "total_engagement", "url", "scrape_time"]

# Facebook post selectors - multiple options to increase reliability
POST_SELECTORS = [
    "div[role='article']",
    "div[data-pagelet^='FeedUnit_']",
    "div.x1yztbdb",
    "div.x1n2onr6",
    "div.x78zum5:not([data-visualcompletion='ignore-dynamic'])",  # 2025 markup
    "div.x1lliihq div.x1pi30zi",  # Common feed container
    "[aria-posinset]",  # Feed items with position
    "div.xdj266r:not([aria-hidden='true'])",  # Posts with content not hidden
]

# Block UI elements that are commonly mistaken for posts
BLOCK_SELECTORS = [
    "div[aria-label*='story']",  # Stories section
    "div[data-pagelet='Stories']",
    "div[role='complementary']",  # Sidebar elements
    "div[role='search']",  # Search box
    "div[role='banner']",  # Header/banner
    "div[aria-label*='menu']",  # Menus
    "div[aria-label*='notification']",  # Notification area
]

# Keywords for filtering out UI elements
UI_INDICATORS = [
    "online status indicator", "privacy", "learn more", "sorry", "having trouble",
    "menu", "navigation", "sidebar", "notification", "friend request", 
    "messenger", "chat", "inbox", "has new content", "enter your pin", "loading",
    "feed preferences", "settings", "create", "more options", "search", "help",
    "marketplace", "gaming", "watch", "groups", "events"
]