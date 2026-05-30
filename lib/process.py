from __future__ import annotations
import os
from dotenv import load_dotenv

from lib.catalogue import FacebookScreenshotAnalyzer
from lib.keys import load as _load_api_keys


def main() -> int:
    """V1 entrypoint: OCR every screenshot via Gemini Vision."""
    print("Starting Facebook screenshot analysis...")
    try:
        load_dotenv()
        _load_api_keys()
        api_key = os.environ.get("GEMINI_API_KEY")
        analyzer = FacebookScreenshotAnalyzer(api_key)
        analyzer.process_screenshots()
        print("Analysis complete!")
        return 0
    except Exception as e:
        print(f"Fatal error in main process: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
