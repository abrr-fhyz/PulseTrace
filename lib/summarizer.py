import os
from dotenv import load_dotenv
from lib.summary import FacebookPostsSummaryAnalyzer

def main():
    """Main function for summarizer module."""
    print("Starting Facebook posts summary analysis...")
    try:
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        analyzer = FacebookPostsSummaryAnalyzer(api_key)
        summary = analyzer.run_analysis()
        print("Summary analysis complete!")
        return 0
    except Exception as e:
        print(f"Fatal error in summary process: {e}")
        return 1

if __name__ == "__main__":
    exit(main())