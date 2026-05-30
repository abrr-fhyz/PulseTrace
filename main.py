#!/usr/bin/env python3
"""
Main entry point for Facebook analysis tools.
Simple dispatcher that loads environment variables and calls appropriate modules.
"""

import os
import sys
import argparse
from dotenv import load_dotenv


def main():
    """Main entry point - loads env and dispatches to appropriate module."""
    parser = argparse.ArgumentParser(
        description='Facebook Analysis Tools Suite',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  scrape      - Scrape Facebook posts and take screenshots
  process     - Analyze screenshots using AI
  summarize   - Generate summary analysis of posts
  briefing    - Generate an executive briefing for a completed run

Examples:
  python main.py scrape --target 100 --headless
  python main.py process
  python main.py summarize
  python main.py briefing --run-id 1780124361-beadcb
        """
    )
    
    parser.add_argument('command', choices=['scrape', 'process', 'summarize', 'briefing'],
                       help='Command to execute')
    
    # Parse only the command first
    args, remaining_args = parser.parse_known_args()
    
    # Load environment variables
    try:
        load_dotenv()
        from lib.keys import load as _load_api_keys
        _load_api_keys()
        print(f"Environment loaded, executing {args.command}...")
    except Exception as e:
        print(f"Failed to load environment: {e}")
        return 1
    
    # Dispatch to appropriate module
    try:
        if args.command == 'scrape':
            from lib.scrape import main as scrape_main
            # Pass remaining args to scrape module
            sys.argv = ['scrape.py'] + remaining_args
            return scrape_main()
            
        elif args.command == 'process':
            from lib.process import main as process_main
            return process_main()
            
        elif args.command == 'summarize':
            from lib.summarizer import main as summarizer_main
            return summarizer_main()

        elif args.command == 'briefing':
            briefing_parser = argparse.ArgumentParser()
            briefing_parser.add_argument('--run-id', required=True)
            briefing_parser.add_argument('--no-pdf', action='store_true')
            briefing_parser.add_argument('--no-summary', action='store_true')
            briefing_args = briefing_parser.parse_args(remaining_args)
            from lib.briefing import build
            out = build(
                briefing_args.run_id,
                with_pdf=not briefing_args.no_pdf,
                exec_summary=not briefing_args.no_summary,
            )
            print(out)
            return 0
            
    except Exception as e:
        print(f"Error executing {args.command}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
