Save cookies.json in "info" directory
Keep .env in root level.

Check logs in info directory during/after scraping.
Images will be saved to Screenshots.
Data will be saved in data direvctory.

.env file format:
```
FACEBOOK_EMAIL=
FACEBOOK_PASSWORD=
OPENAI_API_KEY=
```
## FrontEnd Usage
    Start backend server with  `python server.py`
    Navigate to Dashboard at localhost:5000.

## Commands:
    scrape      - Scrape Facebook posts and take screenshots
    process     - Analyze screenshots using GPT
    summarize   - Generate summary analysis of posts

## Examples:
    `python main.py scrape --headless`
    `python main.py process`
    `python main.py summarize`
