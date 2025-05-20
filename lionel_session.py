#!/usr/bin/python
# -*- coding:utf-8 -*-
import os
import sys
import time
import json
import logging
import requests
from bs4 import BeautifulSoup

# Try to import dotenv for loading environment variables
try:
    from dotenv import load_dotenv
    # Get the directory of the current script
    script_dir = os.path.dirname(os.path.realpath(__file__))
    # Load environment variables from .env file in the script directory
    env_path = os.path.join(script_dir, '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        logging.info(f"Loaded environment from: {env_path}")
        dotenv_loaded = True
    else:
        load_dotenv()  # Try default locations
        logging.warning(f".env file not found at {env_path}, trying default locations")
        dotenv_loaded = True
except ImportError:
    dotenv_loaded = False
    logging.warning("python-dotenv not found. Environment variables will only be loaded from system environment.")

# Configure logging
logging.basicConfig(level=logging.INFO)

"""
Lionel Session Management Module

This module handles authentication and session management for the KGV Lionel website.
It manages obtaining, storing, and refreshing session tokens for API access.

Usage:
1. Set environment variables LIONEL_USERNAME and LIONEL_PASSWORD
   or add them to your .env file which is loaded by python-dotenv

2. To get a session token:
   from lionel_session import get_session_token
   session = get_session_token()

3. To get just the cookies for making requests:
   from lionel_session import get_session_cookies
   cookies = get_session_cookies()
   response = requests.get(url, cookies=cookies)

Note: The session token is cached to a local file and reused until it expires.
"""

# Constants
LIONEL_BASE_URL = "https://lionel2.kgv.edu.hk"
LOGIN_URL = f"{LIONEL_BASE_URL}/login/index.php"
SESSION_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'session.json')
SESSION_TIMEOUT = 3 * 60 * 60  # 3 hours in seconds

def get_session_token(username=None, password=None):
    """Get a valid session token for the Lionel website
    
    Attempts to use cached session first. If no valid session exists or provided,
    it will try to log in with credentials from environment or provided params.
    
    Args:
        username: Optional username to use (defaults to environment variable)
        password: Optional password to use (defaults to environment variable)
        
    Returns:
        dict: Session cookies and info or None if login fails
    """
    # First, try to use cached session
    session_data = load_session()
    if is_valid_session(session_data):
        logging.info("Using cached session")
        return session_data
    
    # No valid session, try to login
    logging.info("No valid session found, attempting to login")
    
    # Get credentials from environment if not provided
    if username is None:
        username = os.getenv("LIONEL_USERNAME")
    if password is None:
        password = os.getenv("LIONEL_PASSWORD")
    
    if not username or not password:
        if dotenv_loaded:
            logging.error("No credentials available. Add LIONEL_USERNAME and LIONEL_PASSWORD to your .env file")
        else:
            logging.error("No credentials available. Set LIONEL_USERNAME and LIONEL_PASSWORD environment variables")
        return None
    
    logging.info(f"Attempting login with username: {username}")
    # Attempt login
    return login_to_lionel(username, password)

def load_session():
    """Load session data from file if it exists"""
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logging.error(f"Error loading session file: {e}")
    
    return None

def save_session(session_data):
    """Save session data to file"""
    try:
        with open(SESSION_FILE, 'w') as f:
            json.dump(session_data, f)
        logging.info("Session saved to file")
    except Exception as e:
        logging.error(f"Error saving session file: {e}")

def is_valid_session(session_data):
    """Check if the session data is valid and not expired"""
    if not session_data:
        return False
    
    # Check if the session has expired
    timestamp = session_data.get('timestamp', 0)
    if time.time() - timestamp > SESSION_TIMEOUT:
        logging.info("Session has expired")
        return False
    
    # Try to make a test request to verify the session is still valid
    try:
        cookies = {
            name: value for name, value in session_data.get('cookies', {}).items()
        }
        
        # Make a request to a protected page
        test_url = f"{LIONEL_BASE_URL}/my/"
        response = requests.get(test_url, cookies=cookies, timeout=10, allow_redirects=True)
        
        # If we get redirected to the login page, the session is invalid
        if 'login' in response.url:
            logging.info("Session cookies are no longer valid - redirected to login page")
            return False
            
        # Check if we can find the user's name or a logout link on the page
        # This is a more robust way to check if the session is valid
        username = session_data.get('username', '')
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for elements that would indicate a valid session
        user_elements = soup.find_all(string=lambda text: username in text if text else False)
        logout_link = soup.find('a', string='Logout') or soup.find('a', string='Log out')
        
        if user_elements or logout_link or response.status_code == 200:
            logging.info("Session appears to be valid")
            return True
            
        logging.info(f"Session validation uncertain - status code: {response.status_code}")
        return False
    except Exception as e:
        logging.error(f"Error testing session validity: {e}")
        return False

def login_to_lionel(username, password):
    """Login to the Lionel website and return session data
    
    Args:
        username: Login username
        password: Login password
        
    Returns:
        dict: Session data including cookies and timestamp if successful, None otherwise
    """
    try:
        session = requests.Session()
        
        # Get login page to extract login token
        logging.info("Fetching login page")
        login_page = session.get(LOGIN_URL)
        
        # Check if the page was retrieved successfully
        if login_page.status_code != 200:
            logging.error(f"Failed to retrieve login page. Status code: {login_page.status_code}")
            return None
            
        # Save the login page HTML for debugging
        debug_html_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'login_page_debug.html')
        with open(debug_html_path, 'w', encoding='utf-8') as f:
            f.write(login_page.text)
        logging.info(f"Saved login page HTML for debugging to: {debug_html_path}")
        
        soup = BeautifulSoup(login_page.content, 'html.parser')
        
        # Extract any potential login token from the page
        login_token = None
        
        # Try to find any logintoken input
        token_input = soup.find('input', {'name': 'logintoken'})
        if token_input:
            login_token = token_input.get('value')
            logging.info("Found login token: %s", login_token)
        
        # If we couldn't find a logintoken, try to extract session key from page
        # This is an alternate approach since the login form doesn't have a login token
        if not login_token:
            # Try to find the session key in JavaScript
            scripts = soup.find_all('script')
            sess_key = None
            for script in scripts:
                if script.string and 'sesskey' in script.string:
                    import re
                    match = re.search(r'sesskey":"([^"]+)"', script.string)
                    if match:
                        sess_key = match.group(1)
                        logging.info("Found session key in script: %s", sess_key)
                        break
            
            # If we found a session key, we'll use that instead
            if sess_key:
                login_token = sess_key
        
        # Prepare login data - note we're still proceeding without a login token
        # if one doesn't exist, as the site may not require it
        login_data = {
            'username': username,
            'password': password,
            'anchor': ''
        }
        
        # Add login token if we found one
        if login_token:
            login_data['logintoken'] = login_token
        
        # Submit login form
        logging.info("Submitting login request")
        login_response = session.post(LOGIN_URL, data=login_data)
        
        # Log full URL after attempted login for debugging
        logging.info(f"Login response URL: {login_response.url}")
        
        # Check response headers for redirect information
        if 'Location' in login_response.headers:
            logging.info(f"Redirect location: {login_response.headers['Location']}")
        
        # Check if login was successful 
        # Success criteria: either redirected away from login page or username appears in response
        login_successful = False
        
        # Method 1: Check if we're not on the login page anymore
        if 'login' not in login_response.url:
            login_successful = True
            logging.info("Login successful - redirected to non-login page")
            
        # Method 2: Check if login failed message appears on the page
        if not login_successful:
            login_soup = BeautifulSoup(login_response.content, 'html.parser')
            if login_soup.find('div', class_='loginerrors'):
                logging.error("Login failed - error message found on page")
                return None
            
        # Method 3: Check if we can find the user's name or a logout link on the page
        if not login_successful:
            login_soup = BeautifulSoup(login_response.content, 'html.parser')
            # Look for elements that would indicate a successful login
            user_elements = login_soup.find_all(string=lambda text: username in text if text else False)
            logout_link = login_soup.find('a', string='Logout') or login_soup.find('a', string='Log out')
            
            if user_elements or logout_link:
                login_successful = True
                logging.info("Login successful - user elements found on page")
        
        # If all checks failed, make a request to another page to confirm login
        if not login_successful:
            try:
                dashboard_url = f"{LIONEL_BASE_URL}/my/"
                dashboard_resp = session.get(dashboard_url)
                if 'login' not in dashboard_resp.url:
                    login_successful = True
                    logging.info("Login successful - able to access dashboard")
            except Exception as e:
                logging.error(f"Error checking dashboard access: {e}")
                
        if not login_successful:
            logging.error("Login appears to have failed - could not confirm successful authentication")
            return None
            
        # Get the cookies from the session
        cookies = session.cookies.get_dict()
        
        # Print out all cookies for debugging
        logging.info("Retrieved cookies:")
        for name, value in cookies.items():
            masked_value = value[:5] + "..." if len(value) > 10 else value
            logging.info(f"  - {name}: {masked_value}")
        
        # Create session data with timestamp
        session_data = {
            'cookies': cookies,
            'timestamp': time.time(),
            'username': username
        }
        
        # Save the session data
        save_session(session_data)
        
        logging.info("Login successful")
        return session_data
        
    except Exception as e:
        logging.error(f"Login error: {e}")
        return None

def get_session_cookies():
    """Get just the cookies from the session data in a format usable by requests
    
    Returns:
        dict: Cookie dict or empty dict if no valid session
    """
    session_data = get_session_token()
    if session_data:
        return session_data.get('cookies', {})
    return {}

if __name__ == '__main__':
    # Test the session management
    session = get_session_token()
    if session:
        print("Session obtained successfully")
        print(f"Cookies: {session.get('cookies')}")
    else:
        print("Failed to get session")
