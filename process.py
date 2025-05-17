from lib.catalogue import FacebookScreenshotAnalyzer
import os
from dotenv import load_dotenv

if __name__ == "__main__":
    print("Starting Facebook screenshot analysis...")
    try:
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        analyzer = FacebookScreenshotAnalyzer(api_key)
        analyzer.process_screenshots()
        print("Analysis complete!")
    except Exception as e:
        print(f"Fatal error in main process: {e}")