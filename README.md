Save cookies.json in "info" directory
Keep .env in root level.

.env format:
```
FACEBOOK_EMAIL=
FACEBOOK_PASSWORD=
OPENAI_API_KEY=
```

To start scraping:
`python scrape.py --headless`

To process screenshots:
`python process.py`

Check logs in info directory during/after scraping.
Images will be saved to Screenshots.
Data will be saved in Data.