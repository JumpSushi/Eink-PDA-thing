#!/usr/bin/python
# -*- coding:utf-8 -*-
import os
from dotenv import load_dotenv
from datetime import datetime
import sys
import time
import json
import logging
import threading
import socket
from bs4 import BeautifulSoup
import re

libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

# Import the ICS parser
try:
    from ics_parser import ICSParser
except ImportError:
    # Create a placeholder that will be replaced when we create the actual file
    ICSParser = None

# Import bulletin utilities
try:
    from bulletin_utils import (
        fetch_bulletin_items, 
        bulletin_thread_function,
        draw_bulletin_screen as render_bulletin_screen
    )
except ImportError:
    # Create placeholders if the import fails
    fetch_bulletin_items = None
    bulletin_thread_function = None
    render_bulletin_screen = None

# Try to import the session management
try:
    from lionel_session import get_session_token, get_session_cookies
    lionel_session_available = True
except ImportError:
    get_session_token = None
    get_session_cookies = None
    lionel_session_available = False
    logging.warning("Lionel session management not available")

# Setup font directories
fontdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
fonts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'fonts')
if not os.path.exists(fonts_dir):
    os.makedirs(fonts_dir, exist_ok=True)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
FONT_PATH = os.path.join(fontdir, 'Font.ttc')  # Keep original font path for backup
REDHAT_REGULAR_PATH = os.path.join(fonts_dir, 'RedHatDisplay-Regular.ttf')
REDHAT_MEDIUM_PATH = os.path.join(fonts_dir, 'RedHatDisplay-Medium.ttf')
REDHAT_BOLD_PATH = os.path.join(fonts_dir, 'RedHatDisplay-Bold.ttf')

from PIL import Image, ImageDraw, ImageFont
import urllib.request
import zipfile
import tempfile
import shutil
from TP_lib import epd2in9_V2
from TP_lib import icnt86

# Function to download Red Hat Display fonts if they don't exist
def download_redhat_fonts():
    # Font URL provided by the user (downloads as a zip)
    font_zip_url = "https://github.com/RedHatOfficial/RedHatFont/archive/refs/tags/4.1.0.zip"
    
    # Check if any of the fonts are missing
    fonts_missing = (
        not os.path.exists(REDHAT_REGULAR_PATH) or
        not os.path.exists(REDHAT_MEDIUM_PATH) or
        not os.path.exists(REDHAT_BOLD_PATH)
    )
    
    if fonts_missing:
        try:
            logging.info("Downloading Red Hat Display font zip file")
            
            # Create a temporary directory to extract the zip
            with tempfile.TemporaryDirectory() as temp_dir:
                # Download the zip file to the temporary directory
                zip_path = os.path.join(temp_dir, "redhat.zip")
                urllib.request.urlretrieve(font_zip_url, zip_path)
                logging.info("Font zip downloaded successfully")
                
                # Extract the zip file
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                logging.info("Font zip extracted successfully")
                
                # Map the font files we need to their expected locations
                font_files = {
                    "RedHatDisplay-Regular.ttf": REDHAT_REGULAR_PATH,
                    "RedHatDisplay-Medium.ttf": REDHAT_MEDIUM_PATH,
                    "RedHatDisplay-Bold.ttf": REDHAT_BOLD_PATH
                }
                
                # Find and copy the font files to their destinations
                found_fonts = False
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        if file in font_files:
                            src_path = os.path.join(root, file)
                            dest_path = font_files[file]
                            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                            shutil.copy2(src_path, dest_path)
                            logging.info(f"Copied {file} to {dest_path}")
                            found_fonts = True
                
                if not found_fonts:
                    logging.error("Could not find the expected font files in the zip")
                    return False
                
                return True
                
        except Exception as e:
            logging.error(f"Error downloading or extracting fonts: {e}")
            return False
    
    # All fonts are already present
    return True

# Configuration paths

# Constants
REFRESH_INTERVAL = 0.1  # Seconds between updates (reduced from 0 to lower CPU usage)
PARTIAL_REFRESHES_BEFORE_FULL = 5
WEATHER_UPDATE_INTERVAL = 600  # 10 minutes
STATS_UPDATE_INTERVAL = 5  # Update CPU/memory every 5 seconds
TIMETABLE_UPDATE_INTERVAL = 3600  # Update timetable hourly (3600 seconds)
BULLETIN_UPDATE_INTERVAL = 1800  # Update bulletin every 30 minutes (1800 seconds)
TIMETABLE_URL = os.getenv("TIMETABLE_URL")
BULLETIN_URL = "https://lionel2.kgv.edu.hk/local/mis/bulletin/bulletin.php"

# Screen states
BULLETIN_SCREEN = 3  # New state for bulletin screen
NETWORK_INFO_SCREEN = 2
MAIN_SCREEN = 1
TIMETABLE_SCREEN = 0

# Configure logging
logging.basicConfig(level=logging.INFO)

try:
    import requests
except ImportError:
    requests = None
    logging.warning("requests library not found, weather functionality will be disabled.")

try:
    import psutil
except ImportError:
    psutil = None
    logging.warning("psutil library not found, some system stats may not be available.")

# Add threading and queue for bulletin fetching
try:
    import queue # Python 3
except ImportError:
    import Queue as queue # Python 2 compatibility
    logging.info("Using Queue (Python 2) for bulletin items.")


# Load configuration
def load_config():
    load_dotenv()
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
            if 'openweathermap_api_key' in config:
                config['weather_enabled'] = True
            else:
                config['weather_enabled'] = False
                
            # Check for Lionel credentials
            lionel_username = os.getenv("LIONEL_USERNAME")
            lionel_password = os.getenv("LIONEL_PASSWORD")
            
            if lionel_username and lionel_password:
                config['lionel_credentials_available'] = True
                # Initialize the session token if the module is available
                if get_session_token:
                    session = get_session_token()
                    if session:
                        logging.info("Lionel session token obtained successfully")
                    else:
                        logging.error("Failed to get Lionel session token")
            else:
                config['lionel_credentials_available'] = False
                logging.warning("Lionel credentials not available in environment")
                
            return config
    except (FileNotFoundError, json.JSONDecodeError):
        return {'weather_enabled': False, 'lionel_credentials_available': False}

config = load_config()

# Touch variables
current_screen = NETWORK_INFO_SCREEN
touch_event = threading.Event()

# Bulletin screen variables
bulletin_scroll_position = 0
bulletin_selected_item = None
bulletin_content_scroll_position = 0
bulletin_items = []  # Initialize globally

# Initialize display
epd = epd2in9_V2.EPD_2IN9_V2()

# Initialize touch controller
touch = icnt86.INCT86()
touch_dev = icnt86.ICNT_Development()
touch_old = icnt86.ICNT_Development()

# Touch thread flag
touch_thread_running = True

def get_weather():
    if not requests:
        return None
    
    # Hardcoded values as requested
    api_key = os.getenv("OPENWEATHERMAP_API_KEY")
    city = 'Hong Kong'
    country_code = 'HK'
    unit = config.get('temperature_unit', 'C')
    
    try:
        units = 'metric' if unit == 'C' else 'imperial'
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city},{country_code}&appid={api_key}&units={units}"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data['cod'] != 200:
            return None
        return {
            'temp': data['main']['temp'],
            'description': data['weather'][0]['description']
        }
    except Exception as e:
        logging.error(f"Weather error: {e}")
        return None

def get_system_stats():
    stats = {}
    
    # CPU Temperature
    try:
        res = os.popen('vcgencmd measure_temp').readline()
        stats['cpu_temp'] = float(res.replace("temp=", "").replace("'C\n", ""))
    except:
        stats['cpu_temp'] = None
    
    # Memory Usage - first try psutil
    stats['mem_usage'] = None
    if psutil:
        try:
            mem = psutil.virtual_memory()
            stats['mem_usage'] = mem.percent
        except:
            pass
    
    # If psutil fails, try free command
    if stats['mem_usage'] is None:
        try:
            cmd = "free | grep Mem | awk '{print int($3/$2 * 100)}'"
            res = os.popen(cmd).readline()
            stats['mem_usage'] = int(res.strip())
        except:
            stats['mem_usage'] = None
    
    return stats

def draw_time_image(fonts, weather_data, stats):
    font_lg, font_md, font_sm, font_xs = fonts  # Updated to unpack 4 fonts
    image = Image.new('1', (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(image)
    
    # Get current time and date using a single time call for consistency
    now = time.localtime()
    current_time = time.strftime("%H:%M", now)
    current_date = time.strftime("%Y-%m-%d", now)
    
    # Draw time
    draw.text((20, 10), current_time, font=font_lg, fill=0)
    # Draw date
    draw.text((20, 45), current_date, font=font_md, fill=0)
    
    # Draw weather
    y_pos = 80
    if weather_data:
        weather_text = f"{weather_data['temp']:.1f}°{config.get('temperature_unit', 'C')} {weather_data['description']}"
        draw.text((20, y_pos), weather_text[:32], font=font_md, fill=0)
        y_pos += 25
    
    # System stats - CPU and Memory on same line with fixed positioning
    if stats['cpu_temp'] is not None:
        # Draw CPU temperature at fixed position
        draw.text((20, y_pos), f"CPU: {stats['cpu_temp']}°C", font=font_sm, fill=0)
        
        # Draw Memory usage right after CPU with fixed offset
        if stats['mem_usage'] is not None:
            draw.text((100, y_pos), f"Mem: {stats['mem_usage']}%", font=font_sm, fill=0)
    
    # Draw button
    draw.rectangle([(250, 0), (295, 127)], outline=0)
    draw.text((255, 60), "Info", font=font_sm, fill=0)
    
    # Apply rotation if needed
    if config.get('display_rotation') == 180:
        image = image.rotate(180)
    
    return image

def get_network_info():
    """Get network information including WiFi, IP address and hostname"""
    info = {
        'wifi': "Unknown",
        'ip': "Unknown",
        'hostname': "pda.local"
    }
    
    # Try to get hostname
    try:
        hostname = socket.gethostname()
        info['hostname'] = f"{hostname}.local"
    except:
        pass
    
    # Get IP address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        info['ip'] = s.getsockname()[0]
        s.close()
    except:
        pass
    
    # Get WiFi network name
    try:
        cmd = "iwgetid -r"
        wifi_name = os.popen(cmd).read().strip()
        if wifi_name:
            info['wifi'] = wifi_name
    except:
        pass
    
    return info

def initialize_fonts():
    """Initialize fonts without refreshing the display"""
    logging.info("Initializing fonts")
    
    # First, try to download Red Hat Display fonts if they don't exist
    fonts_available = download_redhat_fonts()
    
    if fonts_available:
        try:
            # Use Red Hat Display fonts
            return (
                ImageFont.truetype(REDHAT_BOLD_PATH, 24),
                ImageFont.truetype(REDHAT_MEDIUM_PATH, 18), 
                ImageFont.truetype(REDHAT_REGULAR_PATH, 12),
                ImageFont.truetype(REDHAT_REGULAR_PATH, 10)  # Extra small font for timetable
            )
        except Exception as e:
            logging.error(f"Error loading Red Hat fonts: {e}")
    
    # Fallback to default font if Red Hat fonts not available
    logging.info("Using default font")
    return (
        ImageFont.truetype(FONT_PATH, 24),
        ImageFont.truetype(FONT_PATH, 18),
        ImageFont.truetype(FONT_PATH, 12),
        ImageFont.truetype(FONT_PATH, 10)  # Extra small font for timetable
    )

def touch_detection_thread():
    """Thread function for touch detection using INT pin method"""
    global current_screen, touch_event, touch_thread_running, touch_dev
    global bulletin_scroll_position, bulletin_selected_item, bulletin_content_scroll_position
    global bulletin_items, force_full_refresh
    
    logging.info("Touch detection thread started")
    
    # Initialize touch controller
    touch.ICNT_Init()
    
    # Variables for touch debounce
    last_touch_time = 0
    debounce_time = 0.3  # Reduced to 0.3 seconds for faster response
    
    # Common button area (right side of screen)
    button_x_min = 250  # Right side of screen
    button_x_max = 295
    button_y_min = 0
    button_y_max = 127
    
    # Special case for timetable screen which has a smaller button at the top
    timetable_button_x_min = 270
    timetable_button_x_max = 295
    timetable_button_y_min = 0
    timetable_button_y_max = 15
    
    # Main touch detection loop
    while touch_thread_running:
        try:
            # Check if the INT pin is low (touch detected)
            if touch.digital_read(touch.INT) == 0:
                touch_dev.Touch = 1
                
                # Get touch data
                touch.ICNT_Scan(touch_dev, touch_old)
                
                current_time = time.time()
                if touch_dev.TouchCount > 0 and current_time - last_touch_time > debounce_time:
                    x_pos = touch_dev.X[0]
                    y_pos = touch_dev.Y[0]
                    
                    logging.info(f"Touch detected at: {x_pos}, {y_pos}")
                    
                    # Handle bulletin screen interactions
                    if current_screen == BULLETIN_SCREEN:
                        # Check if we're in item detail view
                        if bulletin_selected_item is not None:
                            # Back button in top bar when scrolled down
                            if bulletin_content_scroll_position > 0 and 5 <= x_pos <= 50 and 0 <= y_pos <= 15:
                                # Return to list view
                                bulletin_selected_item = None
                                bulletin_content_scroll_position = 0  # Reset content scroll position
                                
                                # Force a full refresh when exiting an article view
                                force_full_refresh = True
                                
                                touch_event.set()
                                last_touch_time = current_time
                            
                            # Back button (top left of screen) when not scrolled
                            elif bulletin_content_scroll_position == 0 and 5 <= x_pos <= 50 and 20 <= y_pos <= 35:
                                # Return to list view
                                bulletin_selected_item = None
                                bulletin_content_scroll_position = 0  # Reset content scroll position
                                
                                # Force a full refresh when exiting an article view
                                force_full_refresh = True
                                
                                touch_event.set()
                                last_touch_time = current_time
                            
                            # "Return to List" button at the bottom of the last page (expanded clickable area)
                            elif 5 <= x_pos <= 110 and 116 <= y_pos <= 127:
                                # Return to list view
                                bulletin_selected_item = None
                                bulletin_content_scroll_position = 0  # Reset content scroll position
                                
                                # Force a full refresh when exiting an article view
                                force_full_refresh = True
                                
                                touch_event.set()
                                last_touch_time = current_time
                            
                            # Content scroll up button
                            elif bulletin_content_scroll_position > 0 and 270 <= x_pos <= 290 and 45 <= y_pos <= 60:
                                bulletin_content_scroll_position -= 1
                                touch_event.set()
                                last_touch_time = current_time
                            
                            # Content scroll down button
                            elif 270 <= x_pos <= 290 and 95 <= y_pos <= 110:
                                # Simply increment scroll position by 1
                                # The actual limit check will happen in the draw function
                                bulletin_content_scroll_position += 2  # Scroll 1 line at once
                                touch_event.set()
                                last_touch_time = current_time
                        else:
                            # Scrolling up button (top right)
                            if bulletin_scroll_position > 0 and 270 <= x_pos <= 290 and 20 <= y_pos <= 35:
                                bulletin_scroll_position -= 1
                                touch_event.set()
                                last_touch_time = current_time
                            
                            # Scrolling down button (bottom right)
                            elif 270 <= x_pos <= 290 and 95 <= y_pos <= 110:
                                bulletin_scroll_position += 1
                                touch_event.set()
                                last_touch_time = current_time
                            
                            # Item selection maintained but without dragging to scroll
                            elif 0 <= x_pos <= 265:
                                # Make sure bulletin_items exists
                                if bulletin_items:
                                    # Determine y position start based on scroll position
                                    start_y = 25 if bulletin_scroll_position > 0 else 45
                                    
                                    # Calculate item positions based on our updated spacing
                                    item_positions = []
                                    for i in range(4 if bulletin_scroll_position > 0 else 3):
                                        item_top = start_y + (i * 33) - 3
                                        item_bottom = item_top + 25
                                        item_positions.append((item_top, item_bottom))
                                    
                                    # Determine which item was touched
                                    for i, (top, bottom) in enumerate(item_positions):
                                        if top <= y_pos <= bottom:
                                            select_index = bulletin_scroll_position + i
                                            if 0 <= select_index < len(bulletin_items):
                                                # Set the article selection
                                                bulletin_selected_item = select_index
                                                bulletin_content_scroll_position = 0  # Reset content scroll when selecting new item
                                                
                                                # Force a full refresh when entering an article view
                                                force_full_refresh = True
                                                
                                                touch_event.set()
                                                last_touch_time = current_time
                                                break
                    
                    # Handle the main navigation button press
                    if ((current_screen != TIMETABLE_SCREEN and current_screen != BULLETIN_SCREEN and 
                        button_x_min <= x_pos <= button_x_max and button_y_min <= y_pos <= button_y_max) or
                        (current_screen == TIMETABLE_SCREEN and 
                        timetable_button_x_min <= x_pos <= timetable_button_x_max and 
                        timetable_button_y_min <= y_pos <= timetable_button_y_max) or
                        (current_screen == BULLETIN_SCREEN and
                        270 <= x_pos <= 295 and 0 <= y_pos <= 15)):
                        
                        # Reset bulletin view state when leaving bulletin screen
                        if current_screen == BULLETIN_SCREEN:
                            bulletin_scroll_position = 0
                            bulletin_selected_item = None
                            bulletin_content_scroll_position = 0
                        
                        # Cycle through screens
                        old_screen = current_screen
                        if current_screen == NETWORK_INFO_SCREEN:
                            current_screen = MAIN_SCREEN
                        elif current_screen == MAIN_SCREEN:
                            current_screen = TIMETABLE_SCREEN
                        elif current_screen == TIMETABLE_SCREEN:
                            current_screen = BULLETIN_SCREEN
                        else:  # BULLETIN_SCREEN
                            current_screen = NETWORK_INFO_SCREEN
                        
                        # Flag to force full refresh when entering or leaving bulletin screen
                        force_full_refresh = (old_screen == BULLETIN_SCREEN or current_screen == BULLETIN_SCREEN)
                        
                        # Signal main thread to update display
                        touch_event.set()
                        last_touch_time = current_time
                
                # Reset touch flag
                touch_dev.Touch = 0
                time.sleep(0.05)  # Small delay for debounce
            else:
                touch_dev.Touch = 0
                time.sleep(0.01)  # Short sleep when no touch
                
        except Exception as e:
            logging.error(f"Touch error: {e}")
            time.sleep(0.5)
    
    logging.info("Touch detection thread exiting")

def draw_network_info_screen(fonts, network_info):
    """Draw the network information screen"""
    font_lg, font_md, font_sm, font_xs = fonts  # Updated to unpack 4 fonts
    image = Image.new('1', (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(image)
    
    # Title
    draw.text((10, 10), "Network Information", font=font_md, fill=0)
    
    # WiFi Network
    draw.text((10, 40), f"WiFi: {network_info['wifi']}", font=font_sm, fill=0)
    
    # IP Address
    draw.text((10, 60), f"IP: {network_info['ip']}", font=font_sm, fill=0)
    
    # Hostname
    draw.text((10, 80), f"Host: {network_info['hostname']}", font=font_sm, fill=0)
    
    # Lionel Session Status (if available)
    if 'lionel_session' in network_info:
        status_text = "Available" if network_info['lionel_session'] else "Not Available"
        note_text = "(Not used for bulletin)"
        draw.text((10, 100), f"Lionel ID: {status_text}", font=font_sm, fill=0)
        draw.text((35, 115), note_text, font=font_xs, fill=0)
    
    # Draw button
    draw.rectangle([(250, 0), (295, 127)], outline=0)
    draw.text((255, 60), "Next", font=font_sm, fill=0)
    
    # Apply rotation if needed
    if config.get('display_rotation') == 180:
        image = image.rotate(180)
    
    return image

def draw_timetable_screen(fonts, timetable_data, current_time=None, current_date=None):
    """Draw the timetable screen with week/schedule info on left and timetable on right"""
    font_lg, font_md, font_sm, font_xs = fonts  # Add extra small font
    image = Image.new('1', (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(image)
    
    # Get current time and date if not provided
    if current_time is None or current_date is None:
        now = time.localtime()
        current_time = time.strftime("%H:%M", now)
        current_date = time.strftime("%d/%m/%Y", now)
    
    # Create a header with time and date in a top bar
    draw.rectangle([(0, 0), (epd.height, 15)], outline=0, fill=0)
    draw.text((5, 1), current_time, font=font_sm, fill=255)  # Back to original smaller font
    draw.text((epd.height//2 - 10, 1), "|", font=font_sm, fill=255)
    draw.text((epd.height//2, 1), current_date, font=font_sm, fill=255)
    
    # Make the Next button smaller and more stylish in the top right
    draw.rectangle([(270, 0), (295, 15)], outline=0, fill=0)
    draw.text((273, 1), "Next", font=font_xs, fill=255)
    
    # Define left and right section areas
    left_section_width = 100  # Width for the left section
    right_section_start = left_section_width + 5  # Start of the right section
    
    # Draw a vertical divider between sections
    draw.line([(left_section_width, 20), (left_section_width, 127)], fill=0, width=1)
    
    # LEFT SECTION: Week info and next lesson
    left_y = 22  # Starting Y position for left section
    
    # Week and Day information - use smaller font
    week_day_text = f"Week {timetable_data['week']}"
    draw.text((5, left_y), week_day_text, font=font_sm, fill=0)
    left_y += 15
    
    # Day of week - use smaller font
    day_text = f"{timetable_data['day']}"
    draw.text((5, left_y), day_text, font=font_sm, fill=0)
    left_y += 15
    
    # Add "Tomorrow" on a new line if showing next day's schedule
    if timetable_data.get("is_next_day", False):
        draw.text((5, left_y), "(Tomorrow)", font=font_sm, fill=0)
        left_y += 15
    
    # Display next lesson information
    draw.text((5, left_y), "Next:", font=font_sm, fill=0)
    left_y += 15
    
    # If it's a weekend, show next school day
    if timetable_data.get("is_weekend", False):
        next_day_text = f"Week {timetable_data.get('next_week', '?')}"
        next_day_text += f", {timetable_data.get('next_day', 'Monday')}"
        
        draw.text((5, left_y), next_day_text, font=font_sm, fill=0)
        left_y += 15
        
        if "next_schedule" in timetable_data and timetable_data["next_schedule"]:
            # Show first class of next day
            first_class = None
            for period in range(1, 6):
                period_str = str(period)
                if period_str in timetable_data["next_schedule"]:
                    period_classes = timetable_data["next_schedule"][period_str]
                    if period_classes:
                        first_class = period_classes[0].get('class', 'Free Period')
                        first_time = period_classes[0].get('time', '??:??')
                        break
            
            if first_class:
                draw.text((5, left_y), f"{first_time}", font=font_sm, fill=0)
                left_y += 15
                draw.text((5, left_y), first_class, font=font_xs, fill=0)
    else:
        # Determine next lesson for today
        current_period = 0
        next_period = None
        next_class = None
        next_time = None
        
        # Get current schedule
        schedule = timetable_data.get("schedule", {})
        
        # Find next class based on current time
        current_hour = int(time.strftime("%H"))
        current_minute = int(time.strftime("%M"))
        current_time_mins = current_hour * 60 + current_minute
        
        for period in range(1, 6):
            period_str = str(period)
            period_classes = schedule.get(period_str, [])
            
            if period_classes:
                class_time = period_classes[0].get('time', '00:00')
                try:
                    hour, minute = map(int, class_time.split(':'))
                    class_time_mins = hour * 60 + minute
                    
                    # If class time is in the future, it's the next class
                    if class_time_mins > current_time_mins:
                        if next_period is None:
                            next_period = period
                            next_class = period_classes[0].get('class', 'Free Period')
                            next_time = class_time
                            break
                except ValueError:
                    pass
        
        if next_period:
            # Show next class information with smaller font and vertically aligned
            next_text = f"P{next_period} at {next_time}"
            draw.text((5, left_y), next_text, font=font_sm, fill=0)
            left_y += 15
            
            # Draw class name with vertical alignment
            if len(next_class) > 15:  # Truncate if too long for the left side
                next_class = next_class[:12] + "..."
            draw.text((5, left_y), next_class, font=font_xs, fill=0)
        else:
            # No more classes today
            no_more_text = "No more"
            draw.text((5, left_y), no_more_text, font=font_sm, fill=0)
            left_y += 15
            
            # Vertical alignment not as important here, but keep consistent spacing
            draw.text((5, left_y), "classes today", font=font_xs, fill=0)
    
    # RIGHT SECTION: Timetable 
    right_y = 22  # Starting Y position for right section
    
    # Get appropriate schedule
    if timetable_data.get("is_weekend", False):
        schedule = timetable_data.get("next_schedule", {})
        logging.info(f"Drawing timetable for weekend - showing next Monday Week {timetable_data.get('next_week')}")
    elif timetable_data.get("is_next_day", False):
        # If we're showing the next day's schedule (after cutoff time on weekday)
        schedule = timetable_data.get("schedule", {})
        logging.info(f"Drawing timetable for next day - {timetable_data.get('day')} Week {timetable_data.get('week')}")
    else:
        schedule = timetable_data.get("schedule", {})
        logging.info(f"Drawing timetable for current day - {timetable_data.get('day')} Week {timetable_data.get('week')}")
    
    # Draw timetable periods - keep period numbers large, but class names smaller
    for period in range(1, 6):
        period_str = str(period)
        period_classes = schedule.get(period_str, [])
        
        # Define row height and calculate vertical centering
        row_height = 20  # Fixed row height
        
        # Calculate the period text metrics once
        period_text = f"P{period}:"
        period_bbox = font_md.getbbox(period_text)
        period_height = period_bbox[3] - period_bbox[1]
        
        # Calculate vertical position to center the period text in the row
        period_y = right_y + (row_height - period_height) // 2 - 5  # Shifted up by 20px
        
        # Background for each row (alternating) - precisely aligned with row
        if period % 2 == 0:
            draw.rectangle([(right_section_start, right_y), 
                           (epd.height-5, right_y + row_height - 1)], outline=0, fill=255)
        
        # Draw period number with larger font at the centered position
        draw.text((right_section_start + 5, period_y), period_text, font=font_md, fill=0)
        
        if period_classes:
            class_name = period_classes[0].get('class', 'Free Period')
            class_time = period_classes[0].get('time', '??:??')
            
            # Draw class name and time with smaller font
            class_display = f"{class_name} ({class_time})"
            if len(class_display) > 22:  # Truncate if too long
                class_display = class_display[:20] + "..."
            
            # Calculate vertical center alignment for class text aligned with period text
            class_bbox = font_sm.getbbox(class_display)
            class_height = class_bbox[3] - class_bbox[1]
            class_y = right_y + (row_height - class_height) // 2
            
            # Place class text horizontally offset but at same vertical alignment as period
            draw.text((right_section_start + 40, class_y), class_display, font=font_sm, fill=0)
        else:
            # Free period text
            free_text = "Free"
            free_bbox = font_sm.getbbox(free_text)
            free_height = free_bbox[3] - free_bbox[1]
            free_y = right_y + (row_height - free_height) // 2
            
            # Place "Free" text at same vertical alignment as period
            draw.text((right_section_start + 40, free_y), free_text, font=font_sm, fill=0)
        
        # Move to the next row
        right_y += row_height
    
    # Apply rotation if needed
    if config.get('display_rotation') == 180:
        image = image.rotate(180)
    
    return image

# The following functions have been moved to bulletin_utils.py:
# - fetch_bulletin_items
# - is_from_student
# - is_donation_request
# - is_feedback_request
# - create_fallback_headline
# - generate_headline
# - bulletin_thread_function (modified to accept parameters)
# - draw_bulletin_screen (reimplemented as wrapper to call the imported version)

# Moved to bulletin_utils.py

# Bulletin thread variables
bulletin_thread_running = True
bulletin_queue = None  # Will be initialized in main

def main():
    global epd, current_screen, touch_event, touch_thread_running, touch_dev, touch_old
    global bulletin_items, bulletin_scroll_position, bulletin_selected_item, bulletin_content_scroll_position
    global bulletin_queue, bulletin_thread_running, force_full_refresh # Added force_full_refresh

    # Initialize display and touch
    epd.init()
    epd.Clear()
    logging.info("Display initialized")

    # Initialize fonts
    fonts = initialize_fonts()
    logging.info("Fonts initialized")

    # Initialize bulletin queue
    bulletin_queue = queue.Queue()  # Thread-safe queue for bulletin items

    # Start touch detection thread
    touch_thread = threading.Thread(target=touch_detection_thread)
    touch_thread.daemon = True
    touch_thread.start()
    logging.info("Touch detection thread started")

    # Start bulletin fetching thread
    # bulletin_thread = start_bulletin_thread() # Removed call to empty function

    # Initial network info fetch
    network_info = get_network_info()
    
    # Prepare initial screen once - network info screen by default
    image = draw_network_info_screen(fonts, network_info)
    # Use display_Base only once for the first display
    epd.display_Base(epd.getbuffer(image))
    
    try:
        while True:
            current_time = time.time()
            
            # Update system stats periodically rather than every cycle
            stats_updated = False
            if current_time - last_stats_update > STATS_UPDATE_INTERVAL:
                try:
                    stats = get_system_stats()
                    last_stats_update = current_time
                    stats_updated = True
                    
                    # Check if only stats changed (not time or other content)
                    stats_only_changed = (
                        current_screen == MAIN_SCREEN and
                        (stats['cpu_temp'] != last_stats['cpu_temp'] or 
                         stats['mem_usage'] != last_stats['mem_usage'])
                    )
                    # Update last stats values
                    last_stats = stats.copy()
                except Exception as e:
                    logging.error(f"Error updating system stats: {e}")                    
            # Update weather periodically
            if current_time - last_weather_update > WEATHER_UPDATE_INTERVAL:
                logging.info("Updating weather data")
                weather_data = get_weather()
                last_weather_update = current_time
                
            # Update timetable periodically or when forced
            if (timetable_parser is not None and 
                (current_time - last_timetable_update > TIMETABLE_UPDATE_INTERVAL or force_timetable_refresh)):
                logging.info(f"Updating timetable data (forced: {force_timetable_refresh})")
                try:
                    # Force download and parse if refresh button was pressed
                    if force_timetable_refresh:
                        timetable_parser.download_timetable(force=True)
                        timetable_parser.parse_timetable(force=True)
                        force_timetable_refresh = False
                    
                    timetable_data = timetable_parser.get_schedule_for_display()
                    last_timetable_update = current_time
                    logging.info(f"Timetable updated: {timetable_data}")
                except Exception as e:
                    logging.error(f"Error updating timetable: {e}")
                    
            # Check if there are new bulletin items in the queue
            if not bulletin_queue.empty():
                try:
                    # Get the latest bulletin items from the queue
                    new_items = bulletin_queue.get_nowait()
                    # Only update bulletin_items if we actually got items
                    if new_items:
                        bulletin_items = new_items
                        logging.info(f"Main thread: Retrieved {len(bulletin_items)} bulletin items from queue")
                    else:
                        logging.warning("Retrieved empty bulletin items list from queue")
                except Exception as e:
                    logging.error(f"Error retrieving bulletin items from queue: {e}")
                    # Don't reset bulletin_items if there was an error, keep using existing items
            
            # Check for touch event
            if touch_event.is_set():
                touch_event.clear()
                
                # Redraw screen based on current screen state
                if current_screen == NETWORK_INFO_SCREEN:
                    # Only update network info if it's been more than the update interval
                    if current_time - last_network_update > network_update_interval:
                        logging.info("Updating network information")
                        network_info = get_network_info()
                        last_network_update = current_time
                    
                    image = draw_network_info_screen(fonts, network_info)
                elif current_screen == TIMETABLE_SCREEN:
                    # Timetable screen - use current timetable data
                    if timetable_data is not None:
                        # Get current time and date for the top bar
                        now = time.localtime()
                        current_time_str = time.strftime("%H:%M", now)
                        current_date_str = time.strftime("%d/%m/%Y", now)
                        
                        image = draw_timetable_screen(fonts, timetable_data, current_time_str, current_date_str)
                    else:
                        # Fallback if timetable data is not available
                        image = draw_network_info_screen(fonts, network_info)
                        logging.warning("Timetable data not available, showing network screen instead")
                elif current_screen == BULLETIN_SCREEN:
                    # Bulletin screen - use the latest bulletin items from the thread
                    # We don't need to fetch here as the thread will keep the data updated
                    image = draw_bulletin_screen(fonts, bulletin_items,
                                               scroll_position=bulletin_scroll_position,
                                               selected_item=bulletin_selected_item,
                                               content_scroll_position=bulletin_content_scroll_position)
                else:
                    # Main screen - draw with latest time and stats
                    image = draw_time_image(fonts, weather_data, stats)
                
                # Increment partial refresh counter for screen transition
                partial_refresh_count += 1
                
                # Do a full refresh much less frequently to protect the display
                if partial_refresh_count >= PARTIAL_REFRESHES_BEFORE_FULL:
                    logging.info(f"Full refresh after {PARTIAL_REFRESHES_BEFORE_FULL} partial refreshes")
                    epd.display_Base(epd.getbuffer(image))
                    partial_refresh_count = 0  # Reset counter
                else:
                    # Use partial refresh for most updates to protect the display
                    logging.info(f"Partial refresh ({partial_refresh_count}/{PARTIAL_REFRESHES_BEFORE_FULL})")
                    epd.display_Partial(epd.getbuffer(image))
                continue
            
            # Update weather periodically
            if current_time - last_weather_update > WEATHER_UPDATE_INTERVAL:
                logging.info("Updating weather data")
                weather_data = get_weather()
                last_weather_update = current_time
            
            # Check for touch event
            if touch_event.is_set():
                touch_event.clear()
                
                # Redraw screen based on current screen state
                if current_screen == NETWORK_INFO_SCREEN:
                    # Only update network info if it's been more than the update interval
                    if current_time - last_network_update > network_update_interval:
                        logging.info("Updating network information")
                        network_info = get_network_info()
                        last_network_update = current_time
                    
                    image = draw_network_info_screen(fonts, network_info)
                    
                    # Increment partial refresh counter for screen transition
                    partial_refresh_count += 1
                elif current_screen == TIMETABLE_SCREEN:
                    # Timetable screen - draw with latest timetable data
                    if timetable_data:
                        image = draw_timetable_screen(fonts, timetable_data)
                    else:
                        # Fallback to dummy data only if no actual timetable data is available
                        logging.warning("No timetable data available, using dummy data")
                        dummy_timetable_data = {
                            'week': 1,
                            'day': 'Mon',
                            'is_weekend': False,
                            'schedule': {
                                '1': [{'class': 'Math', 'time': '08:00'}],
                                '2': [{'class': 'Science', 'time': '09:00'}],
                                '3': [{'class': 'History', 'time': '10:00'}],
                                '4': [{'class': 'English', 'time': '11:00'}],
                                '5': [{'class': 'PE', 'time': '12:00'}]
                            }
                        }
                        image = draw_timetable_screen(fonts, dummy_timetable_data)
                    
                    # Increment partial refresh counter for screen transition
                    partial_refresh_count += 1
                elif current_screen == BULLETIN_SCREEN:
                    # Bulletin screen - use the latest bulletin items from the thread
                    # We don't need to fetch here as the thread will keep the data updated
                    
                    # Get current state before update
                    previous_selected_item = bulletin_selected_item
                    
                    # Draw new bulletin screen image
                    image = draw_bulletin_screen(fonts, bulletin_items,
                                               scroll_position=bulletin_scroll_position,
                                               selected_item=bulletin_selected_item,
                                               content_scroll_position=bulletin_content_scroll_position)
                    
                    # Check if we entered or exited an article view
                    if (previous_selected_item is None and bulletin_selected_item is not None) or \
                       (previous_selected_item is not None and bulletin_selected_item is None):
                        # Article selection state changed - use full refresh
                        logging.info("Full refresh - entering or exiting bulletin article")
                        epd.display_Base(epd.getbuffer(image))
                        partial_refresh_count = 0  # Reset counter
                    else:
                        # Normal bulletin navigation - always use partial refresh
                        logging.info("Partial refresh - bulletin navigation")
                        epd.display_Partial(epd.getbuffer(image))
                        # Don't increment partial_refresh_count for bulletin scrolling
                else:
                    # Main screen - draw with latest time and stats
                    image = draw_time_image(fonts, weather_data, stats)
                    
                    # Increment partial refresh counter for screen transition
                    partial_refresh_count += 1
                
                # Do a full refresh much less frequently to protect the display
                # Exception for bulletin screen - we've already handled its refresh logic above
                # Also force a full refresh when entering/leaving bulletin screen
                if force_full_refresh:
                    logging.info(f"Full refresh - entering or leaving bulletin screen")
                    epd.display_Base(epd.getbuffer(image))
                    partial_refresh_count = 0  # Reset counter
                    force_full_refresh = False  # Reset flag
                elif current_screen != BULLETIN_SCREEN and partial_refresh_count >= PARTIAL_REFRESHES_BEFORE_FULL:
                    logging.info(f"Full refresh after {PARTIAL_REFRESHES_BEFORE_FULL} partial refreshes")
                    epd.display_Base(epd.getbuffer(image))
                    partial_refresh_count = 0  # Reset counter
                elif current_screen != BULLETIN_SCREEN:
                    # Use partial refresh for most updates to protect the display
                    logging.info(f"Partial refresh ({partial_refresh_count}/{PARTIAL_REFRESHES_BEFORE_FULL})")
                    epd.display_Partial(epd.getbuffer(image))
                continue
            
            # If on main screen, handle normal updates
            if current_screen == MAIN_SCREEN:
                # Get current time components (do this once to avoid inconsistencies)
                current_time_struct = time.localtime()
                current_minute = current_time_struct.tm_min
                current_second = current_time_struct.tm_sec
                
                # Check if time changed (minute change or within first 2 seconds of the same minute)
                time_changed = current_minute != last_minute or (current_second < 2 and last_minute == current_minute)
                
                # Handle time updates (these count toward partial refresh counter)
                if time_changed:
                    # Generate new image with updated time and latest stats
                    image = draw_time_image(fonts, weather_data, stats)
                    
                    # Increment partial refresh counter since time changed
                    partial_refresh_count += 1
                    
                    # Do a full refresh much less frequently to protect the display
                    if partial_refresh_count >= PARTIAL_REFRESHES_BEFORE_FULL:
                        logging.info(f"Full refresh after {PARTIAL_REFRESHES_BEFORE_FULL} partial refreshes")
                        epd.display_Base(epd.getbuffer(image))
                        partial_refresh_count = 0  # Reset counter
                    else:
                        logging.info(f"Partial refresh (time updated) ({partial_refresh_count}/{PARTIAL_REFRESHES_BEFORE_FULL})")
                        epd.display_Partial(epd.getbuffer(image))
                    
                    last_minute = current_minute
                
                # Handle just system stats updates (CPU/memory) - don't count toward refresh counter
                elif stats_only_changed and stats_updated:
                    # Generate new image with just updated stats
                    image = draw_time_image(fonts, weather_data, stats)
                    
                    # Use partial refresh but don't increment the counter
                    logging.info("Partial refresh (stats only) - not counting toward full refresh")
                    epd.display_Partial(epd.getbuffer(image))
            
            # Handle timetable screen time updates
            elif current_screen == TIMETABLE_SCREEN and timetable_data is not None:
                # Get current time components
                current_time_struct = time.localtime()
                current_minute = current_time_struct.tm_min
                current_second = current_time_struct.tm_sec
                
                # Check if time changed
                time_changed = current_minute != last_minute or (current_second < 2 and last_minute == current_minute)
                
                # Update the screen if time changed
                if time_changed:
                    # Get formatted time and date for top bar
                    current_time_str = time.strftime("%H:%M", current_time_struct)
                    current_date_str = time.strftime("%d/%m/%Y", current_time_struct)
                    
                    # Generate new image with updated time
                    image = draw_timetable_screen(fonts, timetable_data, current_time_str, current_date_str)
                    
                    # Increment partial refresh counter
                    partial_refresh_count += 1
                    
                    # Do a full refresh if entering/leaving bulletin screen or periodically otherwise
                    if force_full_refresh:
                        logging.info(f"Full refresh - entering or leaving bulletin screen")
                        epd.display_Base(epd.getbuffer(image))
                        partial_refresh_count = 0
                        force_full_refresh = False  # Reset flag
                    elif current_screen != BULLETIN_SCREEN and partial_refresh_count >= PARTIAL_REFRESHES_BEFORE_FULL:
                        logging.info(f"Full refresh after {PARTIAL_REFRESHES_BEFORE_FULL} partial refreshes")
                        epd.display_Base(epd.getbuffer(image))
                        partial_refresh_count = 0
                    else:
                        logging.info(f"Partial refresh (timetable time updated) ({partial_refresh_count}/{PARTIAL_REFRESHES_BEFORE_FULL})")
                        epd.display_Partial(epd.getbuffer(image))
                    
                    last_minute = current_minute                # Handle bulletin screen updates
            elif current_screen == BULLETIN_SCREEN:
                # Get current time components for time updates
                current_time_struct = time.localtime()
                current_minute = current_time_struct.tm_min
                current_second = current_time_struct.tm_sec
                
                # Check if time changed (minute change)
                time_changed = current_minute != last_minute or (current_second < 2 and last_minute == current_minute)
                
                # Update time display if needed
                if time_changed:
                    # Get formatted time and date
                    current_time_str = time.strftime("%H:%M", current_time_struct)
                    current_date_str = time.strftime("%d/%m/%Y", current_time_struct)
                    
                    # Redraw bulletin screen with updated time
                    image = draw_bulletin_screen(fonts, bulletin_items,
                                                current_time=current_time_str,
                                                current_date=current_date_str,
                                                scroll_position=bulletin_scroll_position,
                                                selected_item=bulletin_selected_item,
                                                content_scroll_position=bulletin_content_scroll_position)
                    
                    # Partial refresh when time changes - do NOT increment refresh counter
                    epd.display_Partial(epd.getbuffer(image))
                    last_minute = current_minute
                
                # Just check if we have new bulletin items from the thread
                elif not bulletin_queue.empty():
                    try:
                        # Get the latest bulletin items from the queue
                        bulletin_items = bulletin_queue.get_nowait()
                        
                        # Redraw bulletin screen with latest items
                        image = draw_bulletin_screen(fonts, bulletin_items,
                                                   scroll_position=bulletin_scroll_position,
                                                   selected_item=bulletin_selected_item,
                                                   content_scroll_position=bulletin_content_scroll_position)
                        
                        # Use partial refresh for bulletin updates - do NOT increment refresh counter
                        epd.display_Partial(epd.getbuffer(image))
                    except Exception as e:
                        logging.error(f"Error updating bulletin screen: {e}")
            
            time.sleep(REFRESH_INTERVAL)

    except KeyboardInterrupt:
        logging.info("Cleaning up and exiting")
        # Signal threads to exit
        touch_thread_running = False
        bulletin_thread_running = False
        time.sleep(0.5)  # Give threads time to exit
        
        # Properly shutdown the display without a full refresh
        epd.sleep()
        epd.Dev_exit()
        sys.exit()

def draw_bulletin_screen(fonts, bulletin_items, current_time=None, current_date=None, scroll_position=0, selected_item=None, content_scroll_position=0):
    """Wrapper function to call the bulletin_utils version of draw_bulletin_screen"""
    # Add debug information
    logging.info(f"Drawing bulletin screen with {len(bulletin_items)} items")
    
    if render_bulletin_screen is not None:
        # Make sure to only pass the expected number of arguments
        return render_bulletin_screen(epd, fonts, bulletin_items, current_time, current_date, 
                                     scroll_position, selected_item, content_scroll_position)
    else:
        # Fallback if the imported function is not available
        logging.error("Bulletin rendering function not available")
        image = Image.new('1', (epd.height, epd.width), 255)
        draw = ImageDraw.Draw(image)
        font_lg, font_md, font_sm, font_xs = fonts
        draw.text((10, 50), "Bulletin module not available", font=font_sm, fill=0)
        
        # Apply rotation if needed
        if config.get('display_rotation') == 180:
            image = image.rotate(180)
        
        return image

# Add the entry point at the end of the file
if __name__ == '__main__':
    main()