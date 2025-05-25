import asyncio
import json
import logging
import random
import time
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('FacebookScraper')

class FacebookScreenshotScraper:
    """Scraper that captures screenshots of Facebook posts instead of parsing them."""
    
    def __init__(self, headless: bool = False, stealth_level: int = 2):
        """Initialize the scraper with configurable stealth level.
        
        Args:
            headless: Whether to run the browser in headless mode
            stealth_level: Level of anti-detection measures (1-3, higher = more stealth)
        """
        self.headless = headless
        self.stealth_level = max(1, min(stealth_level, 3))  # Ensure between 1-3
        self.screenshot_dir = Path("screenshots")
        self.screenshot_dir.mkdir(exist_ok=True)
        self.session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.seen_post_ids = set()
        self.posts_captured = 0
        self.min_post_size = {
            'width': 300,  # Minimum width of a valid post
            'height': 100   # Minimum height of a valid post
        }
        
        # Set up log directory
        log_dir = Path("info")
        log_dir.mkdir(exist_ok=True)
        
        # Add file handler for this session
        file_handler = logging.FileHandler(log_dir / f"fb_scraper_{self.session_id}.log")
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        
    async def launch_browser(self):
        """Launch browser with stealth settings."""
        self.playwright = await async_playwright().start()
        
        # Setup browser arguments for stealth based on selected level
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
        ]
        
        # Add more stealth args based on level
        if self.stealth_level >= 2:
            browser_args.extend([
                "--disable-web-security",
                "--disable-infobars",
                "--disable-notifications",
                "--disable-extensions",
                "--disable-popup-blocking",
                "--disable-automation", 
                "--disable-blink-features",
            ])
            
        if self.stealth_level >= 3:
            browser_args.extend([
                "--disable-canvas-aa",
                "--disable-2d-canvas-clip-aa",
                "--disable-gl-drawing-for-tests",
                "--disable-site-isolation-trials",
            ])
        
        # Launch browser with appropriate config
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=browser_args
        )
        
        # Create a browser context with randomized properties
        self.context = await self.browser.new_context(
            user_agent=self._random_user_agent(),
            viewport={"width": random.randint(1280, 1920), "height": random.randint(800, 1080)},
            locale=random.choice(["en-US", "en-GB", "en-CA"]),
            timezone_id=random.choice(["America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London"]),
            color_scheme=random.choice(["light", "no-preference"]),
            device_scale_factor=random.choice([1, 1.25, 1.5, 2]),
        )
        
        # Apply basic stealth JS patches
        await self.context.add_init_script("""
        () => {
            // Pass WebDriver checks
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });
            
            // Pass Chrome checks
            window.chrome = {
                runtime: {},
                app: { InstallState: 'hehe', RunningState: 'running' },
            };
        }
        """)
        
        # Load cookies if available
        cookies_file = Path("info/cookies.json")
        if cookies_file.exists():
            try:
                with open(cookies_file, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                await self.context.add_cookies(cookies)
                logger.info("Loaded cookies from file")
            except Exception as e:
                logger.error(f"Could not load cookies: {e}")
        
        # Create a new page
        self.page = await self.context.new_page()
        
    def _random_user_agent(self) -> str:
        """Generate realistic modern browser user-agent."""
        os_type = random.choice(["Windows NT 10.0", "Macintosh; Intel Mac OS X 10_15_7", "X11; Linux x86_64"])
        major = random.randint(112, 127)  # Updated to latest Chrome versions
        minor = random.randint(0, 9)
        build = random.randint(1000, 9999)
        ua = (
            f"Mozilla/5.0 ({os_type}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.{build}.{minor} Safari/537.36"
        )
        return ua
    
    async def login(self, email: str = None, password: str = None):
        """Login to Facebook with cookies or credentials."""
        try:
            logger.info("Starting Facebook login process...")
            await self.page.goto("https://www.facebook.com/login", timeout=60000)
            
            # Check if already logged in
            logged_in_selectors = [
                "div[role='banner']",
                "div[aria-label*='profile']",
                "div[data-pagelet='Stories']",
                "a[aria-label*='Home']",
                "div[role='navigation']",
            ]
            
            for selector in logged_in_selectors:
                if await self.page.query_selector(selector) is not None:
                    logger.info("Already logged in via cookies")
                    return True
                    
            # If credentials are provided, use them
            if email and password:
                logger.info("Attempting automatic login...")
                
                await self.page.fill("input[name='email']", email)
                await asyncio.sleep(random.uniform(0.3, 0.8))
                await self.page.fill("input[name='pass']", password)
                
                # Random pause before clicking login
                await asyncio.sleep(random.uniform(0.5, 1.5))
                await self.page.click("button[name='login']")
                
                # Wait for navigation to complete
                try:
                    await self.page.wait_for_selector(
                        "div[role='banner'], nav[role='navigation'], div[data-pagelet='Stories'], a[aria-label*='Home']",
                        timeout=30000
                    )
                    logger.info("Automatic login successful")
                    await self._save_cookies()
                    return True
                except PWTimeout:
                    logger.warning("Automatic login requires manual checkpoint completion")
            
            # Manual login process
            logger.info("\n" + "="*50)
            logger.info("[!] Please log in manually in the browser window that opened.")
            logger.info("[!] The script will continue automatically after successful login.")
            logger.info("[!] Press Ctrl+C to abort if needed.")
            logger.info("="*50 + "\n")
            
            # Print manual login message to console even if logging to file
            print("\n" + "="*50)
            print("[!] Please log in manually in the browser window that opened.")
            print("[!] The script will continue automatically after successful login.")
            print("[!] Press Ctrl+C to abort if needed.")
            print("="*50 + "\n")
            
            # Wait for successful login indicators
            login_complete = False
            start_time = time.time()
            max_wait = 300  # 5 minutes
            check_interval = 5  # 5 seconds
            
            success_selectors = [
                "div[role='banner']", 
                "nav[role='navigation']", 
                "div[data-pagelet='Stories']",
                "a[aria-label*='Home']",
                "div[role='main']",
            ]
            
            while not login_complete and time.time() - start_time < max_wait:
                for selector in success_selectors:
                    if await self.page.query_selector(selector):
                        login_complete = True
                        break
                
                if login_complete:
                    break
                    
                elapsed = time.time() - start_time
                print(f"\rWaiting for login to complete... ({elapsed:.0f}s elapsed)", end="")
                await asyncio.sleep(check_interval)
            
            print()  # New line after progress indicator
                
            if login_complete:
                logger.info("Manual login successful")
                await self._save_cookies()
                return True
            else:
                logger.error("Login timed out after waiting 5 minutes")
                return False
                
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False
    
    async def _save_cookies(self):
        """Save cookies for future sessions."""
        try:
            cookies = await self.context.cookies()
            cookies_dir = Path("info")
            cookies_dir.mkdir(exist_ok=True)
            
            with open(cookies_dir / "cookies.json", 'w', encoding='utf-8') as f:
                json.dump(cookies, f, indent=2, ensure_ascii=False)
            logger.info("Saved cookies to file")
        except Exception as e:
            logger.error(f"Failed to save cookies: {e}")
            
    async def efficient_scroll(self):
        """Perform an efficient scroll without excessive delays."""
        # Get viewport height
        height = self.page.viewport_size["height"]
        
        # Scroll by 80% of viewport height for efficiency
        scroll_amount = int(height * 0.8)
        await self.page.mouse.wheel(0, scroll_amount)
        
        # Short pause to allow content to load
        await asyncio.sleep(random.uniform(0.3, 0.8))
    
    async def search_political_posts(self, search_keywords: list):
        """Navigate to Facebook search and search for political posts using multiple keywords."""
        try:
            # Join keywords with OR operator for broader search
            search_query = " OR ".join([f'"{keyword}"' for keyword in search_keywords[:5]])  # Limit to first 5 keywords for URL length
            logger.info(f"Searching for political posts with query: '{search_query}'")
            
            # Construct search URL - Facebook's search URL pattern
            import urllib.parse
            encoded_query = urllib.parse.quote(search_query)
            search_url = f"https://www.facebook.com/search/posts/?q={encoded_query}"
            
            await self.page.goto(search_url, timeout=60000)
            await asyncio.sleep(random.uniform(2, 4))  # Wait for search results to load
            
            # Wait for search results to appear
            try:
                await self.page.wait_for_selector("div[role='article']", timeout=15000)
                logger.info("Search results loaded successfully")
            except PWTimeout:
                logger.warning("Search results took too long to load, continuing anyway...")
                
        except Exception as e:
            logger.error(f"Error during search: {e}")
            # Fall back to homepage if search fails
            await self.page.goto("https://www.facebook.com", timeout=60000)
        
    async def capture_visible_posts(self, political_keywords: list = None):
        """Capture screenshots of all currently visible posts on the page."""
        # More specific selectors for actual posts, excluding UI elements
        post_selectors = [
            "div[role='article']:not([aria-hidden='true'])",  # Main post selector with visibility check
            "div.x1yztbdb:has(div[data-ad-preview='message'])",  # Posts with content
            "div.x1n2onr6.x1ja2u2z.x1jx94hy:has(div[aria-label*='Comment'])",  # Posts with comment options
        ]
        
        all_selector = ", ".join(post_selectors)
        posts = await self.page.query_selector_all(all_selector)
        
        captured_in_current_batch = 0
        
        for post in posts:
            try:
                # Check if element is too small (likely UI element)
                size = await post.bounding_box()
                if not size or size['width'] < 300 or size['height'] < 100:
                    logger.debug(f"Skipping small element: {size}")
                    continue
                
                # If political keywords are provided, check post content
                if political_keywords:
                    post_text = await post.evaluate("""
                        (el) => {
                            return el.innerText ? el.innerText.toLowerCase() : '';
                        }
                    """)
                    
                    # Check if any political keyword is in the post (case-insensitive)
                    contains_political = any(keyword.lower() in post_text for keyword in political_keywords)
                    if not contains_political:
                        logger.debug("Skipping non-political post")
                        continue
                
                # Check if post is in viewport
                in_viewport = await self.page.evaluate("""
                    (element) => {
                        const rect = element.getBoundingClientRect();
                        return (
                            rect.top >= 0 &&
                            rect.top < (window.innerHeight || document.documentElement.clientHeight) * 0.8 &&
                            rect.left >= 0 &&
                            rect.bottom > 0 &&
                            rect.right > 0
                        );
                    }
                """, post)
                
                if not in_viewport:
                    continue
                
                # Skip elements that are likely UI and not posts by checking content
                is_ui_element = await post.evaluate("""
                    (el) => {
                        // UI elements typically have specific aria roles or text content
                        const uiKeywords = ['menu', 'navigation', 'search', 'banner', 'alert', 'dialog'];
                        
                        // Check for UI roles
                        const role = el.getAttribute('role');
                        if (role && (uiKeywords.includes(role) || 
                                    role === 'button' || 
                                    role === 'link' ||
                                    role === 'tab')) {
                            return true;
                        }
                        
                        // UI elements often lack certain post-specific elements
                        const hasPostContent = el.querySelector('div[dir="auto"], span[dir="auto"], div[data-ad-preview="message"]');
                        const hasAuthor = el.querySelector('a[role="link"] span, h3, h4, strong');
                        const hasInteractions = el.querySelector('div[aria-label*="Like"], div[aria-label*="Comment"]');
                        
                        // If it doesn't have typical post features, it's probably UI
                        return !(hasPostContent || hasAuthor || hasInteractions);
                    }
                """)
                
                if is_ui_element:
                    logger.debug("Skipping UI element")
                    continue
                    
                # Additional verification - check for post timestamp (almost all posts have these)
                has_timestamp = await post.evaluate("""
                    (el) => {
                        return Boolean(
                            el.querySelector('a[role="link"] span[aria-hidden="true"]') || 
                            el.querySelector('abbr[data-utime]') ||
                            el.querySelector('span.x4k7w5x, span.x1i10hfl')
                        );
                    }
                """)
                
                if not has_timestamp:
                    logger.debug("Skipping element without timestamp")
                    continue
                
                # Generate a unique post identifier
                post_id = await post.evaluate("""
                    (el) => {
                        // Try to get some unique attributes
                        const aria_labelledby = el.getAttribute('aria-labelledby');
                        const aria_describedby = el.getAttribute('aria-describedby');
                        const data_pagelet = el.getAttribute('data-pagelet');
                        const id = el.id;
                        
                        // Form a unique ID from available attributes
                        return (aria_labelledby || '') + '_' + 
                               (aria_describedby || '') + '_' + 
                               (data_pagelet || '') + '_' + 
                               (id || '') + '_' + 
                               Date.now().toString();
                    }
                """)
                
                # Create a hash of the ID to make it filesystem-friendly
                import hashlib
                post_id_hash = hashlib.md5(post_id.encode()).hexdigest()[:12]
                
                # Take screenshot of just this post
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                prefix = "political_" if political_keywords else ""
                filename = f"{prefix}{self.session_id}_{self.posts_captured}_{post_id_hash}.png"
                filepath = self.screenshot_dir / filename
                
                # Make sure the post is fully visible before screenshot
                await self.page.evaluate("""
                    (element) => {
                        // Ensure element is in view with some context
                        element.scrollIntoView({ behavior: 'auto', block: 'center' });
                    }
                """, post)
                
                # Brief pause to ensure scrolling is complete
                await asyncio.sleep(0.2)
                
                # Take the screenshot
                await post.screenshot(path=filepath)
                
                # Validate the screenshot - check if it's not too small or empty
                import os
                file_size = os.path.getsize(filepath)
                if file_size < 5000:  # Less than 5KB is suspicious
                    logger.warning(f"Very small screenshot ({file_size} bytes): {filename}")
                    # Continue anyway as it might be a legitimate small post
                
                self.posts_captured += 1
                captured_in_current_batch += 1
                
                logger.info(f"Captured {'political ' if political_keywords else ''}post {self.posts_captured}: {filename} ({int(file_size/1024)}KB)")
                
            except Exception as e:
                logger.error(f"Error capturing post: {e}")
        
        return captured_in_current_batch
    
    async def scrape_facebook(self, url: str = None, target_posts: int = 100, search_political: list = None):
        """
        Scrape Facebook posts as screenshots from a specific URL or main feed.
        
        Args:
            url: The specific Facebook URL to scrape (profile, group, page, etc.)
            target_posts: Target number of posts to collect
            search_political: List of political keywords to search for
        """
        # If search_political is provided, search for political posts
        if search_political:
            await self.search_political_posts(search_political)
            political_keywords = search_political
        else:
            # Navigate to the target URL or default to Facebook homepage
            target_url = url if url else "https://www.facebook.com"
            logger.info(f"Navigating to {target_url}")
            await self.page.goto(target_url, timeout=60000)
            political_keywords = None
        
        # Dismiss any popup dialogs that might appear
        try:
            for _ in range(2):  # Check a couple of times for popups
                # Try to find and click "Not Now", "Cancel", "No", etc. buttons in popups
                for dismiss_text in ["Not Now", "Cancel", "No", "Close", "Skip"]:
                    dismiss_buttons = await self.page.query_selector_all(f"button:has-text('{dismiss_text}')")
                    for button in dismiss_buttons:
                        try:
                            await button.click()
                            logger.info(f"Dismissed popup with '{dismiss_text}' button")
                            await asyncio.sleep(1)
                        except:
                            pass
        except Exception as e:
            logger.debug(f"Error handling popups: {e}")
        
        # Wait for content to load
        feed_selectors = [
            "div[role='feed']",
            "div[data-pagelet='FeedUnit']",
            "div.x1lliihq", 
            "div.x1yztbdb",
            "div[aria-label*='News Feed']",
            "div[role='main'] div[role='article']",
        ]
        
        feed_found = False
        for selector in feed_selectors:
            try:
                await self.page.wait_for_selector(selector, timeout=10000)
                logger.info(f"Feed found using selector: {selector}")
                feed_found = True
                break
            except Exception:
                continue
                
        if not feed_found:
            logger.warning("Could not detect feed with known selectors. Continuing anyway...")
            await asyncio.sleep(5)  # Give page time to load
            
        logger.info(f"Starting to collect {'political ' if search_political else ''}posts (target: {target_posts})")
        start_time = time.time()
        
        no_new_posts_count = 0
        consecutive_empty_batches = 0
        post_count_checkpoint = 0
        
        # Save some debug info about the page
        try:
            debug_dir = Path("info")
            debug_dir.mkdir(exist_ok=True)
            await self.page.screenshot(path=debug_dir / f"full_page_{self.session_id}.png", full_page=True)
        except Exception as e:
            logger.error(f"Error saving debug screenshot: {e}")
        
        while self.posts_captured < target_posts:
            # Capture all visible posts
            captured = await self.capture_visible_posts(political_keywords=political_keywords)
            
            # If we didn't find any new posts after several scrolls, try different strategies
            if captured == 0:
                no_new_posts_count += 1
                consecutive_empty_batches += 1
                
                # After 3 consecutive empty batches, try some recovery strategies
                if consecutive_empty_batches >= 3:
                    # Strategy 1: Refresh the page
                    if no_new_posts_count % 3 == 0:
                        logger.info("No new posts found after several scrolls, refreshing page...")
                        await self.page.reload()
                        await asyncio.sleep(5)  # Wait for page to load
                        
                    # Strategy 2: Scroll a lot to get past potential sticky elements
                    elif no_new_posts_count % 3 == 1:
                        logger.info("Performing longer scroll to bypass sticky elements...")
                        height = self.page.viewport_size["height"]
                        await self.page.mouse.wheel(0, height * 2)
                        await asyncio.sleep(2)
                        
                    # Strategy 3: Try clicking "See More" or similar buttons
                    else:
                        logger.info("Looking for 'See More' buttons...")
                        see_more_selectors = [
                            "div:has-text('See More')",
                            "span:has-text('See More')",
                            "[role='button']:has-text('See More')",
                            "a:has-text('Show more posts')"
                        ]
                        for selector in see_more_selectors:
                            try:
                                buttons = await self.page.query_selector_all(selector)
                                for button in buttons:
                                    await button.click()
                                    logger.info(f"Clicked '{selector}' button")
                                    await asyncio.sleep(2)
                            except:
                                pass
                
                # If we've been stuck at the same post count for too long, stop the scraper
                if post_count_checkpoint == self.posts_captured:
                    if no_new_posts_count >= 15:  # After ~15 attempts with no new posts
                        logger.warning(f"No new posts found after {no_new_posts_count} attempts. Ending scrape early.")
                        break
                else:
                    # Reset counters when we make progress
                    post_count_checkpoint = self.posts_captured
                    consecutive_empty_batches = 0
            else:
                no_new_posts_count = 0
                consecutive_empty_batches = 0
            
            # Check if we've reached the target
            if self.posts_captured >= target_posts:
                break
                
            # Scroll down to see more posts
            await self.efficient_scroll()
            
            # Print progress every 10 posts
            if self.posts_captured % 10 == 0 and self.posts_captured > 0:
                elapsed = time.time() - start_time
                posts_per_minute = self.posts_captured / (elapsed / 60) if elapsed > 0 else 0
                logger.info(f"Progress: {self.posts_captured}/{target_posts} posts ({posts_per_minute:.1f} posts/minute)")
        
        elapsed = time.time() - start_time
        posts_per_minute = self.posts_captured / (elapsed / 60) if elapsed > 0 else 0
        logger.info(f"Scraping complete. Captured {self.posts_captured} posts in {elapsed:.1f} seconds ({posts_per_minute:.1f} posts/minute)")
        return self.screenshot_dir
        
    async def close(self):
        """Close browser and clean up."""
        if hasattr(self, 'context'):
            await self._save_cookies()
            await self.context.close()
            
        if hasattr(self, 'browser'):
            await self.browser.close()
            
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
            
        logger.info("Browser closed")