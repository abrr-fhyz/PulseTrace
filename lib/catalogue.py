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

    def analyze_screenshot(self, image_path):
        """Analyze Facebook screenshot using OpenAI Vision."""
        filename = os.path.basename(image_path)
        print(f"Starting analysis for {filename}...")
        
        try:
            # Verify the file exists and can be read
            if not os.path.exists(image_path):
                print(f"File not found: {image_path}")
                return {"error": "File not found", "filename": filename}
                
            # Get file size to check if it's reasonable
            file_size = os.path.getsize(image_path) / (1024 * 1024)  # Size in MB
            print(f"File size: {file_size:.2f} MB")
            
            if file_size > 20:
                print(f"Warning: File size exceeds 20MB ({file_size:.2f}MB)")
            
            # Convert image to base64
            base64_image = self.get_image_base64(image_path)
            if not base64_image:
                return {"error": "Failed to encode image", "filename": filename}
            
            print(f"Image encoded successfully, sending to API...")
            
            # First try: see if we can get valid JSON directly
            try:
                response = self.client.chat.completions.create(
                    model="o4-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a data extraction assistant. Extract information from Facebook screenshots and return only valid JSON."
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Extract the following from this Facebook screenshot and return ONLY a valid JSON object:\n\n"
                                                      "{\n"
                                                      "  \"author\": \"name of original poster\",\n"
                                                      "  \"shared_by\": \"name of person who shared (if applicable, otherwise empty string)\",\n"
                                                      "  \"post_content\": \"text content of post\",\n"
                                                      "  \"reactions\": \"number and types of reactions\",\n"
                                                      "  \"comments\": \"number of comments\",\n"
                                                      "  \"shares\": \"number of shares if visible\",\n"
                                                      "  \"image_description\": \"description of any images in post\"\n"
                                                      "}\n\n"
                                                      "Return ONLY the JSON with no additional text or formatting."},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                            ]
                        }
                    ],
                    max_completion_tokens=1000
                )
                
                # Debug the complete response object
                print(f"API Response received. Status: {response.model_dump()['object']}")
                
                # Check if we got a valid content response
                content = response.choices[0].message.content
                if not content:
                    print("Warning: Empty content received from API")
                    content = ""
                else:
                    content = content.strip()
                    print(f"Response content (first 100 chars): {content[:100]}...")
                
                # Try to parse as JSON directly
                try:
                    result = json.loads(content)
                    print("Successfully parsed JSON response")
                    result["filename"] = filename
                    return result
                except json.JSONDecodeError as e:
                    print(f"Initial JSON parsing failed: {e}")
                    # Continue to fallback methods
            
            except Exception as api_error:
                print(f"API call error: {api_error}")
                # Try with a simpler approach
            
            # Second try: Use a simpler prompt and manually extract fields
            print("Trying simplified approach...")
            
            # Create a basic structured response
            structured_data = {
                "author": "",
                "shared_by": "",
                "post_content": "",
                "reactions": "",
                "comments": "",
                "shares": "",
                "image_description": "",
                "filename": filename
            }
            
            # Try a simpler API call
            try:
                simple_response = self.client.chat.completions.create(
                    model="o4-mini",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Describe this Facebook post screenshot. Include who posted it, any text content, reactions, comments, and description of images."},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                            ]
                        }
                    ],
                    max_completion_tokens=1000
                )
                
                simple_content = simple_response.choices[0].message.content
                print(f"Simple response received (first 100 chars): {simple_content[:100]}...")
                
                # Use regex to extract information
                author_match = re.search(r"(?:posted|shared) by[:\s]+([^,.\n]+)", simple_content, re.IGNORECASE)
                if author_match:
                    structured_data["author"] = author_match.group(1).strip()
                    
                content_match = re.search(r"content[:\s]+\"([^\"]+)\"", simple_content, re.IGNORECASE)
                if content_match:
                    structured_data["post_content"] = content_match.group(1).strip()
                    
                reactions_match = re.search(r"(\d+)\s+(?:reactions|likes)", simple_content, re.IGNORECASE)
                if reactions_match:
                    structured_data["reactions"] = reactions_match.group(1).strip()
                    
                comments_match = re.search(r"(\d+)\s+comments", simple_content, re.IGNORECASE)
                if comments_match:
                    structured_data["comments"] = comments_match.group(1).strip()
                
                # Add the raw description as image description
                structured_data["image_description"] = simple_content
                
                print(f"Extracted data from simple approach: {structured_data}")
                return structured_data
                
            except Exception as simple_error:
                print(f"Simple approach error: {simple_error}")
                structured_data["error"] = f"API error: {str(simple_error)}"
                return structured_data
        
        except Exception as e:
            print(f"Critical error analyzing image: {str(e)}")
            return {
                "error": f"Error analyzing image: {str(e)}",
                "filename": filename
            }

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

