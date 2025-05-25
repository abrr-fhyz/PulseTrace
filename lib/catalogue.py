import os
import glob
import base64
import pandas as pd
import re
import time
from openai import OpenAI
import json

class FacebookScreenshotAnalyzer:
    def __init__(self, api_key):
        """Initialize the Facebook Screenshot Analyzer."""

        # Initialize OpenAI client with explicit error display
        self.api_key = api_key
        if not self.api_key:
            raise ValueError("No OpenAI API key found in .env file")

        self.client = OpenAI(api_key=self.api_key)
        
        # Create data directory if it doesn't exist
        if not os.path.exists('data'):
            os.makedirs('data')

    def get_image_base64(self, image_path):
        """Convert image to base64 string."""
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            print(f"Error encoding image {image_path}: {e}")
            return ""

    def extract_json_from_text(self, text):
        """Extract JSON from text that might contain other content."""
        # Try to find JSON object in the text
        json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        matches = re.findall(json_pattern, text, re.DOTALL)
        
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue
        
        # If no valid JSON found, return None
        return None

    def create_fallback_structure(self, filename, error_msg=""):
        """Create a fallback data structure when parsing fails."""
        return {
            "author": "",
            "shared_by": "",
            "post_content": "",
            "reactions": "",
            "comments": "",
            "shares": "",
            "image_description": "",
            "filename": filename,
            "error": error_msg if error_msg else "Failed to extract data"
        }

    def analyze_screenshot(self, image_path):
        """Analyze Facebook screenshot using OpenAI Vision."""
        filename = os.path.basename(image_path)
        print(f"Starting analysis for {filename}...")
        
        try:
            # Verify the file exists and can be read
            if not os.path.exists(image_path):
                print(f"File not found: {image_path}")
                return self.create_fallback_structure(filename, "File not found")
                
            # Get file size to check if it's reasonable
            file_size = os.path.getsize(image_path) / (1024 * 1024)  # Size in MB
            print(f"File size: {file_size:.2f} MB")
            
            if file_size > 20:
                print(f"Warning: File size exceeds 20MB ({file_size:.2f}MB)")
            
            # Convert image to base64
            base64_image = self.get_image_base64(image_path)
            if not base64_image:
                return self.create_fallback_structure(filename, "Failed to encode image")
            
            print(f"Image encoded successfully, sending to API...")
            
            # Try API call with guaranteed JSON parsing
            models_to_try = ["gpt-4o-mini", "gpt-4o"]
            
            for model in models_to_try:
                try:
                    print(f"Trying with model: {model}")
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a data extraction assistant. Extract information from Facebook screenshots and return ONLY valid JSON."
                            },
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Extract the following from this Facebook screenshot and return ONLY a valid JSON object:\n\n"
                                                          "{\n"
                                                          "  \"author\": \"name of original poster\",\n"
                                                          "  \"shared_by\": \"name of person who shared (if applicable, otherwise empty string)\",\n"
                                                          "  \"post_content\": \"text content of post if any, otherwise empty string\",\n"
                                                          "  \"reactions\": \"number and types of reactions, if visible\",\n"
                                                          "  \"comments\": \"number of comments, if visible\",\n"
                                                          "  \"shares\": \"number of shares if visible\",\n"
                                                          "  \"image_description\": \"description of any images in the post itself if present, otherwise leave empty\"\n"
                                                          "}\n\n"
                                                          "Return ONLY the JSON in THIS SPECIFIC FORMAT with NO ADDITIONAL text or formatting."},
                                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                                ]
                            }
                        ],
                        max_completion_tokens=1000
                    )
                    
                    # Get response content
                    content = response.choices[0].message.content
                    if not content:
                        print("Warning: Empty content received from API")
                        continue
                    
                    content = content.strip()
                    print(f"Response content (first 100 chars): {content[:100]}...")
                    
                    # Try to parse as JSON directly first
                    try:
                        result = json.loads(content)
                        print("Successfully parsed JSON response directly")
                        result["filename"] = filename
                        return result
                    except json.JSONDecodeError:
                        print("Direct JSON parsing failed, trying to extract JSON from text")
                        
                        # Try to extract JSON from the text
                        extracted_json = self.extract_json_from_text(content)
                        if extracted_json:
                            print("Successfully extracted JSON from text")
                            extracted_json["filename"] = filename
                            return extracted_json
                        else:
                            print("Failed to extract JSON from text, continuing to next model")
                            continue
                
                except Exception as api_error:
                    print(f"API call error with {model}: {api_error}")
                    continue
            
            # If all models failed, return fallback structure
            print("All API attempts failed, returning fallback structure")
            return self.create_fallback_structure(filename, "All API attempts failed")
        
        except Exception as e:
            print(f"Critical error analyzing image: {str(e)}")
            return self.create_fallback_structure(filename, f"Critical error: {str(e)}")

    def save_json(self, data, filepath):
        """Save data as JSON file."""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Data saved to {filepath}")
            return True
        except Exception as e:
            print(f"Error saving JSON to {filepath}: {e}")
            return False

    def process_screenshots(self, screenshots_dir='screenshots', output_dir='data'):
        """Process all PNG files in the screenshots directory and save results as JSON."""
        # Get all PNG files in the screenshots directory
        screenshot_files = glob.glob(f'{screenshots_dir}/*.png')
        
        if not screenshot_files:
            print(f"No PNG files found in '{screenshots_dir}' directory!")
            return
        
        print(f"Found {len(screenshot_files)} PNG files to process.")
        
        # Create output directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        # Prepare data collection
        all_data = []
        
        for i, screenshot_file in enumerate(screenshot_files):
            print(f"\n{'='*50}")
            print(f"Processing {i+1}/{len(screenshot_files)}: {os.path.basename(screenshot_file)}")
            
            # Analyze the screenshot with OpenAI
            analysis = self.analyze_screenshot(screenshot_file)
            
            # Add to data list
            all_data.append(analysis)
            
            # Save individual JSON file
            filename_base = os.path.splitext(os.path.basename(screenshot_file))[0]
            json_path = os.path.join(output_dir, f"{filename_base}.json")
            self.save_json(analysis, json_path)
            
            # Save progress after each batch
            if (i+1) % 5 == 0 or i+1 == len(screenshot_files):
                print(f"Saving progress after {i+1} files...")
                progress_path = os.path.join(output_dir, f"facebook_posts_progress_{i+1}.json")
                self.save_json(all_data, progress_path)
            
            # Sleep to avoid rate limiting
            if i < len(screenshot_files) - 1:
                print("Waiting before next file...")
                time.sleep(3)
        
        # Save final consolidated JSON file
        final_json_path = os.path.join(output_dir, "facebook_posts_all.json")
        self.save_json(all_data, final_json_path)
        
        print(f"\nProcessed {len(all_data)} screenshots. Results saved to {final_json_path}")
        
        return all_data