import json
from openai import OpenAI
import os

class FacebookPostsSummaryAnalyzer:
    def __init__(self, api_key):
        """Initialize the Facebook Posts Summary Analyzer."""
        self.api_key = api_key
        if not self.api_key:
            raise ValueError("No OpenAI API key provided")
        
        self.client = OpenAI(api_key=self.api_key)
    
    def load_posts_data(self, file_path='data/facebook_posts_all.json'):
        """Load the Facebook posts JSON data."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
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
    
    def prepare_posts_text(self, posts_data):
        """Convert posts data to readable text format for analysis."""
        if not posts_data:
            return ""
        
        posts_text = "Facebook Posts Data for Analysis:\n\n"
        
        for i, post in enumerate(posts_data, 1):
            posts_text += f"Post {i}:\n"
            posts_text += f"Author: {post.get('author', 'N/A')}\n"
            posts_text += f"Shared by: {post.get('shared_by', 'N/A')}\n"
            posts_text += f"Content: {post.get('post_content', 'N/A')}\n"
            posts_text += f"Reactions: {post.get('reactions', 'N/A')}\n"
            posts_text += f"Comments: {post.get('comments', 'N/A')}\n"
            posts_text += f"Shares: {post.get('shares', 'N/A')}\n"
            posts_text += f"Image Description: {post.get('image_description', 'N/A')}\n"
            posts_text += "-" * 50 + "\n"
        
        return posts_text
    
    def analyze_posts_summary(self, posts_data):
        """Send posts to GPT-4o and get summary analysis."""
        if not posts_data:
            return "No data available for analysis."
        
        posts_text = self.prepare_posts_text(posts_data)
        
        # Truncate if too long (GPT has token limits)
        if len(posts_text) > 50000:  # Rough character limit
            posts_text = posts_text[:50000] + "\n[Content truncated due to length]"
            print("Content truncated due to length limitations")
        
        try:
            print("Sending data to GPT-4o for analysis...")
            
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert social media analyst. Analyze Facebook posts data and provide insights about trends, popular posts, overall mood, and notable patterns."
                    },
                    {
                        "role": "user",
                        "content": f"""Analyze the following Facebook posts data and provide a comprehensive summary in exactly 2 paragraphs (150-200 words total).

Focus on:
1. General highlights and most popular posts (based on reactions, comments, shares)
2. Overall mood of the posts (Optimistic, Pessimistic, Skeptical, Ironic, etc.)
3. Notable trends, themes, or patterns
4. Any interesting observations about user engagement

Data to analyze:

{posts_text}

Please provide your analysis in exactly 2 well-structured paragraphs totaling 150-200 words."""
                    }
                ],
                max_completion_tokens=300,
                temperature=0.7
            )
            
            summary = response.choices[0].message.content
            print("Analysis completed successfully!")
            return summary.strip()
            
        except Exception as e:
            print(f"Error during analysis: {e}")
            return f"Error occurred during analysis: {str(e)}"
    
    def save_summary(self, summary, output_path='data/facebook_posts_summary.txt'):
        """Save the summary to a text file."""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("Facebook Posts Analysis Summary\n")
                f.write("=" * 40 + "\n\n")
                f.write(summary)
            
            print(f"Summary saved to {output_path}")
            return True
        except Exception as e:
            print(f"Error saving summary: {e}")
            return False
    
    def run_analysis(self, input_file='data/facebook_posts_all.json', output_file='data/facebook_posts_summary.txt'):
        """Run complete analysis pipeline."""
        print("Starting Facebook posts analysis...")
        
        # Load posts data
        posts_data = self.load_posts_data(input_file)
        if not posts_data:
            return None
        
        # Analyze with GPT-4o
        summary = self.analyze_posts_summary(posts_data)
        
        # Save summary
        self.save_summary(summary, output_file)
        
        # Print summary to console
        print("\n" + "="*50)
        print("FACEBOOK POSTS ANALYSIS SUMMARY")
        print("="*50)
        print(summary)
        print("="*50)
        
        return summary