"""V1 Facebook posts summary — Gemini chat via lib.llm cascade.

Converted from direct OpenAI gpt-4o calls to chat_json() which walks the
multi-provider cascade (gemini, groq, llm7, etc.). Output is a JSON object
with one field; we extract the plain text and write the same files.
"""
from __future__ import annotations
import json
import os

from .llm import chat_json


SYS = (
    "You are an expert social media analyst. Analyze Facebook posts data and "
    "return ONLY a JSON object of the shape {\"summary\": \"...\"}, where "
    "summary is exactly two well-structured paragraphs totaling 150-200 words. "
    "Focus on: general highlights and most popular posts (reactions, comments, "
    "shares), overall mood (Optimistic, Pessimistic, Skeptical, Ironic, etc.), "
    "notable trends/themes/patterns, observations about engagement."
)


class FacebookPostsSummaryAnalyzer:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def load_posts_data(self, file_path: str = "data/facebook_posts_all.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"Loaded {len(data)} posts from {file_path}")
            return data
        except FileNotFoundError:
            print(f"File not found: {file_path}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            return None
        except Exception as e:
            print(f"Error loading file: {e}")
            return None

    def prepare_posts_text(self, posts_data) -> str:
        if not posts_data:
            return ""
        out = ["Facebook Posts Data for Analysis:\n"]
        for i, post in enumerate(posts_data, 1):
            out.append(f"Post {i}:")
            out.append(f"Author: {post.get('author', 'N/A')}")
            out.append(f"Shared by: {post.get('shared_by', 'N/A')}")
            out.append(f"Content: {post.get('post_content', 'N/A')}")
            out.append(f"Reactions: {post.get('reactions', 'N/A')}")
            out.append(f"Comments: {post.get('comments', 'N/A')}")
            out.append(f"Shares: {post.get('shares', 'N/A')}")
            out.append(f"Image Description: {post.get('image_description', 'N/A')}")
            out.append("-" * 50)
        return "\n".join(out)

    def analyze_posts_summary(self, posts_data) -> str:
        if not posts_data:
            return "No data available for analysis."
        posts_text = self.prepare_posts_text(posts_data)
        if len(posts_text) > 50000:
            posts_text = posts_text[:50000] + "\n[Content truncated due to length]"
            print("Content truncated due to length limitations")
        try:
            print("Sending data to cascade LLM for analysis...")
            out = chat_json(SYS,
                            f"Analyze the following Facebook posts data:\n\n{posts_text}",
                            max_tokens=500, stage="rag")
            summary = str(out.get("summary", "")).strip()
            print("Analysis completed successfully!")
            return summary or "No summary returned."
        except Exception as e:
            print(f"Error during analysis: {e}")
            return f"Error occurred during analysis: {e}"

    def save_summary(self, summary: str, output_path: str = "data/facebook_posts_summary.txt") -> bool:
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("Facebook Posts Analysis Summary\n")
                f.write("=" * 40 + "\n\n")
                f.write(summary)
            print(f"Summary saved to {output_path}")
            return True
        except Exception as e:
            print(f"Error saving summary: {e}")
            return False

    def run_analysis(self, input_file: str = "data/facebook_posts_all.json",
                     output_file: str = "data/facebook_posts_summary.txt"):
        print("Starting Facebook posts analysis...")
        posts_data = self.load_posts_data(input_file)
        if not posts_data:
            return None
        summary = self.analyze_posts_summary(posts_data)
        self.save_summary(summary, output_file)
        print("\n" + "=" * 50)
        print("FACEBOOK POSTS ANALYSIS SUMMARY")
        print("=" * 50)
        print(summary)
        print("=" * 50)
        return summary
