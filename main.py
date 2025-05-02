"""CLI entry point for Facebook scraper"""

import argparse
import asyncio
import os
import logging

from lib.config import logger
from lib.scraper import FacebookScraper
from lib.utils import stats

async def main():
    parser = argparse.ArgumentParser(description="Advanced Facebook Post Scraper")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--url", type=str, help="Specific Facebook URL to scrape")
    parser.add_argument("--target", type=int, help="Target number of posts to collect")
    parser.add_argument("--debug", action="store_true", help="Show detailed debug information")
    parser.add_argument("--stealth", type=int, default=2, choices=[1, 2, 3], 
                      help="Stealth level (1=basic, 2=medium, 3=maximum)")
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    email = os.getenv("FACEBOOK_EMAIL")
    password = os.getenv("FACEBOOK_PASSWORD")
    
    scraper = FacebookScraper(headless=args.headless, stealth_level=args.stealth)
    
    try:
        await scraper.launch_browser()
        login_success = await scraper.login(email, password)
        if not login_success:
            logger.error("Failed to log in to Facebook")
            return
            
        await scraper.scrape_facebook(url=args.url, target_posts=args.target)
        
    except KeyboardInterrupt:
        logger.info("Scraping interrupted by user")
        stats.print_summary()
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await scraper.close()

if __name__ == "__main__":
    asyncio.run(main())