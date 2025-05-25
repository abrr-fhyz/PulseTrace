from lib.catalogue import FacebookScreenshotAnalyzer
import os
from dotenv import load_dotenv

def main():
    """Main function for process module."""
    print("Starting Facebook screenshot analysis...")
    try:
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        analyzer = FacebookScreenshotAnalyzer(api_key)
        analyzer.process_screenshots()
        print("Analysis complete!")
        return 0
    except Exception as e:
        print(f"Fatal error in main process: {e}")
        return 1

if __name__ == "__main__":
    exit(main())