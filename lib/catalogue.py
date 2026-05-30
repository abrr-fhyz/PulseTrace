"""V1 Facebook screenshot analyzer — Gemini Vision via REST.

Converted from OpenAI gpt-4o-mini Vision to Gemini 2.5-flash-lite with
fallback to 2.0-flash. Same JSON output shape so downstream summary.py
keeps working.
"""
from __future__ import annotations
import base64
import glob
import json
import os
import re
import time
from pathlib import Path

import requests


GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

PROMPT = (
    "Extract the following from this Facebook screenshot and return ONLY a "
    "valid JSON object:\n\n"
    "{\n"
    '  "author": "name of original poster",\n'
    '  "shared_by": "name of person who shared (if applicable, otherwise empty string)",\n'
    '  "post_content": "text content of post if any, otherwise empty string",\n'
    '  "reactions": "number and types of reactions, if visible",\n'
    '  "comments": "number of comments, if visible",\n'
    '  "shares": "number of shares if visible",\n'
    '  "image_description": "description of any images in the post itself if present, otherwise leave empty"\n'
    "}\n\n"
    "Return ONLY the JSON. No prose, no markdown fence."
)


def _strip_fence(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.MULTILINE).strip()
    return s


class FacebookScreenshotAnalyzer:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("gemini_api_key", "")
        if not self.api_key:
            raise ValueError("No GEMINI_API_KEY found (set in .env.api_keys)")
        if not os.path.exists("data"):
            os.makedirs("data")

    def get_image_base64(self, image_path: str) -> str:
        try:
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            print(f"Error encoding image {image_path}: {e}")
            return ""

    def create_fallback_structure(self, filename: str, error_msg: str = "") -> dict:
        return {
            "author": "",
            "shared_by": "",
            "post_content": "",
            "reactions": "",
            "comments": "",
            "shares": "",
            "image_description": "",
            "filename": filename,
            "error": error_msg or "Failed to extract data",
        }

    def _call_gemini(self, model: str, b64: str) -> dict | None:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={self.api_key}")
        payload = {
            "contents": [{
                "parts": [
                    {"text": PROMPT},
                    {"inline_data": {"mime_type": "image/png", "data": b64}},
                ],
            }],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
            },
        }
        r = requests.post(url, json=payload, timeout=60)
        r.raise_for_status()
        body = r.json()
        cands = body.get("candidates") or []
        if not cands:
            return None
        parts = cands[0].get("content", {}).get("parts") or []
        txt = _strip_fence("".join(p.get("text", "") for p in parts))
        try:
            return json.loads(txt)
        except Exception:
            return None

    def analyze_screenshot(self, image_path: str) -> dict:
        filename = os.path.basename(image_path)
        print(f"Starting analysis for {filename}...")
        if not os.path.exists(image_path):
            return self.create_fallback_structure(filename, "File not found")
        size_mb = os.path.getsize(image_path) / (1024 * 1024)
        print(f"File size: {size_mb:.2f} MB")
        b64 = self.get_image_base64(image_path)
        if not b64:
            return self.create_fallback_structure(filename, "Failed to encode image")

        for model in GEMINI_MODELS:
            for attempt in range(3):
                try:
                    print(f"Trying model {model} attempt {attempt + 1}")
                    out = self._call_gemini(model, b64)
                    if out is not None:
                        out["filename"] = filename
                        return out
                    break
                except requests.HTTPError as e:
                    code = getattr(e.response, "status_code", 0)
                    if code == 429:
                        sleep_s = 4 * (attempt + 1)
                        print(f"  429 rate-limit; sleeping {sleep_s}s")
                        time.sleep(sleep_s)
                        continue
                    print(f"  HTTP {code}; trying next model")
                    break
                except Exception as e:
                    print(f"  {type(e).__name__}: {e}")
                    break
        return self.create_fallback_structure(filename, "All Gemini models failed")

    def save_json(self, data, filepath: str) -> bool:
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Data saved to {filepath}")
            return True
        except Exception as e:
            print(f"Error saving JSON to {filepath}: {e}")
            return False

    def process_screenshots(self, screenshots_dir: str = "screenshots",
                            output_dir: str = "data") -> list[dict]:
        files = glob.glob(f"{screenshots_dir}/*.png")
        if not files:
            print(f"No PNG files found in '{screenshots_dir}' directory!")
            return []
        print(f"Found {len(files)} PNG files to process.")
        os.makedirs(output_dir, exist_ok=True)
        all_data: list[dict] = []
        for i, shot in enumerate(files):
            print(f"\n{'='*50}")
            print(f"Processing {i + 1}/{len(files)}: {os.path.basename(shot)}")
            analysis = self.analyze_screenshot(shot)
            all_data.append(analysis)
            base = os.path.splitext(os.path.basename(shot))[0]
            self.save_json(analysis, os.path.join(output_dir, f"{base}.json"))
            if (i + 1) % 5 == 0 or i + 1 == len(files):
                self.save_json(all_data,
                               os.path.join(output_dir,
                                            f"facebook_posts_progress_{i + 1}.json"))
            if i < len(files) - 1:
                time.sleep(3)
        self.save_json(all_data, os.path.join(output_dir, "facebook_posts_all.json"))
        print(f"\nProcessed {len(all_data)} screenshots.")
        return all_data
