#!/usr/bin/python
# -*- coding:utf-8 -*-
from dotenv import load_dotenv
from datetime import datetime
import os
import sys
import json
import time
import logging
import socket
import threading
import queue
import subprocess # Add subprocess import

libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

# Import the ICS parser
try:
    from ics_parser import ICSParser
except ImportError:
    ICSParser = None # Placeholder

# Import bulletin utilities
try:
    from bulletin_utils import (
        fetch_bulletin_items,
        bulletin_thread_function,
        draw_bulletin_screen as render_bulletin_screen
    )
except ImportError:
    fetch_bulletin_items = None
    bulletin_thread_function = None
    render_bulletin_screen = None

# Setup font directories
fontdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
fonts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'fonts')
if not os.path.exists(fonts_dir):
    os.makedirs(fonts_dir, exist_ok=True)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
FONT_PATH = os.path.join(fontdir, 'Font.ttc')
REDHAT_REGULAR_PATH = os.path.join(fonts_dir, 'RedHatDisplay-Regular.ttf')
REDHAT_MEDIUM_PATH = os.path.join(fonts_dir, 'RedHatDisplay-Medium.ttf')
REDHAT_BOLD_PATH = os.path.join(fonts_dir, 'RedHatDisplay-Bold.ttf')

from PIL import Image, ImageDraw, ImageFont
from TP_lib import epd2in9_V2 # Hardware specific, will error on dev machine
from TP_lib import icnt86   # Hardware specific, will error on dev machine

# Constants
REFRESH_INTERVAL = 0.1
PARTIAL_REFRESHES_BEFORE_FULL = 5
WEATHER_UPDATE_INTERVAL = 600  # 10 minutes
STATS_UPDATE_INTERVAL = 5
TIMETABLE_UPDATE_INTERVAL = 3600  # 1 hour
BULLETIN_UPDATE_INTERVAL = 1800  # 30 minutes
TIMETABLE_URL = os.getenv("TIMETABLE_URL")
BULLETIN_URL = "https://lionel2.kgv.edu.hk/local/mis/bulletin/bulletin.php"

# Screen states
BULLETIN_SCREEN = 3
NETWORK_INFO_SCREEN = 2
MAIN_SCREEN = 1
TIMETABLE_SCREEN = 0

# Configure logging
logging.basicConfig(level=logging.INFO)

try:
    import requests
except ImportError:
    requests = None

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
            return config
    except (FileNotFoundError, json.JSONDecodeError):
        return {'weather_enabled': False}

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
        logging.warning("Requests library not available. Cannot fetch weather.")
        return None

    api_key = os.getenv("OPENWEATHERMAP_API_KEY")
    if not api_key:
        logging.warning("OpenWeatherMap API key not found in environment variables.")
        return None

    city = 'Hong Kong'
    country_code = 'HK'
    unit = config.get('temperature_unit', 'C')
    units_param = 'metric' if unit == 'C' else 'imperial'
    
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city},{country_code}&appid={api_key}&units={units_param}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
        data = response.json()
        
        if data.get('cod') != 200:
            logging.error(f"Weather API error: {data.get('message', 'Unknown error')}")
            return None
            
        temp = data.get('main', {}).get('temp')
        description = data.get('weather', [{}])[0].get('description')

        if temp is None or description is None:
            logging.error("Weather data incomplete in API response.")
            return None

        return {
            'temp': temp,
            'description': description
        }
    except requests.exceptions.RequestException as e:
        logging.error(f"Weather request failed: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode weather API response: {e}")
        return None
    except Exception as e: # Catch any other unexpected errors
        logging.error(f"An unexpected error occurred in get_weather: {e}")
        return None

def get_system_stats():
    """Get system statistics like CPU temperature and memory usage."""
    stats = {'cpu_temp': None, 'mem_usage': None}

    # CPU Temperature (Raspberry Pi specific)
    try:
        # Use subprocess for better error handling and to capture output
        result = subprocess.check_output(['vcgencmd', 'measure_temp'], text=True)
        # Example output: temp=45.5'C
        stats['cpu_temp'] = float(result.split('=')[1].split("'")[0])
    except FileNotFoundError:
        # vcgencmd not found, likely not a Raspberry Pi or not in PATH
        logging.info("vcgencmd command not found. CPU temperature not available.")
    except (IndexError, ValueError, subprocess.CalledProcessError) as e:
        logging.warning(f"Could not parse CPU temperature: {e}")
    except Exception as e: # Catch any other unexpected errors
        logging.error(f"An unexpected error occurred while getting CPU temperature: {e}")

    # Memory Usage - using free command
    try:
        # Use subprocess for the free command
        result = subprocess.check_output("free | grep Mem | awk '{print int($3/$2 * 100)}'", shell=True, text=True)
        stats['mem_usage'] = int(result.strip())
    except (ValueError, subprocess.CalledProcessError) as e:
        logging.warning(f"'free' command failed to get memory usage: {e}")
    except Exception as e: # Catch any other unexpected errors
        logging.error(f"An unexpected error occurred while getting memory usage with 'free': {e}")
            
    return stats

def draw_time_image(fonts, weather_data, stats):
    font_lg, font_md, font_sm, _ = fonts  # Unpack needed fonts, ignore xs
    image = Image.new('1', (epd.height, epd.width), 255)  # White background
    draw = ImageDraw.Draw(image)
    
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    current_date = now.strftime("%Y-%m-%d")
    
    # Draw time and date
    draw.text((20, 10), current_time, font=font_lg, fill=0)
    draw.text((20, 45), current_date, font=font_md, fill=0)
    
    # Draw weather
    y_pos = 80
    if weather_data:
        temp_unit = config.get('temperature_unit', 'C')
        weather_text = f"{weather_data['temp']:.1f}°{temp_unit} {weather_data['description']}"
        draw.text((20, y_pos), weather_text[:32], font=font_md, fill=0)
        y_pos += 25 # Increment y_pos for next element
    
    # System stats
    if stats.get('cpu_temp') is not None:
        cpu_text = f"CPU: {stats['cpu_temp']}°C"
        draw.text((20, y_pos), cpu_text, font=font_sm, fill=0)
        if stats.get('mem_usage') is not None:
            mem_text = f"Mem: {stats['mem_usage']}%"
            draw.text((100, y_pos), mem_text, font=font_sm, fill=0) # Positioned to the right of CPU temp
    
    # Draw button for Info screen
    draw.rectangle([(250, 0), (295, 127)], outline=0) # Button border
    draw.text((255, 60), "Info", font=font_sm, fill=0)   # Button text
    
    if config.get('display_rotation') == 180:
        image = image.rotate(180)
    
    return image

def get_network_info():
    """Get network information including WiFi SSID, IP address, and hostname."""
    info = {
        'wifi': "N/A",
        'ip': "N/A",
        'hostname': "pda.local"  # Default, can be overridden
    }

    # Get hostname
    try:
        hostname = socket.gethostname()
        if hostname: # Ensure hostname is not empty
            info['hostname'] = f"{hostname}.local"
    except socket.gaierror as e:
        logging.warning(f"Could not get hostname: {e}. Using default '{info['hostname']}'.")
    except Exception as e:
        logging.error(f"Unexpected error getting hostname: {e}. Using default '{info['hostname']}'.")

    # Get IP address
    s = None # Ensure s is defined for finally block
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0) # Add a timeout to prevent long hangs
        s.connect(("8.8.8.8", 80))  # Connect to a known external server (doesn't send data)
        info['ip'] = s.getsockname()[0]
    except socket.timeout:
        logging.warning("Timeout when trying to get IP address. Network might be down or slow.")
    except OSError as e: # Catches socket.error and other OS-level errors
        logging.warning(f"Could not get IP address: {e}")
    except Exception as e:
        logging.error(f"Unexpected error getting IP address: {e}")
    finally:
        if s:
            s.close()

    # Get WiFi network name (SSID) - Linux specific using iwgetid
    try:
        process = subprocess.run(['iwgetid', '-r'], capture_output=True, text=True, check=False, timeout=5)
        if process.returncode == 0:
            wifi_name = process.stdout.strip()
            if wifi_name:
                info['wifi'] = wifi_name
            else:
                logging.info("iwgetid returned empty string, possibly not connected to WiFi.")
                info['wifi'] = "Not Connected"
        else:
            error_message = process.stderr.strip() if process.stderr else process.stdout.strip()
            if "No such device" in error_message or "Not connected" in error_message or not error_message:
                 logging.info(f"Not connected to a WiFi network or wireless interface down (iwgetid output: '{error_message}').")
                 info['wifi'] = "Not Connected"
            else:
                logging.warning(f"iwgetid failed to get WiFi SSID: {error_message}")
    except FileNotFoundError:
        logging.info("iwgetid command not found. Cannot determine WiFi SSID. (This is normal if not on Linux or wireless_tools not installed)")
    except subprocess.TimeoutExpired:
        logging.warning("Timeout when trying to run iwgetid.")
    except Exception as e:
        logging.error(f"An unexpected error occurred while getting WiFi SSID: {e}")
        
    return info

def initialize_fonts():
    """Initialize fonts without refreshing the display"""
    logging.info("Initializing fonts")
    
    # Attempt to use Red Hat Display fonts first
    try:
        if all(os.path.exists(p) for p in [REDHAT_BOLD_PATH, REDHAT_MEDIUM_PATH, REDHAT_REGULAR_PATH]):
            logging.info("Using Red Hat Display fonts")
            return (
                ImageFont.truetype(REDHAT_BOLD_PATH, 24),
                ImageFont.truetype(REDHAT_MEDIUM_PATH, 18), 
                ImageFont.truetype(REDHAT_REGULAR_PATH, 12),
                ImageFont.truetype(REDHAT_REGULAR_PATH, 10)  # Extra small font for timetable
            )
        else:
            logging.warning("Red Hat Display fonts not found. Falling back to default font.")
    except Exception as e:
        logging.error(f"Error loading Red Hat fonts: {e}. Falling back to default font.")
    
    # Fallback to default font
    logging.info("Using default font")
    return (
        ImageFont.truetype(FONT_PATH, 24),
        ImageFont.truetype(FONT_PATH, 18),
        ImageFont.truetype(FONT_PATH, 12),
        ImageFont.truetype(FONT_PATH, 10)  # Extra small font for timetable
    )

def touch_detection_thread():
    """Thread function for touch detection using INT pin method."""
    # Globals accessed by this thread and its helpers
    global current_screen, touch_event, touch_thread_running, touch_dev, touch_old
    global bulletin_scroll_position, bulletin_selected_item, bulletin_content_scroll_position
    global bulletin_items, force_full_refresh

    logging.info("Touch detection thread started")

    # Initialize touch controller (assuming touch is a global object)
    touch.ICNT_Init()

    # Variables for touch debounce
    last_touch_time = 0
    debounce_time = 0.3  # Reduced to 0.3 seconds for faster response

    # --- Touch Area Constants ---
    # Common navigation button (right side of screen)
    NAV_BUTTON_COMMON_X_MIN, NAV_BUTTON_COMMON_X_MAX = 250, 295
    NAV_BUTTON_COMMON_Y_MIN, NAV_BUTTON_COMMON_Y_MAX = 0, 127

    # Navigation button for Timetable screen (smaller, top right)
    NAV_BUTTON_TIMETABLE_X_MIN, NAV_BUTTON_TIMETABLE_X_MAX = 270, 295
    NAV_BUTTON_TIMETABLE_Y_MIN, NAV_BUTTON_TIMETABLE_Y_MAX = 0, 15

    # Navigation button for Bulletin screen (top right, acts as "Next")
    NAV_BUTTON_BULLETIN_X_MIN, NAV_BUTTON_BULLETIN_X_MAX = 270, 295
    NAV_BUTTON_BULLETIN_Y_MIN, NAV_BUTTON_BULLETIN_Y_MAX = 0, 15

    # Bulletin screen specific areas
    BULLETIN_BACK_BUTTON_SCROLLED_X_MIN, BULLETIN_BACK_BUTTON_SCROLLED_X_MAX = 5, 50
    BULLETIN_BACK_BUTTON_SCROLLED_Y_MIN, BULLETIN_BACK_BUTTON_SCROLLED_Y_MAX = 0, 15

    BULLETIN_BACK_BUTTON_TOP_X_MIN, BULLETIN_BACK_BUTTON_TOP_X_MAX = 5, 50
    BULLETIN_BACK_BUTTON_TOP_Y_MIN, BULLETIN_BACK_BUTTON_TOP_Y_MAX = 20, 35
    
    BULLETIN_RETURN_TO_LIST_BOTTOM_X_MIN, BULLETIN_RETURN_TO_LIST_BOTTOM_X_MAX = 5, 110
    BULLETIN_RETURN_TO_LIST_BOTTOM_Y_MIN, BULLETIN_RETURN_TO_LIST_BOTTOM_Y_MAX = 116, 127

    BULLETIN_CONTENT_SCROLL_UP_X_MIN, BULLETIN_CONTENT_SCROLL_UP_X_MAX = 270, 290
    BULLETIN_CONTENT_SCROLL_UP_Y_MIN, BULLETIN_CONTENT_SCROLL_UP_Y_MAX = 45, 60

    BULLETIN_CONTENT_SCROLL_DOWN_X_MIN, BULLETIN_CONTENT_SCROLL_DOWN_X_MAX = 270, 290
    BULLETIN_CONTENT_SCROLL_DOWN_Y_MIN, BULLETIN_CONTENT_SCROLL_DOWN_Y_MAX = 95, 110

    BULLETIN_LIST_SCROLL_UP_X_MIN, BULLETIN_LIST_SCROLL_UP_X_MAX = 270, 290
    BULLETIN_LIST_SCROLL_UP_Y_MIN, BULLETIN_LIST_SCROLL_UP_Y_MAX = 20, 35

    BULLETIN_LIST_SCROLL_DOWN_X_MIN, BULLETIN_LIST_SCROLL_DOWN_X_MAX = 270, 290
    BULLETIN_LIST_SCROLL_DOWN_Y_MIN, BULLETIN_LIST_SCROLL_DOWN_Y_MAX = 95, 110
    
    BULLETIN_ITEM_SELECT_AREA_X_MAX = 265


    def _is_touch_in_area(x, y, x_min, x_max, y_min, y_max):
        return x_min <= x <= x_max and y_min <= y <= y_max

    # --- Helper function for bulletin screen interactions ---
    def _handle_bulletin_interactions(x, y):
        nonlocal last_touch_time # To update it if action is taken
        global bulletin_selected_item, bulletin_content_scroll_position, force_full_refresh
        global bulletin_scroll_position, bulletin_items, touch_event

        action_taken = False
        current_time_val = time.time() # Get current time for potential update

        if bulletin_selected_item is not None:  # Viewing an item's content
            # Back button (scrolled content)
            if bulletin_content_scroll_position > 0 and _is_touch_in_area(x,y, BULLETIN_BACK_BUTTON_SCROLLED_X_MIN, BULLETIN_BACK_BUTTON_SCROLLED_X_MAX, BULLETIN_BACK_BUTTON_SCROLLED_Y_MIN, BULLETIN_BACK_BUTTON_SCROLLED_Y_MAX):
                bulletin_selected_item = None
                bulletin_content_scroll_position = 0
                force_full_refresh = True
                action_taken = True
            # Back button (top of content)
            elif bulletin_content_scroll_position == 0 and _is_touch_in_area(x,y, BULLETIN_BACK_BUTTON_TOP_X_MIN, BULLETIN_BACK_BUTTON_TOP_X_MAX, BULLETIN_BACK_BUTTON_TOP_Y_MIN, BULLETIN_BACK_BUTTON_TOP_Y_MAX):
                bulletin_selected_item = None
                bulletin_content_scroll_position = 0
                force_full_refresh = True
                action_taken = True
            # "Return to List" button at bottom
            elif _is_touch_in_area(x,y, BULLETIN_RETURN_TO_LIST_BOTTOM_X_MIN, BULLETIN_RETURN_TO_LIST_BOTTOM_X_MAX, BULLETIN_RETURN_TO_LIST_BOTTOM_Y_MIN, BULLETIN_RETURN_TO_LIST_BOTTOM_Y_MAX):
                bulletin_selected_item = None
                bulletin_content_scroll_position = 0
                force_full_refresh = True
                action_taken = True
            # Content scroll up
            elif bulletin_content_scroll_position > 0 and _is_touch_in_area(x,y, BULLETIN_CONTENT_SCROLL_UP_X_MIN, BULLETIN_CONTENT_SCROLL_UP_X_MAX, BULLETIN_CONTENT_SCROLL_UP_Y_MIN, BULLETIN_CONTENT_SCROLL_UP_Y_MAX):
                bulletin_content_scroll_position -= 1
                action_taken = True
            # Content scroll down
            elif _is_touch_in_area(x,y, BULLETIN_CONTENT_SCROLL_DOWN_X_MIN, BULLETIN_CONTENT_SCROLL_DOWN_X_MAX, BULLETIN_CONTENT_SCROLL_DOWN_Y_MIN, BULLETIN_CONTENT_SCROLL_DOWN_Y_MAX):
                bulletin_content_scroll_position += 2 # Scroll 2 lines
                action_taken = True
        else:  # Viewing the list of bulletin items
            # List scroll up
            if bulletin_scroll_position > 0 and _is_touch_in_area(x,y, BULLETIN_LIST_SCROLL_UP_X_MIN, BULLETIN_LIST_SCROLL_UP_X_MAX, BULLETIN_LIST_SCROLL_UP_Y_MIN, BULLETIN_LIST_SCROLL_UP_Y_MAX):
                bulletin_scroll_position -= 1
                action_taken = True
            # List scroll down
            elif _is_touch_in_area(x,y, BULLETIN_LIST_SCROLL_DOWN_X_MIN, BULLETIN_LIST_SCROLL_DOWN_X_MAX, BULLETIN_LIST_SCROLL_DOWN_Y_MIN, BULLETIN_LIST_SCROLL_DOWN_Y_MAX):
                bulletin_scroll_position += 1
                action_taken = True
            # Item selection
            elif x <= BULLETIN_ITEM_SELECT_AREA_X_MAX and bulletin_items:
                start_y = 25 if bulletin_scroll_position > 0 else 45 # Copied from original logic
                item_height_plus_spacing = 33 # Approx height + spacing
                items_on_screen = 4 if bulletin_scroll_position > 0 else 3

                for i in range(items_on_screen):
                    item_top = start_y + (i * item_height_plus_spacing) - 3
                    item_bottom = item_top + 25 # Approx item clickable height
                    if item_top <= y <= item_bottom:
                        select_index = bulletin_scroll_position + i
                        if 0 <= select_index < len(bulletin_items):
                            bulletin_selected_item = select_index
                            bulletin_content_scroll_position = 0
                            force_full_refresh = True
                            action_taken = True
                            break
        
        if action_taken:
            last_touch_time = current_time_val
            touch_event.set()
        return action_taken

    # --- Helper function for main navigation ---
    def _handle_main_navigation_press(x, y):
        nonlocal last_touch_time
        global current_screen, force_full_refresh, touch_event
        global bulletin_scroll_position, bulletin_selected_item, bulletin_content_scroll_position

        action_taken = False
        current_time_val = time.time()

        nav_button_pressed = False
        if current_screen == TIMETABLE_SCREEN and \
           _is_touch_in_area(x, y, NAV_BUTTON_TIMETABLE_X_MIN, NAV_BUTTON_TIMETABLE_X_MAX, NAV_BUTTON_TIMETABLE_Y_MIN, NAV_BUTTON_TIMETABLE_Y_MAX):
            nav_button_pressed = True
        elif current_screen == BULLETIN_SCREEN and \
             _is_touch_in_area(x, y, NAV_BUTTON_BULLETIN_X_MIN, NAV_BUTTON_BULLETIN_X_MAX, NAV_BUTTON_BULLETIN_Y_MIN, NAV_BUTTON_BULLETIN_Y_MAX):
            nav_button_pressed = True
        elif current_screen not in [TIMETABLE_SCREEN, BULLETIN_SCREEN] and \
             _is_touch_in_area(x, y, NAV_BUTTON_COMMON_X_MIN, NAV_BUTTON_COMMON_X_MAX, NAV_BUTTON_COMMON_Y_MIN, NAV_BUTTON_COMMON_Y_MAX):
            nav_button_pressed = True

        if nav_button_pressed:
            action_taken = True
            old_screen = current_screen

            if current_screen == BULLETIN_SCREEN:
                bulletin_scroll_position = 0
                bulletin_selected_item = None
                bulletin_content_scroll_position = 0
            
            # Cycle through screens
            if current_screen == NETWORK_INFO_SCREEN: current_screen = MAIN_SCREEN
            elif current_screen == MAIN_SCREEN: current_screen = TIMETABLE_SCREEN
            elif current_screen == TIMETABLE_SCREEN: current_screen = BULLETIN_SCREEN
            else:  # Was BULLETIN_SCREEN
                current_screen = NETWORK_INFO_SCREEN
            
            force_full_refresh = (old_screen == BULLETIN_SCREEN or current_screen == BULLETIN_SCREEN)
        
        if action_taken:
            last_touch_time = current_time_val
            touch_event.set()
        return action_taken

    # --- Main touch detection loop ---
    while touch_thread_running:
        try:
            if touch.digital_read(touch.INT) == 0:  # Touch detected
                touch_dev.Touch = 1
                touch.ICNT_Scan(touch_dev, touch_old) # Populate touch_dev

                current_time = time.time()
                if touch_dev.TouchCount > 0 and (current_time - last_touch_time > debounce_time):
                    x_pos, y_pos = touch_dev.X[0], touch_dev.Y[0]
                    
                    processed_by_bulletin_interaction = False
                    if current_screen == BULLETIN_SCREEN:
                        if _handle_bulletin_interactions(x_pos, y_pos):
                            processed_by_bulletin_interaction = True
                    if not processed_by_bulletin_interaction: # Only try navigation if bulletin internal action wasn't primary
                         _handle_main_navigation_press(x_pos, y_pos)
                    elif current_screen == BULLETIN_SCREEN : # If bulletin interaction happened, still check its specific nav button
                        _handle_main_navigation_press(x_pos, y_pos)


                touch_dev.Touch = 0 # Reset touch flag
                time.sleep(0.05)  # Small delay
            else:
                touch_dev.Touch = 0
                time.sleep(0.01)  # Short sleep when no touch
                
        except Exception as e:
            logging.error(f"Touch error: {e}")
            # Potentially add more specific error handling or re-initialization if needed
            time.sleep(0.5) # Longer sleep on error
    
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
    elif timetable_data.get("is_next_day", False):
        # If we're showing the next day's schedule (after cutoff time on weekday)
        schedule = timetable_data.get("schedule", {})
    else:
        schedule = timetable_data.get("schedule", {})
    
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

# Bulletin thread variables
bulletin_thread_running = True
bulletin_queue = None

def start_bulletin_thread():
    """Start the bulletin thread function using the imported version if available"""
    global bulletin_thread_running, bulletin_queue
    
    # Set the thread running flag to True
    bulletin_thread_running = True
    
    # Initialize bulletin queue if not already initialized
    if bulletin_queue is None:
        bulletin_queue = queue.Queue(maxsize=1)
    
    # Use the imported function if available, otherwise use a stub that does nothing
    if bulletin_thread_function is not None:
        logging.info("Starting bulletin thread with imported function")
        thread = threading.Thread(
            target=bulletin_thread_function, 
            args=(bulletin_queue, bulletin_thread_running),
            daemon=True
        )
        thread.start()
        return thread
    else:
        # Return a dummy thread object
        logging.error("Bulletin thread function not available")
        return None

def main():
    global touch_thread_running, force_timetable_refresh, bulletin_thread_running, bulletin_queue
    global bulletin_scroll_position, bulletin_selected_item, bulletin_content_scroll_position
    global bulletin_items, force_full_refresh  # Make variables global
    
    # Initialize display once at startup, no status message or initial clear
    epd.init()
    
    # Initialize variables
    fonts = initialize_fonts()
    last_weather_update = 0
    weather_data = None
    last_minute = int(time.strftime("%M"))
    partial_refresh_count = 0
    last_network_update = 0
    network_update_interval = 300  # Update network info every 5 minutes
    force_timetable_refresh = False
    force_full_refresh = False
    
    # Initialize bulletin variables
    bulletin_items = []  # Initialize as empty list
    bulletin_queue = queue.Queue()  # Thread-safe queue for bulletin items
    bulletin_scroll_position = 0
    bulletin_selected_item = None
    bulletin_content_scroll_position = 0
    
    # Initialize timetable variables
    timetable_parser = None
    timetable_data = None
    last_timetable_update = 0
    
    # Try to initialize the timetable parser
    try:
        if ICSParser is not None:
            timetable_parser = ICSParser(TIMETABLE_URL)
            if timetable_parser.download_timetable() and timetable_parser.parse_timetable():
                timetable_data = timetable_parser.get_schedule_for_display()
                last_timetable_update = current_time
                logging.info(f"Timetable initialized: {timetable_data}")
            else:
                logging.error("Failed to initialize timetable")
    except Exception as e:
        logging.error(f"Error initializing timetable: {e}")
    
    # Variables to track system stats changes
    last_stats = {'cpu_temp': None, 'mem_usage': None}
    stats_only_changed = False
    last_stats_update = 0  # Track when we last updated stats
    
    # Initialize the touch controller
    touch.ICNT_Init()
    
    # Get initial system stats and network info
    stats = get_system_stats()
    last_stats = stats.copy()  # Initialize last_stats with the initial values
    network_info = get_network_info()
    
    # Prepare initial screen once - network info screen by default
    image = draw_network_info_screen(fonts, network_info)
    # Use display_Base only once for the first display
    epd.display_Base(epd.getbuffer(image))
    
    # Start touch detection thread
    touch_thread = threading.Thread(target=touch_detection_thread, daemon=True)
    touch_thread.start()
    
    # Start bulletin fetching thread using our new function
    bulletin_thread = start_bulletin_thread()
    
    # Note: bulletin_queue is already initialized in start_bulletin_thread()
    
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
                        # Fallback if timetable data is not available
                        logging.warning("No timetable data available, showing network screen instead")
                        image = draw_network_info_screen(fonts, network_info)
                    
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
        _, _, font_sm, _ = fonts  # Only font_sm is used in the fallback implementation
        draw.text((10, 50), "Bulletin module not available", font=font_sm, fill=0)
        
        # Apply rotation if needed
        if config.get('display_rotation') == 180:
            image = image.rotate(180)
        
        return image

# Add the entry point at the end of the file
if __name__ == '__main__':
    main()