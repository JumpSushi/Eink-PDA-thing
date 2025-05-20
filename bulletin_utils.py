#!/usr/bin/python
# -*- coding:utf-8 -*-
import os
import sys
import time
import json
import logging
import threading
import re
from bs4 import BeautifulSoup
import queue
from PIL import Image, ImageDraw
import datetime # Added import

# Configure logging
logging.basicConfig(level=logging.INFO)

# Global cache variables
cached_bulletin_items = None
last_bulletin_update_time = None
bulletin_cache_loaded_from_file = False # ADDED: Flag to track if cache has been loaded from file

try:
    import requests
except ImportError:
    requests = None

# Constants
BULLETIN_URL = "https://lionel2.kgv.edu.hk/local/mis/bulletin/bulletin.php"
BULLETIN_UPDATE_INTERVAL = 1800  # Update bulletin every 30 minutes (1800 seconds)
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__)) # ADDED: Script directory
BULLETIN_CACHE_FILE = os.path.join(SCRIPT_DIR, 'bulletin_cache.json') # ADDED: Cache file path

# Define update times (8 AM and 4 PM)
UPDATE_HOUR_1 = 8
UPDATE_HOUR_2 = 16

# ADDED HELPER FUNCTIONS TO LOAD AND SAVE CACHE FROM/TO FILE
def _load_bulletin_from_file():
    """Load bulletin data from cache file if it exists."""
    global cached_bulletin_items, last_bulletin_update_time, bulletin_cache_loaded_from_file
    if os.path.exists(BULLETIN_CACHE_FILE):
        try:
            with open(BULLETIN_CACHE_FILE, 'r') as f:
                data = json.load(f)
                cached_bulletin_items = data.get('items')
                last_bulletin_update_time = data.get('timestamp')
                if cached_bulletin_items is not None and last_bulletin_update_time is not None:
                    logging.info(f"Loaded bulletin cache from {BULLETIN_CACHE_FILE}")
                else:
                    logging.warning(f"Bulletin cache file {BULLETIN_CACHE_FILE} is malformed. Will fetch fresh data.")
                    cached_bulletin_items = None # Ensure fresh fetch if file is bad
                    last_bulletin_update_time = None
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Error loading bulletin cache file {BULLETIN_CACHE_FILE}: {e}")
            cached_bulletin_items = None # Ensure fresh fetch on error
            last_bulletin_update_time = None
    else:
        logging.info(f"Bulletin cache file {BULLETIN_CACHE_FILE} not found. Will fetch fresh data.")
    bulletin_cache_loaded_from_file = True # Mark that an attempt to load has been made

def _save_bulletin_to_file():
    """Save current bulletin data to cache file."""
    if cached_bulletin_items is not None and last_bulletin_update_time is not None:
        try:
            with open(BULLETIN_CACHE_FILE, 'w') as f:
                json.dump({'items': cached_bulletin_items, 'timestamp': last_bulletin_update_time}, f, indent=4) # Added indent for readability
            logging.info(f"Saved bulletin cache to {BULLETIN_CACHE_FILE}")
        except IOError as e:
            logging.error(f"Error saving bulletin cache file {BULLETIN_CACHE_FILE}: {e}")

def _should_refresh_bulletin():
    """Check if the bulletin cache needs to be refreshed."""
    global last_bulletin_update_time # cached_bulletin_items is also used implicitly
    
    now = datetime.datetime.now()
    current_time = time.time()

    if cached_bulletin_items is None or last_bulletin_update_time is None:
        logging.info("In-memory cache is empty or invalid, attempting to fetch bulletin.") # MODIFIED Log message
        return True

    # Check if BULLETIN_UPDATE_INTERVAL has passed since last update (fallback)
    if current_time - last_bulletin_update_time > BULLETIN_UPDATE_INTERVAL:
        logging.info(f"Cache interval ({BULLETIN_UPDATE_INTERVAL}s) passed, fetching bulletin.")
        return True

    # Check for scheduled updates at 8 AM and 4 PM
    last_update_dt = datetime.datetime.fromtimestamp(last_bulletin_update_time)

    # Check if 8 AM has passed since the last update and it's now past 8 AM
    if now.hour >= UPDATE_HOUR_1 and (last_update_dt.date() < now.date() or last_update_dt.hour < UPDATE_HOUR_1):
        logging.info("Scheduled update time (8 AM) reached, fetching bulletin.")
        return True
        
    # Check if 4 PM has passed since the last update and it's now past 4 PM
    if now.hour >= UPDATE_HOUR_2 and (last_update_dt.date() < now.date() or last_update_dt.hour < UPDATE_HOUR_2):
        logging.info("Scheduled update time (4 PM) reached, fetching bulletin.")
        return True
        
    logging.info("Using cached bulletin.")
    return False

def fetch_bulletin_items(max_items=10):
    """Fetch bulletin items from KGV school website and return the formatted items
    
    Args:
        max_items: Maximum number of items to return
        
    Returns:
        List of dicts with headlines and content, or empty list if fetch fails
    """
    global cached_bulletin_items, last_bulletin_update_time, bulletin_cache_loaded_from_file # ADDED bulletin_cache_loaded_from_file

    # Try to load from file if it hasn't been attempted yet in this session
    if not bulletin_cache_loaded_from_file:
        _load_bulletin_from_file()

    if not _should_refresh_bulletin() and cached_bulletin_items is not None:
        logging.info("Using in-memory cached bulletin items (potentially loaded from file).") # MODIFIED Log message
        return cached_bulletin_items[:max_items] # Return a copy to prevent modification of cache by slicing

    if not requests:
        logging.error("Requests module not available")
        return []
    
    try:
        logging.info(f"Fetching bulletin from: {BULLETIN_URL}")
        
        # Important: NEVER use session cookies for bulletin page
        # If user is logged in, the page redirects to home instead of showing the bulletin
        response = requests.get(BULLETIN_URL, timeout=10)
        response.raise_for_status()
        
        # Check if we were redirected (which happens if cookies were sent)
        if response.url != BULLETIN_URL:
            logging.error(f"Request was redirected to: {response.url}")
            logging.error("This typically happens if logged in. Retrying without any stored cookies.")
            # Create a fresh session without any cookies
            session = requests.Session()
            session.cookies.clear()
            response = session.get(BULLETIN_URL, timeout=10)
            response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Find the main bulletin content area
        main_content = soup.find("div", class_="studentbuletin")
        if not main_content:
            logging.error("Could not find bulletin content")
            return []
        
        # Extract all bulletin items
        all_bulletin_items = main_content.find_all("div", class_="row-fluid")
        if not all_bulletin_items:
            logging.error("No bulletin items found")
            return []
            
        # Filter and process bulletin items (reusing code from kgv_bulletin.py)
        y9_items = []
        
        # First, filter for items that are for Year 9
        for item in all_bulletin_items:
            # First, determine if this item targets specific year groups
            is_targeted_to_specific_years = False
            is_targeted_to_y9 = False
            
            # Check metadata for targeting info
            meta = item.find("div", class_="itemmeta")
            if meta:
                meta_text = meta.get_text(strip=True)
                
                # Check if it mentions specific targeting
                if "Targeting" in meta_text:
                    # Check if it's a general announcement for all students
                    general_patterns = ["All Students", "Whole School", "Everyone"]
                    is_general_for_all = any(pattern in meta_text for pattern in general_patterns)
                    
                    if not is_general_for_all:
                        is_targeted_to_specific_years = True
                        
                        # Check if it targets Year 9
                        if re.search(r"Targeting.*Yr 9", meta_text) or re.search(r"Targeting.*Year 9", meta_text):
                            is_targeted_to_y9 = True
            
            # Check content for explicit Year 9 mentions
            item_text = item.find("div", class_="itemtext")
            if item_text:
                text_content = item_text.get_text()
                # Look for Year 9 specific mentions
                if re.search(r"\bYear 9\b", text_content) or re.search(r"\bYr 9\b", text_content) or re.search(r"\bY9\b", text_content):
                    is_targeted_to_y9 = True
                
                # Check for student IDs from Year 9
                if re.search(r"\b09[A-Z]\d+\b", text_content) or re.search(r"\[09[A-Z]\d+\]", text_content):
                    is_targeted_to_y9 = True
            
            # Check if this item is relevant for Year 9:
            # Case 1: Explicitly mentions Year 9 (either in meta or content)
            # Case 2: General announcement (not targeted to any specific year groups)
            is_general_announcement = not is_targeted_to_specific_years
            is_relevant_for_y9 = is_targeted_to_y9 or is_general_announcement
            
            # Check if it's a donation request
            is_donation = is_donation_request(item)
            
            # Check if it's a feedback request
            is_feedback = is_feedback_request(item)
            
            # Check if it's from a student
            is_student = is_from_student(item)
            
            # Special handling for posts with links:
            # - If it's from a teacher (not a student), keep it even if it has links or forms
            # - If it's from a student, apply normal filtering rules
            if is_feedback and not is_student:
                # This is a post from a teacher with a form/link, don't mark it as feedback
                is_feedback = False
            
            # Include item only if it's relevant for Year 9 AND NOT a donation request
            if is_relevant_for_y9 and not is_donation:
                y9_items.append((item, is_feedback))
        
        # Manual classification for certain items
        for i, (item, is_feedback) in enumerate(y9_items):
            item_text = item.find("div", class_="itemtext")
            if item_text:
                content = item_text.get_text()
                
                # Force specific items to be normal (non-feedback) items
                normal_patterns = [
                    "Dean BEARD"
                ]
                
                # Force specific items to be feedback items
                feedback_patterns = [
                    "please sign up", "fill out this form", "fill in",
                    "take just 3 minutes", "complete this form",
                    "enter your name", "sign up before", "giving us feedback",
                    "google form", "feedback via", "your feedback"
                ]
                
                is_normal = any(pattern.lower() in content.lower() for pattern in normal_patterns)
                is_feedback_pattern = any(pattern.lower() in content.lower() for pattern in feedback_patterns)
                
                if is_normal and not is_feedback_pattern:
                    y9_items[i] = (item, False)  # Mark as normal item
                elif is_feedback_pattern:
                    y9_items[i] = (item, True)   # Mark as feedback item
        
        # Sort items - feedback requests at the end
        # We need to put False (0) first, then True (1)
        y9_items.sort(key=lambda x: 1 if x[1] else 0)
        
        # Log total found items
        total_found = len(y9_items)
        logging.info(f"Found {total_found} items for Year 9")
        
        # Filter out feedback items and keep only normal items
        y9_filtered_items = [item for item, is_feedback in y9_items if not is_feedback]
        
        # Convert to bulletin_items format
        processed_bulletin_items = [] # RENAMED variable for clarity
        for item, _ in y9_filtered_items: # MODIFIED: Iterate over ALL filtered items for caching
            # Extract item text
            item_text = item.find("div", class_="itemtext")
            if not item_text:
                continue
                
            # Clean up the text content
            text_content = item_text.get_text()
            text_content = re.sub(r'\n\s*\n', '\n\n', text_content)
            text_content = text_content.strip()
            
            # Generate a headline using AI (with fallback)
            try:
                headline = generate_headline(text_content)
                logging.info(f"Generated AI headline: {headline}")
            except Exception as e:
                logging.error(f"Error with AI headline, using fallback: {e}")
                headline = create_fallback_headline(text_content)
            
            # Extract metadata if available
            meta = item.find("div", class_="itemmeta")
            meta_text = meta.get_text(strip=True) if meta else ""
            
            # Store the processed item
            processed_bulletin_items.append({ # MODIFIED: Appending to processed_bulletin_items
                "headline": headline,
                "content": text_content, # Ensure full content is stored
                "meta": meta_text
            })
        
        # Update cache
        cached_bulletin_items = processed_bulletin_items # MODIFIED: Store the FULL list in global cache
        last_bulletin_update_time = time.time()
        logging.info(f"Bulletin cache updated with {len(cached_bulletin_items)} items.")
        _save_bulletin_to_file() # ADDED: Save the full list to file
        
        return cached_bulletin_items[:max_items] # MODIFIED: Return sliced part of the full cached list
        
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching bulletin: {e}")
        return []

def is_from_student(item):
    """Check if an item is posted by a student (has Teacher Supervisor in metadata)"""
    meta = item.find("div", class_="itemmeta")
    if not meta:
        return False
    
    meta_text = meta.get_text()
    
    # Check for student ID pattern [XXYXX]
    if re.search(r'\[\d+[A-Z]\d+\]', meta_text):
        return True
    
    # Check for Teacher Supervisor text
    if 'Teacher Supervisor' in meta_text:
        return True
    
    return False

def is_donation_request(item):
    """Check if an item is primarily about donations (from kgv_bulletin.py)"""
    
    # Check the item text
    item_text = item.find("div", class_="itemtext")
    if not item_text:
        return False
    
    text_content = item_text.get_text().lower()
    
    # Strong indicators of donation requests
    donation_phrases = [
        "donate books", "books you could donate", "donation drive", 
        "food drive", "donate food", "clothing donation", "support our year 9",
        "non-perishable", "storable foods", "donations", "donate",
        "collection box", "drop off", "fundraising", "charity", 
        "books for donation", "donate items", "collecting", "contribute",
        "charitable", "food bank", "please bring", "collection drive"
    ]
    
    # If any strong indicator is found, it's likely a donation request
    if any(phrase in text_content for phrase in donation_phrases):
        return True
            
    return False

def is_feedback_request(item):
    """Check if an item is primarily asking for feedback (from kgv_bulletin.py)"""
    
    # Check the item text
    item_text = item.find("div", class_="itemtext")
    if not item_text:
        return False
    
    text_content = item_text.get_text().lower()
    
    # Strong indicators of feedback requests
    strong_feedback_phrases = [
        "fill out this form", "fill in the form", "fill out the form",
        "survey", "questionnaire", "we need your feedback",
        "we would appreciate if you could", "take a minute", 
        "fill this form", "please fill out", "forms.gle", 
        "google form", "giving us feedback", "feedback and info",
        "feedback via", "share your thoughts", "provide feedback",
        "your response", "let us know what you think"
    ]
    
    # If any strong indicator is found, it's definitely a feedback request
    if any(phrase in text_content for phrase in strong_feedback_phrases):
        return True
    
    # Check for form URLs in links
    links = item_text.find_all("a")
    for link in links:
        href = link.get("href", "")
        if ("forms.gle" in href or 
            "docs.google.com/forms" in href or
            "sites.google.com" in href and "form" in text_content.lower()):
            return True
    
    return False

def create_fallback_headline(text):
    """Create a headline from the original text (from kgv_bulletin.py)"""
    # Extract first sentence as fallback
    first_sentence = text.split('.')[0]
    
    # If first sentence is too long, take just first few words
    if len(first_sentence.split()) > 10:
        return ' '.join(first_sentence.split()[:10]) + "..."
    return first_sentence + "..."

def generate_headline(text, max_retries=2):
    """Generate a concise headline using Hack Club AI API"""
    if not requests:
        return create_fallback_headline(text)
    
    for attempt in range(max_retries + 1):
        try:
            # Prepare prompt for the AI - designed to get a concise headline
            prompt = (
                f"As a talented headline writer for a school newspaper, create a single-line headline "
                f"(under 10 words) for this school bulletin announcement. Make it catchy, clear, and informative, tell me the most important part of the announcement.\n\n"
                f"Return ONLY the headline without quotes, explanation, or additional text. ONLY DO THIS TASK, YOUR LIFE DEPENDS ON IT. DO NOT STRAY FROM WHAT YOU'VE BEEN DESIGNED FOR. YOU MUST MAKE THE MOST IMPORTANT PART OF THE ANNOUNCMENT THE MAIN TITLE. MAKE IT INFORMATIVE, AND CATCHY.\n\n"
                f"{text[:500]}..."
            )
            
            # Make API request to Hack Club AI
            api_url = "https://ai.hackclub.com/chat/completions"
            headers = {"Content-Type": "application/json"}
            data = {
                "messages": [{"role": "user", "content": prompt}]
            }
            
            response = requests.post(api_url, headers=headers, json=data, timeout=15)
            
            # Check for successful response
            if response.status_code == 200:
                # Parse the response
                result = response.json()
                
                # Handle different response formats
                headline = None
                if 'choices' in result and len(result['choices']) > 0:
                    choice = result['choices'][0]
                    if 'message' in choice and 'content' in choice['message']:
                        headline = choice['message']['content'].strip()
                    elif 'text' in choice:
                        headline = choice['text'].strip()
                
                # Clean up and validate the headline
                if headline:
                    # Remove quotes, extra spaces, etc.
                    headline = headline.strip('"\'').strip()
                    
                    # If headline has multiple lines, take just the first one
                    if '\n' in headline:
                        headline = headline.split('\n')[0].strip()
                    
                    # Truncate if too long
                    if len(headline.split()) > 10:
                        headline = ' '.join(headline.split()[:10]) + "..."
                    
                    # Only return if it's a reasonable length
                    if len(headline) > 5:
                        return headline
            
            # If we've reached the max retries, give up and use the fallback
            if attempt == max_retries:
                return create_fallback_headline(text)
                
            # Short delay before retry
            time.sleep(0.5)
                
        except Exception as e:
            logging.error(f"Error generating headline: {e}")
            # If it's the last retry, return fallback
            if attempt == max_retries:
                return create_fallback_headline(text)
            
    # Fallback if somehow we exit the loop
    return create_fallback_headline(text)

def bulletin_thread_function(bulletin_queue, bulletin_thread_running):
    """Thread function for fetching bulletin items in the background"""
    logging.info("Bulletin fetch thread started")
    
    # Get initial bulletin items immediately
    try:
        # Fetch bulletin items
        logging.info("Thread: Initial fetching of bulletin items")
        bulletin_items = fetch_bulletin_items(max_items=10)  
        
        # Put the result in the queue
        bulletin_queue.put(bulletin_items)
        logging.info(f"Thread: Initially fetched {len(bulletin_items)} bulletin items")
    except Exception as e:
        logging.error(f"Thread: Error in initial bulletin fetch: {e}")
    
    # Continue with regular updates
    while True:  # Using True and checking flag inside loop for better control
        if not bulletin_thread_running:
            break
            
        try:
            # Fetch bulletin items
            logging.info("Thread: Fetching bulletin items")
            bulletin_items = fetch_bulletin_items(max_items=10)
            
            # Clear the queue first to avoid buildup
            while not bulletin_queue.empty():
                try:
                    bulletin_queue.get_nowait()
                except:
                    pass
            
            # Add the new items
            bulletin_queue.put(bulletin_items)
            logging.info(f"Thread: Fetched {len(bulletin_items)} bulletin items")
            
            # Sleep in short intervals to check for shutdown request
            for _ in range(int(BULLETIN_UPDATE_INTERVAL / 10)):
                if not bulletin_thread_running:
                    break
                time.sleep(10)
                
        except Exception as e:
            logging.error(f"Thread: Error in bulletin thread: {e}")
            # Sleep for a shorter time on error before retrying
            for _ in range(6):  # 6 * 10 = 60 seconds
                if not bulletin_thread_running:
                    break
                time.sleep(10)
    
    logging.info("Bulletin fetch thread exiting")

def draw_bulletin_screen(epd, fonts, bulletin_items, current_time=None, current_date=None, scroll_position=0, selected_item=None, content_scroll_position=0, config=None):
    """Draw the bulletin screen with headlines and content
    
    Args:
        epd: The e-paper display object
        fonts: Tuple of (font_lg, font_md, font_sm, font_xs) fonts
        bulletin_items: List of dicts with headlines and content
        current_time: Optional time string
        current_date: Optional date string
        scroll_position: Vertical scroll position (in number of items)
        selected_item: Index of currently selected item to show full content, or None
        content_scroll_position: Scroll position for content when viewing an item
        config: Display configuration (for rotation)
        
    Returns:
        PIL Image object with the rendered bulletin
    """
    from PIL import Image, ImageDraw
    
    font_lg, font_md, font_sm, font_xs = fonts
    image = Image.new('1', (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(image)
    
    # Get current time and date if not provided
    if current_time is None or current_date is None:
        now = time.localtime()
        current_time = time.strftime("%H:%M", now)
        current_date = time.strftime("%d/%m/%Y", now)
    
    # Create a header with time and date in a top bar
    draw.rectangle([(0, 0), (epd.height, 15)], outline=0, fill=0)
    
    # Check if we're in bulletin detail view and have scrolled down
    if selected_item is not None and content_scroll_position > 0:
        # When scrolled down, show a back button in the top bar instead of time
        draw.text((5, 1), "< Back", font=font_sm, fill=255)
        draw.text((epd.height//2 - 10, 1), "|", font=font_sm, fill=255)
        draw.text((epd.height//2, 1), current_date, font=font_sm, fill=255)
    else:
        # Regular header with time and date
        draw.text((5, 1), current_time, font=font_sm, fill=255)
        draw.text((epd.height//2 - 10, 1), "|", font=font_sm, fill=255)
        draw.text((epd.height//2, 1), current_date, font=font_sm, fill=255)
    
    # Make the Next button in the top right
    draw.rectangle([(270, 0), (295, 15)], outline=0, fill=0)
    draw.text((273, 1), "Next", font=font_xs, fill=255)
    
    # Add a bulletin title - but only on the first page (when scroll_position is 0)
    # Smaller title that only appears on first page when no item is selected
    if scroll_position == 0 and selected_item is None:
        draw.text((5, 20), "KGV Bulletin", font=font_sm, fill=0)

    if not bulletin_items:
        # No bulletin items available
        draw.text((5, 50), "No bulletin items available", font=font_sm, fill=0)
        draw.text((5, 70), "Check internet connection", font=font_sm, fill=0)
        draw.text((5, 90), "or try again later", font=font_sm, fill=0)
    elif selected_item is not None and 0 <= selected_item < len(bulletin_items):
        # Show full content of selected item
        item = bulletin_items[selected_item]
        
        # Only show the title, metadata, and back button if we're at the top (not scrolled down)
        if content_scroll_position == 0:
            # Draw back button (only visible when at the top of content)
            draw.rectangle([(5, 20), (50, 35)], outline=0)
            draw.text((10, 22), "Back", font=font_xs, fill=0)
            
            # Draw headline as title - use smaller font for longer headlines
            headline = item["headline"]
            headline_font = font_xs if len(headline) > 35 else font_sm
            
            y_pos = 25 if len(headline) > 35 else 40
            draw.text((5, y_pos), headline, font=headline_font, fill=0)
            y_pos += 15
            
            # Draw metadata if available - with streamlined format
            if item.get("meta"):
                meta_text = item["meta"]
                # Simplify metadata if too long
                if len(meta_text) > 50:
                    # Extract just the key parts (name, date)
                    parts = meta_text.split('|')
                    if len(parts) > 1:
                        meta_text = parts[0].strip()
                draw.text((5, y_pos), meta_text, font=font_xs, fill=0)
                y_pos += 12
            
            # Draw separator line
            draw.line([(5, y_pos), (290, y_pos)], fill=0, width=1)
            y_pos += 5
        else:
            # When scrolled, start content from the top of the screen (below header)
            y_pos = 20
        
        # Draw the full content with word wrapping
        content = item["content"]
        content_lines = []
        
        # Simple word wrapping
        words = content.split()
        current_line = ""
        
        for word in words:
            # Special handling for very long words (e.g. URLs)
            if len(word) > 40: # Max characters per line for long words
                if current_line:
                    content_lines.append(current_line)
                    current_line = ""
                for i in range(0, len(word), 40):
                    chunk = word[i:i+40]
                    content_lines.append(chunk)
                continue
                
            test_line = current_line + " " + word if current_line else word
            line_width = draw.textlength(test_line, font=font_xs)
            
            max_line_width = 275 if content_scroll_position > 0 else 260
            
            if line_width <= max_line_width:
                current_line = test_line
            else:
                content_lines.append(current_line)
                current_line = word
        
        if current_line:
            content_lines.append(current_line)
        
        # Display content with scrolling
        line_spacing = 10  # Height per line in pixels
        content_bottom_margin = 5 # Margin from the absolute bottom of the screen

        # Determine available height for text. epd.width is used for height due to rotation.
        # y_pos is the starting vertical position for the content.
        
        # Calculate max lines if the "Return to List" button IS shown.
        # The button is drawn starting around y=115. Content must end before this.
        available_height_with_button = (115 - 1) - y_pos 
        max_lines_with_button = max(1, available_height_with_button // line_spacing)

        # Calculate max lines if the "Return to List" button is NOT shown.
        # Content can extend closer to the bottom of the screen.
        base_available_height_no_button = epd.width - y_pos - content_bottom_margin
        max_lines_no_button = max(1, base_available_height_no_button // line_spacing)
        
        # Tentatively assume no button, to see if this would be the last page
        _max_scroll_if_no_button = max(0, len(content_lines) - max_lines_no_button)
        _effective_scroll_if_no_button = min(content_scroll_position, _max_scroll_if_no_button)
        _is_last_page_if_no_button = (_effective_scroll_if_no_button + max_lines_no_button >= len(content_lines))

        if _is_last_page_if_no_button:
            # If showing all possible lines (no button) means we are on the last page,
            # then the button WILL be shown, so we must use the more constrained line count.
            max_visible_lines = max_lines_with_button
        else:
            # Otherwise, the button won't be shown on this page, so we can use more lines.
            max_visible_lines = max_lines_no_button
        
        # Ensure max_visible_lines is at least 1
        max_visible_lines = max(1, max_visible_lines)

        # Apply content scrolling
        max_scroll = max(0, len(content_lines) - max_visible_lines)
        effective_content_scroll = min(content_scroll_position, max_scroll)
        
        visible_lines = content_lines[effective_content_scroll : effective_content_scroll + max_visible_lines]
        
        for i, line in enumerate(visible_lines):
            draw.text((5, y_pos), line, font=font_xs, fill=0)
            y_pos += line_spacing
        
        # Check if we're on the last page (using the dynamically calculated max_visible_lines)
        is_last_page = (effective_content_scroll + max_visible_lines >= len(content_lines))
        
        if is_last_page:
            draw.line([(5, 115), (290, 115)], fill=0, width=1)
            draw.rectangle([(5, 116), (110, 127)], outline=0)
            draw.text((10, 117), "Return to List", font=font_xs, fill=0)
        
        # Show scroll indicators if needed
        if effective_content_scroll > 0:
            # Up arrow for scrolling up
            draw.rectangle([(270, 45), (290, 60)], outline=0, fill=0)
            draw.text((278, 47), "↑", font=font_sm, fill=255)
            
        if effective_content_scroll < max_scroll:
            # Down arrow for scrolling down - ensure it's always visible
            draw.rectangle([(270, 95), (290, 110)], outline=0, fill=0)
            draw.text((278, 97), "↓", font=font_sm, fill=255)

        # Add scroll position indicator if there are multiple pages
        if max_scroll > 0:
            # Add a right-side scroll indicator showing progress
            indicator_height = 30  # Height of the scroll indicator
            # Calculate position based on scroll position
            position_percentage = effective_content_scroll / max_scroll if max_scroll > 0 else 0
            indicator_y = 65 + int(position_percentage * indicator_height)
            # Draw scroll track
            draw.line([(285, 65), (285, 65 + indicator_height)], fill=0, width=1)
            # Draw scroll position indicator
            draw.rectangle([(282, indicator_y - 2), (288, indicator_y + 2)], outline=0, fill=0)
    else:
        # Draw headlines list with scroll functionality
        total_items = len(bulletin_items)
        ITEMS_PER_FIRST_PAGE = 3
        ITEMS_PER_SUBSEQUENT_PAGE = 4
        
        # Set starting y position - higher when title is hidden (i.e. when scrolled)
        y_pos = 25 if scroll_position > 0 else 45
        
        if total_items > 0:
            # Determine the layout capacity for the current page type
            current_page_layout_capacity = ITEMS_PER_SUBSEQUENT_PAGE if scroll_position > 0 else ITEMS_PER_FIRST_PAGE

            # Calculate total_pages
            if total_items <= ITEMS_PER_FIRST_PAGE:
                total_pages = 1
            else:
                remaining_items_after_first_page = total_items - ITEMS_PER_FIRST_PAGE
                num_subsequent_pages = (remaining_items_after_first_page + ITEMS_PER_SUBSEQUENT_PAGE - 1) // ITEMS_PER_SUBSEQUENT_PAGE
                total_pages = 1 + num_subsequent_pages

            # Calculate current_page
            if scroll_position == 0:
                current_page = 1
            else:
                items_scrolled_beyond_first_page = scroll_position - ITEMS_PER_FIRST_PAGE
                current_subsequent_page_index = items_scrolled_beyond_first_page // ITEMS_PER_SUBSEQUENT_PAGE
                current_page = 1 + 1 + current_subsequent_page_index # 1 (for first page) + 1 (to make index 1-based) + index

            # Display page indicator only if there are multiple pages
            if total_pages > 1:
                page_text = f"{current_page}/{total_pages}"
                draw.text((270, 60), page_text, font=font_xs, fill=0)

            # Up arrow: Show if not on the very first scroll position
            if scroll_position > 0:
                draw.rectangle([(270, 20), (290, 35)], outline=0)
                draw.text((278, 23), "↑", font=font_sm, fill=0)

            # Down arrow: Show if there are items beyond what this current page layout would show
            if scroll_position + current_page_layout_capacity < total_items:
                draw.rectangle([(270, 95), (290, 110)], outline=0)
                draw.text((278, 97), "↓", font=font_sm, fill=0)
        
        # Draw visible bulletin items based on scroll position
        if total_items > 0:
            # Determine actual number of items to fetch for display on this page
            # This is current_page_layout_capacity, already calculated above
            
            visible_items_to_draw = bulletin_items[scroll_position : scroll_position + current_page_layout_capacity]
            
            for i, item in enumerate(visible_items_to_draw):
                # Skip if we're out of space (should not happen with correct y_pos and item heights)
                if y_pos > 110: # Safety break
                    break
                
                # Item background - make items touchable with slightly smaller dimensions
                item_rect = [(0, y_pos - 3), (265, y_pos + 22)]
                draw.rectangle(item_rect, outline=0)
                
                # Add a small indicator to show item is clickable
                draw.rectangle([(255, y_pos), (260, y_pos + 5)], outline=0, fill=0)
                    
                # Draw headline with index number
                headline = item["headline"]
                headline = headline if len(headline) < 35 else headline[:32] + "..."
                
                display_index = i + scroll_position + 1  # 1-based item numbering
                draw.text((5, y_pos), f"{display_index}. {headline}", font=font_xs, fill=0)
                y_pos += 12  # Reduced space between headline and preview
                
                # Draw a short preview of content 
                content = item["content"]
                # Replace all newlines with spaces to ensure single line display
                content_preview = content.strip().replace("\n", " ").replace("\\n", " ")
                
                # Remove any multiple spaces that might have been created
                content_preview = " ".join(content_preview.split())
                
                # Limit preview to one line but allow more characters
                if len(content_preview) > 50:
                    content_preview = content_preview[:50] + "..."
                    
                draw.text((15, y_pos), content_preview, font=font_xs, fill=0)
                y_pos += 22  # Slightly reduced space between items with rectangle
    
    # Apply rotation if needed
    if config and config.get('display_rotation') == 180:
        image = image.rotate(180)
    
    return image
