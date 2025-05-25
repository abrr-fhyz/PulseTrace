#!/usr/bin/env python3
"""
Simple Flask server for Facebook Analysis Tools Frontend
"""

import os
import subprocess
import threading
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

def run_command_async(command):
    """Run command in background thread"""
    try:
        result = subprocess.run(['python', 'main.py', command], 
                               capture_output=True, text=True, timeout=3600)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out after 1 hour"
    except Exception as e:
        return False, "", str(e)

def count_files_in_directory(directory, extension=None, exclude_pattern=None):
    """Count files in directory with optional filtering"""
    if not os.path.exists(directory):
        return 0
    
    count = 0
    try:
        for filename in os.listdir(directory):
            if extension and not filename.lower().endswith(extension):
                continue
            if exclude_pattern and exclude_pattern.lower() in filename.lower():
                continue
            count += 1
    except PermissionError:
        return 0
    
    return count

def read_file_content(filepath, max_chars=None):
    """Read file content with optional size limit"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if max_chars and len(content) > max_chars:
                    return content[:max_chars] + "..."
                return content
        return "File not found"
    except Exception as e:
        return f"Error reading file: {str(e)}"

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('index.html')

@app.route('/status')
def get_status():
    """Get current status of directories and files"""
    try:
        # Count screenshots (assuming common image extensions)
        screenshot_count = sum([
            count_files_in_directory('screenshots', '.png'),
            count_files_in_directory('screenshots', '.jpg'),
            count_files_in_directory('screenshots', '.jpeg'),
            count_files_in_directory('screenshots', '.gif'),
            count_files_in_directory('screenshots', '.bmp')
        ])
        
        # Count JSON files in data directory that don't contain "facebook"
        json_count = count_files_in_directory('data', '.json', 'facebook')
        
        # Read summary text
        summary_text = read_file_content('data/facebook_posts_summary.txt')
        
        return jsonify({
            'screenshots': screenshot_count,
            'json_files': json_count,
            'summary': summary_text
        })
    except Exception as e:
        return jsonify({
            'screenshots': 'Error',
            'json_files': 'Error', 
            'summary': f'Error: {str(e)}'
        }), 500

@app.route('/run-command', methods=['POST'])
def run_command():
    """Execute a command through main.py"""
    try:
        data = request.get_json()
        command = data.get('command')
        
        if command not in ['scrape', 'process', 'summarize']:
            return jsonify({'success': False, 'error': 'Invalid command'}), 400
        
        # Run command in background thread to avoid blocking
        def run_in_background():
            success, stdout, stderr = run_command_async(command)
            # Store result somewhere if needed for later retrieval
        
        thread = threading.Thread(target=run_in_background)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': f'{command} started successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print("Starting Facebook Analysis Tools Server...")
    print("Open your browser and go to: http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)