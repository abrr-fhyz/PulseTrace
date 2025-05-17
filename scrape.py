import os
import logging
import asyncio
from lib.scraper import FacebookScreenshotScraper

async def main():
    """Run the Facebook screenshot scraper."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger('FacebookScraper')
    
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Facebook Screenshot Scraper')
    parser.add_argument('--url', help='Facebook URL to scrape (default: homepage)', default=None)
    parser.add_argument('--target', type=int, help='Number of posts to capture (default: 50)', default=50)
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    parser.add_argument('--stealth', type=int, choices=[1, 2, 3], help='Stealth level (1-3)', default=2)
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # Get credentials from environment variables
    email = os.getenv("FACEBOOK_EMAIL")
    password = os.getenv("FACEBOOK_PASSWORD")
    
    # Run the scraper
    scraper = FacebookScreenshotScraper(headless=args.headless, stealth_level=args.stealth)
    
    try:
        await scraper.launch_browser()
        login_success = await scraper.login(email, password)
        
        if not login_success:
            logger.error("Failed to log in to Facebook")
            return
            
        await scraper.scrape_facebook(url=args.url, target_posts=args.target)
        
    except KeyboardInterrupt:
        logger.info("Scraping interrupted by user")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await scraper.close()

if __name__ == "__main__":
    asyncio.run(main())