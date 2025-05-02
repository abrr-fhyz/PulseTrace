import pandas as pd
import asyncio
import json
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Any
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from bs4 import BeautifulSoup

from lib.constants import (
    COOKIES_FILE, RESULTS_DIR, CSV_HEADERS, POST_SELECTORS,
    BLOCK_SELECTORS, UI_INDICATORS, SCROLL_PAUSE, SCROLL_RANDOM_DELAY
)
from lib.utils import retry
from lib.config import logger
from lib.state import stats

class FacebookScraper:
    """Advanced scraper for Facebook posts with continuous operation support."""
    
    def __init__(self, headless: bool = False, stealth_level: int = 2):
        """Initialize the scraper with configurable stealth level.
        
        Args:
            headless: Whether to run the browser in headless mode
            stealth_level: Level of anti-detection measures (1-3, higher = more stealth but slower)
        """
        self.headless = headless
        self.stealth_level = max(1, min(stealth_level, 3))  # Ensure between 1-3
        self.posts_data = []
        self.seen_post_ids = set()
        self.csv_path = None
        self.last_save_count = 0
        self.current_url = None
        self.session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        
    async def launch_browser(self):
        """Launch browser with advanced stealth settings."""
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
            has_touch=random.random() > 0.7,  # 30% chance of touch enabled
        )
        
        # Apply advanced stealth JS patches
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
            
            // Pass Navigator checks
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
            
            // Pass plugins check
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    return [1, 2, 3, 4, 5];
                },
            });
            
            // Pass language check
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en', 'es'],
            });
            
            // WebGL fingerprinting protection
            const getParameter = WebGLRenderingContext.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                // Add randomization to throw off fingerprinting
                if (parameter === 37445) {
                    return 'Intel Inc.';
                }
                if (parameter === 37446) {
                    return 'Intel Iris OpenGL Engine';
                }
                return getParameter.apply(this, [parameter]);
            };
            
            // Mock hardware concurrency
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 8
            });
        }
        """)
        
        # Additional stealth for highest level
        if self.stealth_level >= 3:
            await self.context.add_init_script("""
            () => {
                // Spoof common properties used for fingerprinting
                Object.defineProperty(screen, 'width', { get: () => 1920 });
                Object.defineProperty(screen, 'height', { get: () => 1080 });
                Object.defineProperty(screen, 'availWidth', { get: () => 1920 });
                Object.defineProperty(screen, 'availHeight', { get: () => 1080 });
                Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
                Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });
                
                // Add noise to audio context
                const originalGetChannelData = AudioBuffer.prototype.getChannelData;
                AudioBuffer.prototype.getChannelData = function() {
                    const array = originalGetChannelData.apply(this, arguments);
                    // add very slight noise to prevent fingerprinting
                    for(let i = 0; i < array.length; i += 100) {
                        array[i] = array[i] + (Math.random() * 0.0000001);
                    }
                    return array;
                }
            }
            """)
        
        # Load cookies if available
        if COOKIES_FILE.exists():
            try:
                # Read with UTF-8 encoding to handle any Unicode characters
                with open(COOKIES_FILE, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                await self.context.add_cookies(cookies)
                logger.info("Loaded cookies from file")
            except Exception as e:
                logger.warning(f"Could not load cookies: {e}")
        
        # Create a new page
        self.page = await self.context.new_page()
        
        # Set up event listeners to monitor for potential bans or rate limits
        self.page.on("response", self._check_response)
        self.page.on("console", self._handle_console)
        
    def _random_user_agent(self) -> str:
        """Generate realistic modern Chrome/Edge/Firefox user-agent."""
        browser_type = random.choice(["chrome", "edge", "firefox"])
        
        if browser_type == "chrome":
            os_type = random.choice(["Windows NT 10.0", "Macintosh; Intel Mac OS X 10_15_7", "X11; Linux x86_64"])
            major = random.randint(112, 127)  # Updated to latest Chrome versions
            minor = random.randint(0, 9)
            build = random.randint(1000, 9999)
            ua = (
                f"Mozilla/5.0 ({os_type}) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{major}.0.{build}.{minor} Safari/537.36"
            )
        elif browser_type == "edge":
            os_type = "Windows NT 10.0"
            edg_v = random.randint(112, 127)
            chrome_v = edg_v - random.randint(0, 2)
            ua = (
                f"Mozilla/5.0 ({os_type}) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{chrome_v}.0.0.0 Safari/537.36 Edg/{edg_v}.0.0.0"
            )
        else:  # firefox
            os_type = random.choice(["Windows NT 10.0", "Macintosh; Intel Mac OS X 10.15", "X11; Linux x86_64"])
            major = random.randint(112, 127)
            minor = random.randint(0, 9)
            gecko_date = f"20100101"
            ua = (
                f"Mozilla/5.0 ({os_type}; rv:{major}.{minor}) "
                f"Gecko/{gecko_date} Firefox/{major}.{minor}"
            )
                
        return ua
        
    async def _check_response(self, response):
        """Monitor responses for indications of problems."""
        if response.status >= 400:
            logger.warning(f"Received error status {response.status} for URL: {response.url}")
            
        if response.status == 429:
            logger.error(f"Rate limit detected (429 status). Slowing down.")
            stats.throttles += 1
            await asyncio.sleep(random.uniform(20, 45))
            
        # Check for login/security checkpoints redirects
        if "checkpoint" in response.url or "security" in response.url:
            logger.warning(f"Security checkpoint detected: {response.url}")
            
    async def _handle_console(self, msg):
        """Monitor console messages for problems."""
        text = msg.text.lower()
        
        if "error" in text or "exception" in text:
            # Ignore certain common errors
            if not any(x in text for x in ["react_", "fbicon", "stylesheet", "adblock"]):
                logger.debug(f"Console error: {msg.text}")
                
        # Detect security issues
        security_terms = ["security", "suspicious", "unusual", "activity", "verify", "checkpoint"]
        if any(term in text for term in security_terms):
            logger.warning(f"Potential security alert in console: {msg.text}")
        
    @retry(max_attempts=2)
    async def login(self, email: str = None, password: str = None):
        """Login to Facebook with enhanced error handling."""
        try:
            logger.info("Starting Facebook login process...")
            await self.page.goto("https://www.facebook.com/login", timeout=60000)
            
            # Check if already logged in by looking for multiple elements
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
                
                # Randomize typing speed to appear more human
                await self._fill_with_human_typing("input[name='email']", email)
                await asyncio.sleep(random.uniform(0.3, 0.8))
                await self._fill_with_human_typing("input[name='pass']", password)
                
                # Random pause before clicking login
                await asyncio.sleep(random.uniform(0.5, 1.5))
                
                # Randomize click position on the login button
                login_button = await self.page.query_selector("button[name='login']")
                if login_button:
                    bounds = await login_button.bounding_box()
                    if bounds:
                        # Click at a random position within the button
                        x = bounds["x"] + random.uniform(5, bounds["width"] - 5)
                        y = bounds["y"] + random.uniform(5, bounds["height"] - 5)
                        await self.page.mouse.click(x, y)
                    else:
                        await login_button.click()
                else:
                    # Fallback to normal click if button not found
                    await self.page.click("button[name='login']")
                
                # Wait for navigation to complete with multiple success indicators
                try:
                    await self.page.wait_for_selector(
                        "div[role='banner'], nav[role='navigation'], div[data-pagelet='Stories'], a[aria-label*='Home']",
                        timeout=30000
                    )
                    logger.info("Automatic login successful")
                    await self._save_cookies()
                    return True
                except PWTimeout:
                    # Check for login checkpoints (2FA, CAPTCHA, etc.)
                    checkpoint_selectors = [
                        "input[name='approvals_code']",  # 2FA code
                        "input#captcha_response",  # CAPTCHA
                        "button[value='security_check']",  # Security check
                        "input[name='verification_code']", # SMS code
                        "input[placeholder*='code']", # Generic verification code
                    ]
                    
                    for selector in checkpoint_selectors:
                        if await self.page.query_selector(selector):
                            logger.warning(f"Login checkpoint detected: {selector}")
                            break
                    
                    logger.warning("Automatic login requires manual checkpoint completion")
            
            # Manual login process
            logger.info("Please log in manually in the browser window...")
            print("\n" + "="*50)
            print("[!] Please complete the login in the browser window that opened.")
            print("[!] The script will continue automatically after successful login.")
            print("[!] Press Ctrl+C to abort if needed.")
            print("="*50 + "\n")
            
            # Wait for successful login indicators with progression feedback
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
            
    async def _fill_with_human_typing(self, selector, text):
        """Fill an input field with human-like typing patterns."""
        # First click on the input field (with random position)
        element = await self.page.query_selector(selector)
        if not element:
            logger.warning(f"Element {selector} not found for typing")
            return
            
        # Get element dimensions
        box = await element.bounding_box()
        if not box:
            logger.warning(f"Could not get bounding box for {selector}")
            await element.click()
        else:
            # Click at a random position within the element
            x = box["x"] + random.uniform(5, box["width"] - 5)
            y = box["y"] + random.uniform(5, box["height"] - 5)
            await self.page.mouse.click(x, y)
            
        # Clear the field if it has a value
        await self.page.evaluate(f'''selector => {{
            const element = document.querySelector('{selector}');
            if (element) element.value = '';
        }}''')
        
        # Type with variable speed like a human
        for char in text:
            await self.page.type(selector, char, delay=random.uniform(50, 150))
            # Occasional longer pauses
            if random.random() < 0.1:  # 10% chance
                await asyncio.sleep(random.uniform(0.1, 0.3))
                
    async def _save_cookies(self):
        """Save cookies for future sessions."""
        try:
            cookies = await self.context.cookies()
            # Use UTF-8 encoding to handle any Unicode in cookies
            with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, indent=2, ensure_ascii=False)
            logger.info("Saved cookies to file")
        except Exception as e:
            logger.error(f"Failed to save cookies: {e}")
            
    async def human_scroll(self, force_random: bool = False):
        """Scrolls with enhanced human-like behavior and random pauses."""
        # Update stats
        stats.scrolls += 1
        
        # Randomize scroll behavior
        height = self.page.viewport_size["height"]
        
        # Different scroll patterns
        if random.random() < 0.2 or force_random:  # 20% chance of random scroll
            # Short, varied scroll for "looking at content" behavior
            scroll_amount = random.randint(int(height * 0.1), int(height * 0.4))
            logger.debug("Performing short scroll")
        else:
            # Normal scroll to see new content
            scroll_amount = random.randint(int(height * 0.5), int(height * 0.9))
        
        # Occasionally horizontal offset to mimic human behavior
        h_offset = random.randint(-8, 8) if random.random() < 0.3 else 0
        
        # Throttle the wheel event for more natural scrolling
        steps = random.randint(3, 8)
        step_size = scroll_amount / steps
        
        for i in range(steps):
            await self.page.mouse.wheel(h_offset / steps, step_size)
            await asyncio.sleep(random.uniform(0.01, 0.05))
        
        # Standard pause after scrolling
        pause_time = random.uniform(SCROLL_PAUSE[0], SCROLL_PAUSE[1])
        
        # Longer random pauses occasionally to simulate human reading
        if random.random() < 0.15:  # 15% chance
            pause_time = random.uniform(SCROLL_RANDOM_DELAY[0], SCROLL_RANDOM_DELAY[1])
            logger.debug(f"Taking a longer pause ({pause_time:.1f}s)...")
        
        await asyncio.sleep(pause_time)
        
        # Occasionally move the mouse to simulate checking content
        if random.random() < 0.4:  # 40% chance
            viewport_width = self.page.viewport_size["width"]
            viewport_height = self.page.viewport_size["height"]
            x = random.randint(int(viewport_width * 0.1), int(viewport_width * 0.9))
            y = random.randint(int(viewport_height * 0.1), int(viewport_height * 0.9))
            
            # Move with variable speeds and steps
            await self.page.mouse.move(
                x, y, 
                steps=random.randint(3, 10)
            )
            
            # Occasionally hover over links to simulate interest
            if random.random() < 0.3:
                link_selectors = ["a", "div[role='button']", "span[role='link']"]
                random_selector = random.choice(link_selectors)
                links = await self.page.query_selector_all(random_selector)
                if links and len(links) > 0:
                    random_link = links[random.randint(0, len(links) - 1)]
                    try:
                        await random_link.hover(timeout=1000)
                        await asyncio.sleep(random.uniform(0.2, 0.7))
                    except:
                        pass  # Ignore if link is no longer available
                
            # Micro-pause after mouse movement
            await asyncio.sleep(random.uniform(0.1, 0.3))
            
    async def _extract_url_from_post(self, post_element) -> str:
        """Extract the permanent URL for a post."""
        # Try multiple selectors for finding the permalink
        permalink_selectors = [
            "a[href*='/posts/']",
            "a[href*='fbid=']",
            "a[href*='story_fbid=']",
            "a[href*='/permalink/']",
            "a[href*='/photo/']",
            "a[href*='/photo.php']",
            "a[href*='/reel/']",
            "a[href*='/videos/']",
            "span[role='link'] a[aria-label*='comment']",  # Link near comments
            "a[aria-label*='comment']",
            "a[href*='/groups/'][href*='/permalink/']"
        ]
        
        for selector in permalink_selectors:
            try:
                link = await post_element.query_selector(selector)
                if link:
                    href = await link.get_attribute("href")
                    if href and ('posts' in href or 'fbid=' in href or 'story_fbid=' in href or 'permalink' in href):
                        # Ensure it's an absolute URL
                        if not href.startswith('http'):
                            href = f"https://www.facebook.com{href}"
                        return href
            except:
                continue
                
        # Fallback: Look for timestamps which often link to the permanent post
        try:
            time_selectors = [
                "a[role='link'] abbr",
                "a[role='link'] time",
                "abbr[data-utime]",
                "span[id*='jsc_c'][role='button']",  # Often timestamps
                "span[role='link'] > span:last-child", # Often relative times
            ]
            
            for selector in time_selectors:
                time_element = await post_element.query_selector(f"a:has({selector})")
                if time_element:
                    href = await time_element.get_attribute("href")
                    if href:
                        if not href.startswith('http'):
                            href = f"https://www.facebook.com{href}"
                        return href
        except:
            pass
                
        # Return None if no URL found
        return None
        
    @retry(max_attempts=2)
    async def parse_post(self, post_element) -> Optional[Dict[str, Any]]:
        """Extract post data from a post element with enhanced accuracy."""
        try:
            # Get post HTML
            post_html = await post_element.inner_html()
            
            # IMPROVED FILTERING - Skip UI elements mistaken for posts
            
            # 1. Check for very small posts (likely UI elements)
            if len(post_html) < 500:  # Real posts typically have substantial HTML
                stats.posts_skipped += 1
                return None
                
            # Parse with BeautifulSoup
            soup = BeautifulSoup(post_html, "html.parser")
            
            # 2. Check for obvious UI text patterns
            for indicator in UI_INDICATORS:
                if soup.find(string=lambda text: text and indicator.lower() in (text.lower() if text else "")):
                    stats.posts_skipped += 1
                    return None
                    
            # 3. Check if post contains actual content divs and not just UI elements
            has_content_div = soup.select_one("div[data-ad-comet-preview='message'], div[dir='auto']")
            if not has_content_div:
                stats.posts_skipped += 1
                return None
            
            # Extract post URL directly from the element
            post_url = await self._extract_url_from_post(post_element)
            
            # Extract unique post ID from URL or HTML
            post_id = None
            
            # Try to get ID from URL first
            if post_url:
                patterns = [
                    r"[?&]fbid=(\d+)",
                    r"story_fbid=(\d+)",
                    r"/(?:posts|permalink|reel|photo|video|videos)/(\d+)",
                    r"/permalink/\d+/(\d+)",
                    r"/groups/[^/]+/permalink/(\d+)",
                ]
                for pat in patterns:
                    m = re.search(pat, post_url)
                    if m:
                        post_id = m.group(1)
                        break
            
            # If no ID found in URL, try data attributes
            if not post_id:
                # Check if the element has a direct ID attribute
                element_id = await post_element.get_attribute("id")
                if element_id and "mall_post_" in element_id:
                    post_id = element_id.split("mall_post_")[1]
                
                # Try data-ft attributes
                if not post_id:
                    for element in soup.find_all(attrs={"data-ft": True}):
                        try:
                            data_ft = json.loads(element["data-ft"])
                            if "mf_story_key" in data_ft:
                                post_id = data_ft["mf_story_key"]
                                break
                            elif "top_level_post_id" in data_ft:
                                post_id = data_ft["top_level_post_id"]
                                break
                        except:
                            pass
                            
            # If still no ID, check for aria-posinset
            if not post_id:
                aria_posinset = await post_element.get_attribute("aria-posinset")
                if aria_posinset:
                    # Use position plus timestamp for unique ID
                    timestamp = int(time.time())
                    post_id = f"pos_{aria_posinset}_{timestamp}"
                    
            # If still no ID, generate a hash of content + author
            if not post_id:
                content_elements = soup.select("div[dir='auto']")
                author_elements = soup.select("h3 a, strong a[role='link']")
                
                content_text = ""
                if content_elements:
                    content_text = content_elements[0].get_text(strip=True)
                
                author_text = ""
                if author_elements:
                    author_text = author_elements[0].get_text(strip=True)
                
                combined = (author_text + content_text).strip()
                if combined:
                    # Generate a deterministic but unique ID
                    import hashlib
                    post_id = hashlib.md5(combined.encode()).hexdigest()[:16]
                else:
                    # Last resort - random ID with timestamp
                    post_id = f"fb_{int(time.time())}_{random.randint(1000, 9999)}"
                    
            # Extract page/author name and profile URL from link tags
            # Look for page name in specific link elements that typically contain the author
            author_name = ""
            author_profile = ""
            page_link_selectors = [
                "h3 a[href*='facebook.com']",
                "h4 a[href*='facebook.com']",
                "strong a[role='link'][href*='facebook.com']",
                "a[aria-label][href*='facebook.com']",
                "div[role='article'] h4 a[href*='facebook.com']",
                "span[dir='auto'] a[role='link'][href*='facebook.com']"
            ]
            
            for selector in page_link_selectors:
                links = soup.select(selector)
                if links:
                    for link in links:
                        # Get the page name from the link text
                        link_text = link.get_text(strip=True)
                        if link_text and len(link_text) > 1:
                            # Skip common UI elements mistakenly captured
                            if link_text.lower() not in ["learn more", "see more", "privacy", "menu", "home"]:
                                author_name = link_text
                                author_profile = link.get("href", "")
                                break
                    if author_name:
                        break
                        
            # Skip if no author found - likely UI element
            if not author_name:
                stats.posts_skipped += 1
                return None
            
            # Extract timestamp with improved detection
            timestamp = None
            time_selectors = [
                "a[role='link'] abbr",
                "a[role='link'] time",
                "abbr[data-utime]",
                "span[role='link'] > span:last-child", # Often contains relative times
                "span.x4k7w5x", # 2025 markup
                "span[id*='jsc_c']", # 2025 markup
                "a.x1i10hfl span.x1iorvi4", # Another timestamp location
            ]
            
            for selector in time_selectors:
                time_elements = soup.select(selector)
                for time_tag in time_elements:
                    text = time_tag.get_text(strip=True)
                    # Look for typical time patterns
                    if text and re.search(r'(hr|min|sec|hour|day|yesterday|week|month|^[0-9]+[dhm]$|^now$)', text.lower()):
                        timestamp = text
                        break
                if timestamp:
                    break
            
            # For absolute precision, try to get the actual timestamp attribute if available
            data_utime = None
            utime_elements = soup.select("[data-utime]")
            if utime_elements:
                try:
                    data_utime = utime_elements[0].get("data-utime")
                    if data_utime:
                        # Convert Unix timestamp to human readable
                        timestamp_obj = datetime.fromtimestamp(int(data_utime))
                        data_utime = timestamp_obj.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    pass
            
            # Extract post content with improved selectors
            content_text = ""
            
            # Look for main post content in text blocks
            content_selectors = [
                "div[data-ad-comet-preview='message']",
                "div[dir='auto']:not([class*='comment'])",
                "div.xdj266r",
                "div.x11i5rnm",
                "div[role='article'] div[dir='auto']:not([aria-hidden='true'])"
            ]
            
            for selector in content_selectors:
                elements = soup.select(selector)
                for element in elements:
                    text = element.get_text(strip=True)
                    if text and len(text) > 5:
                        # Check if it's not UI text
                        if not any(ui in text.lower() for ui in UI_INDICATORS):
                            if text not in content_text:  # Avoid duplication
                                content_text += " " + text
            
            # Clean up content text
            content_text = content_text.strip()
            content_text = re.sub(r'\s+', ' ', content_text)
            
            # Extract engagement metrics with improved patterns
            reactions = comments = shares = 0
            
            # Look for reaction counts with more patterns
            engagement_patterns = [
                (r'(\d+(?:\.\d+)?)[kK]\s*(?:like|reaction|comment|share)', lambda x: int(float(x) * 1000)),  # "5K likes"
                (r'(\d+)[mM]\s*(?:like|reaction|comment|share)', lambda x: int(float(x) * 1000000)),  # "2M likes"
                (r'([0-9.,]+)\s*(?:like|reaction)', lambda x: int(float(x.replace(',', '')))),  # "15 likes" or "1,234 likes"
                (r'([0-9.,]+)\s*comment', lambda x: int(float(x.replace(',', '')))),  # "7 comments" or "1,234 comments"
                (r'([0-9.,]+)\s*share', lambda x: int(float(x.replace(',', '')))),  # "3 shares" or "1,234 shares"
            ]
            
            # Check all text in the post for engagement numbers
            all_text = soup.get_text().lower()
            
            for pattern, converter in engagement_patterns:
                matches = re.findall(pattern, all_text)
                for match in matches:
                    try:
                        value = converter(match)
                        if 'like' in pattern or 'reaction' in pattern:
                            reactions = max(reactions, value)
                        elif 'comment' in pattern:
                            comments = max(comments, value)
                        elif 'share' in pattern:
                            shares = max(shares, value)
                    except ValueError:
                        continue
            
            # Create post data structure
            post_data = {
                "post_id": post_id,
                "author_name": author_name,
                "author_profile": author_profile,
                "timestamp": data_utime if data_utime else (timestamp if timestamp else ""),
                "content": content_text,
                "reactions": reactions,
                "comments": comments,
                "shares": shares,
                "total_engagement": reactions + comments + shares,
                "url": post_url if post_url else "",
                "scrape_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # Track unique authors
            stats.unique_authors.add(author_name)
            
            return post_data
            
        except Exception as e:
            logger.error(f"Error parsing post: {e}")
            return None
    
    async def initialize_csv(self) -> str:
        """Initialize CSV file with headers for streaming updates."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.csv_path = RESULTS_DIR / f"facebook_posts_{self.session_id}.csv"
        self.json_path = RESULTS_DIR / f"facebook_posts_{self.session_id}.json"
        
        # Create CSV with headers
        df = pd.DataFrame(columns=CSV_HEADERS)
        df.to_csv(self.csv_path, index=False, encoding='utf-8-sig')
        
        # Initialize empty JSON array
        with open(self.json_path, 'w', encoding='utf-8') as f:
            f.write('[]')
            
        logger.info(f"Initialized result files: {self.csv_path}")
        return str(self.csv_path)
    
    async def save_post_to_csv(self, post_data: Dict[str, Any]) -> None:
        """Save a single post to CSV and JSON files."""
        if not self.csv_path:
            await self.initialize_csv()
            
        try:
            # Append to CSV
            df = pd.DataFrame([post_data])
            df.to_csv(self.csv_path, mode='a', header=False, index=False, encoding='utf-8-sig')
            
            # Update JSON - we need to read the current data, add the new post, and write it back
            with open(self.json_path, 'r', encoding='utf-8') as f:
                try:
                    current_data = json.load(f)
                except json.JSONDecodeError:
                    current_data = []
                    
            current_data.append(post_data)
            
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(current_data, f, indent=2, ensure_ascii=False)
                
            stats.last_saved_at = datetime.now()
                
        except Exception as e:
            logger.error(f"Error saving post to CSV/JSON: {e}")
            
            # Attempt emergency backup of the post
            try:
                backup_file = RESULTS_DIR / f"fb_post_backup_{int(time.time())}.json"
                with open(backup_file, 'w', encoding='utf-8') as f:
                    json.dump(post_data, f, ensure_ascii=False)
                logger.info(f"Created emergency backup of post at {backup_file}")
            except:
                logger.critical("Failed to create emergency backup!")
    
    async def scrape_facebook(self, url: str = None, target_posts: int = None):
        """
        Scrape Facebook posts continuously from a specific URL or main feed.
        
        Args:
            url: The specific Facebook URL to scrape (profile, group, page, etc.)
            target_posts: Target number of posts to collect (None = run continuously)
        """
        # Navigate to the target URL or default to the Facebook homepage
        target_url = url if url else "https://www.facebook.com"
        logger.info(f"Navigating to {target_url}")
        
        stats.page_loads += 1
        await self.page.goto(target_url, timeout=60000)
        self.current_url = target_url
        
        # Initialize CSV for results
        await self.initialize_csv()
        
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
            
        # Start collecting posts
        collected_posts = 0
        scroll_count = 0
        last_post_time = datetime.now()
        
        logger.info(f"Starting to collect posts{' (target: ' + str(target_posts) + ')' if target_posts else ' continuously'}")
        
        # Initialize stats tracking
        stats.posts_collected = 0
        stats.posts_skipped = 0
        stats.scrolls = 0
        last_stats_print = datetime.now()
        
        # Main scraping loop
        while stats.running:
            # Check if we've reached the target (if specified)
            if target_posts is not None and collected_posts >= target_posts:
                logger.info(f"Reached target of {target_posts} posts - scraping complete")
                break
                
            # Get all visible posts using combined selector
            post_selector = ", ".join(POST_SELECTORS)
            posts = await self.page.query_selector_all(post_selector)
            logger.debug(f"Found {len(posts)} potential posts on screen")
            
            # Skip empty results
            if not posts:
                logger.debug("No posts found on screen, scrolling for more...")
                await self.human_scroll()
                scroll_count += 1
                continue
                
            # Flag to track if we found any new posts
            found_new_post = False
            
            # Process each post
            for post in posts:
                # Skip post if it matches any of the block selectors
                is_blocked = False
                for block_selector in BLOCK_SELECTORS:
                    if await post.query_selector(block_selector):
                        is_blocked = True
                        break
                        
                if is_blocked:
                    continue
                
                # Get post data
                post_data = await self.parse_post(post)
                
                if not post_data:
                    continue
                    
                post_id = post_data.get("post_id")
                
                # Skip if we've already seen this post
                if post_id in self.seen_post_ids:
                    continue
                    
                # Mark this post as seen
                self.seen_post_ids.add(post_id)
                found_new_post = True
                
                # Add to our collection and save immediately
                await self.save_post_to_csv(post_data)
                self.posts_data.append(post_data)
                collected_posts += 1
                stats.posts_collected += 1
                
                # Update runtime stats
                last_post_time = datetime.now()
                
                # Log the post - handle Unicode safely
                try:
                    content_preview = post_data.get("content", "")[:50].replace("\n", " ") if post_data.get("content") else "[No content]"
                    author_name = post_data.get('author_name', '')[:25] if post_data.get('author_name') else ""
                    timestamp = post_data.get('timestamp', '')
                    post_time = timestamp[:10] if timestamp is not None else ""
                    logger.info(f"[{collected_posts}] {author_name:25} | {post_time:10} | {content_preview:50}")
                except UnicodeEncodeError:
                    # Fallback logging that sanitizes Unicode
                    logger.info(f"[{collected_posts}] Post collected (unicode content)")
                
                # Print stats summary periodically
                current_time = datetime.now()
                if (current_time - last_stats_print).total_seconds() > 60:  # Every minute
                    stats.print_summary()
                    last_stats_print = current_time
            
            # If we've been scrolling for a while with no new posts, consider refreshing
            time_since_last_post = datetime.now() - last_post_time
            if scroll_count > 30 and not found_new_post and time_since_last_post.total_seconds() > 120:
                logger.info(f"No new posts found after {scroll_count} scrolls, refreshing page...")
                stats.page_loads += 1
                await self.page.reload()
                scroll_count = 0
                await asyncio.sleep(5)  # Wait for page to load
                continue
                
            # Scroll for more posts with occasional "look around" behavior
            if random.random() < 0.1:  # 10% chance
                # "Looking at content" - short, random scrolls
                for _ in range(random.randint(1, 3)):
                    await self.human_scroll(force_random=True)
            else:
                # Normal scrolling
                await self.human_scroll()
                
            scroll_count += 1
            
            # Add more random behaviors
            if random.random() < 0.05 and scroll_count > 5:  # 5% chance after some scrolling
                # Random page interactions to appear more human-like
                random_action = random.choice([
                    "move_mouse", "short_pause", "random_clicks", "react"
                ])
                
                if random_action == "move_mouse":
                    # Move mouse around randomly
                    for _ in range(random.randint(2, 5)):
                        x = random.randint(100, self.page.viewport_size["width"] - 100)
                        y = random.randint(100, self.page.viewport_size["height"] - 100)
                        await self.page.mouse.move(x, y, steps=random.randint(3, 8))
                        await asyncio.sleep(random.uniform(0.1, 0.5))
                        
                elif random_action == "short_pause":
                    # Take a slightly longer break
                    pause_time = random.uniform(3.0, 7.0)
                    logger.debug(f"Taking a short break ({pause_time:.1f}s)...")
                    await asyncio.sleep(pause_time)
                    
                elif random_action == "random_clicks":
                    # Find non-interactive areas to click (avoid buttons/links)
                    try:
                        blank_areas = await self.page.query_selector_all("div.x1n2onr6, div.xzueoph, div.x78zum5")
                        if blank_areas and len(blank_areas) > 0:
                            area = random.choice(blank_areas)
                            bounds = await area.bounding_box()
                            if bounds:
                                x = bounds["x"] + random.uniform(10, bounds["width"] - 10)
                                y = bounds["y"] + random.uniform(10, bounds["height"] - 10)
                                await self.page.mouse.click(x, y)
                    except:
                        pass
                        
                elif random_action == "react":
                    # Simulate hovering over a post (but not actually reacting)
                    try:
                        reaction_areas = await self.page.query_selector_all("div[role='button'][tabindex='0']")
                        if reaction_areas and len(reaction_areas) > 0:
                            reaction = random.choice(reaction_areas)
                            await reaction.hover()
                            await asyncio.sleep(random.uniform(0.5, 1.5))
                            # Move away without clicking
                            await self.page.mouse.move(
                                random.randint(100, self.page.viewport_size["width"] - 100),
                                random.randint(100, self.page.viewport_size["height"] - 100)
                            )
                    except:
                        pass
        
        # Final stats update
        stats.print_summary()
        logger.info(f"Scraping complete. Collected {collected_posts} posts.")
        return self.csv_path
            
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