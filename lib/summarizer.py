from __future__ import annotations
import os
from dotenv import load_dotenv

from lib.summary import FacebookPostsSummaryAnalyzer
from lib.keys import load as _load_api_keys


def main() -> int:
    """V1 entrypoint: summarize OCR'd posts via cascade LLM."""
    print("Starting Facebook posts summary analysis...")
    try:
        load_dotenv()
        _load_api_keys()
        analyzer = FacebookPostsSummaryAnalyzer()
        analyzer.run_analysis()
        print("Summary analysis complete!")
        return 0
    except Exception as e:
        print(f"Fatal error in summary process: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
