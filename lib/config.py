import logging
import sys
import os
from datetime import datetime, timedelta

log_dir = "info" 
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "fb_scraper.log"), encoding='utf-8'),
        logging.StreamHandler(sys.stdout)  # Explicitly use stdout for better Unicode handling
    ]
)
logger = logging.getLogger("fb_scraper")

class ScraperStats:
    def __init__(self):
        self.started_at = datetime.now()
        self.posts_collected = 0
        self.posts_skipped = 0
        self.unique_authors = set()
        self.scrolls = 0
        self.total_runtime = timedelta(seconds=0)
        self.page_loads = 0
        self.retries = 0
        self.throttles = 0
        self.last_saved_at = None
        self.running = True
        
    def update(self):
        self.total_runtime = datetime.now() - self.started_at
        
    def print_summary(self):
        self.update()
        runtime_str = str(self.total_runtime).split('.')[0]  # Remove microseconds
        
        # Calculate rates
        if self.total_runtime.total_seconds() > 0:
            posts_per_hour = (self.posts_collected / self.total_runtime.total_seconds()) * 3600
            scrolls_per_hour = (self.scrolls / self.total_runtime.total_seconds()) * 3600
        else:
            posts_per_hour = scrolls_per_hour = 0
            
        logger.info(f"--- SCRAPER STATISTICS ---")
        logger.info(f"Runtime: {runtime_str}")
        logger.info(f"Posts collected: {self.posts_collected}")
        logger.info(f"Posts skipped: {self.posts_skipped}")
        logger.info(f"Unique authors: {len(self.unique_authors)}")
        logger.info(f"Page loads: {self.page_loads}")
        logger.info(f"Scrolls: {self.scrolls}")
        logger.info(f"Posts per hour: {posts_per_hour:.1f}")
        logger.info(f"Retries: {self.retries}")
        logger.info(f"Throttles: {self.throttles}")
        if self.last_saved_at:
            last_save = datetime.now() - self.last_saved_at
            logger.info(f"Last CSV update: {last_save.total_seconds():.1f}s ago")
        logger.info(f"---------------------------")
