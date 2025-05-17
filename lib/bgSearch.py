import json
import requests
import argparse
from urllib.parse import urlencode

def load_json_data(file_path):
    """Load JSON data from file"""
    with open(file_path, 'r') as file:
        return json.load(file)

def calculate_engagement(post):
    """Calculate total engagement (reactions + comments) for a post"""
    try:
        # Extract numeric value from reactions string (e.g., "10 Love" -> 10)
        reactions = int(post['reactions'].split()[0]) if post.get('reactions') else 0
    except (ValueError, AttributeError):
        reactions = 0
    
    try:
        comments = int(post['comments']) if post.get('comments') else 0
    except (ValueError, AttributeError):
        comments = 0
    
    return reactions + comments

def get_facebook_user_data(access_token, user_name, fields='id,name'):
    """Get user data from Facebook Graph API"""
    base_url = 'https://graph.facebook.com/v12.0/search'
    
    params = {
        'q': user_name,
        'type': 'user',
        'fields': fields,
        'access_token': access_token
    }
    
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'data' in data and len(data['data']) > 0:
            return data['data'][0]  # Return first match
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for {user_name}: {e}")
        return None

def process_data(data, threshold, access_token):
    """Process JSON data and find users above engagement threshold"""
    high_engagement_users = {}
    
    for post in data:
        engagement = calculate_engagement(post)
        
        if engagement >= threshold:
            author = post.get('author', 'Unknown')
            shared_by = post.get('shared_by', None)
            
            # Avoid duplicate API calls for same user
            if author not in high_engagement_users:
                user_data = get_facebook_user_data(access_token, author)
                if user_data:
                    high_engagement_users[author] = {
                        'user_data': user_data,
                        'engagement': engagement,
                        'posts': [post]
                    }
                else:
                    print(f"Could not find data for author: {author}")
            
            # Also check shared_by if it exists
            if shared_by and shared_by not in high_engagement_users:
                user_data = get_facebook_user_data(access_token, shared_by)
                if user_data:
                    high_engagement_users[shared_by] = {
                        'user_data': user_data,
                        'engagement': engagement,
                        'posts': [post]
                    }
    
    return high_engagement_users

def main():
    parser = argparse.ArgumentParser(description='Find Facebook users with high engagement')
    parser.add_argument('--input', required=False, help='Path to input JSON file')
    parser.add_argument('--threshold', type=int, default=20, 
                       help='Engagement threshold (reactions + comments)')
    parser.add_argument('--access-token', required=True, 
                       help='Facebook Graph API access token')
    parser.add_argument('--output', default='high_engagement_users.json',
                       help='Output file path')
    
    args = parser.parse_args()
    default_dir = "../data/facebook_posts_all.json"
    if args.input:
        default_dir = args.input

    
    # Load data
    data = load_json_data(default_dir)
    
    # Process data
    high_engagement_users = process_data(data, args.threshold, args.access_token)
    
    # Save results
    with open(args.output, 'w') as outfile:
        json.dump(high_engagement_users, outfile, indent=2)
    
    print(f"Found {len(high_engagement_users)} users with engagement ≥ {args.threshold}")
    print(f"Results saved to {args.output}")

if __name__ == '__main__':
    main()