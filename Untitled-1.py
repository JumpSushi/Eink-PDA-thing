#!/usr/bin/python
# -*- coding:utf-8 -*-
import os
import sys
import time
import json
import logging
import threading
import socket
from datetime import datetime

libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

# Import the ICS parser
try:
    from ics_parser import ICSParser
except ImportError:
    # Create a placeholder that will be replaced when we create the actual file
    ICSParser = None

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
TIMETABLE_URL = "https://lionel2.kgv.edu.hk/local/mis/calendar/timetable.php/11016/399239f79819124fc33606ae94435c66.ics"

# Screen states
NETWORK_INFO_SCREEN = 2
MAIN_SCREEN = 1
TIMETABLE_SCREEN = 0

# Configure logging
logging.basicConfig(level=logging.INFO)

try:
    import requests
except ImportError:
    requests = None

try:
    import psutil
except ImportError:
    psutil = None

# Load configuration
def load_config():
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
    api_key = 'f3333928c9ffd47f857eab25111ca132'
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
                    
                    # Handle the main navigation button press
                    if ((current_screen != TIMETABLE_SCREEN and 
                        button_x_min <= x_pos <= button_x_max and button_y_min <= y_pos <= button_y_max) or
                        (current_screen == TIMETABLE_SCREEN and 
                        timetable_button_x_min <= x_pos <= timetable_button_x_max and 
                        timetable_button_y_min <= y_pos <= timetable_button_y_max)):
                        
                        # Cycle through screens
                        if current_screen == NETWORK_INFO_SCREEN:
                            current_screen = MAIN_SCREEN
                        elif current_screen == MAIN_SCREEN:
                            current_screen = TIMETABLE_SCREEN
                        else:  # TIMETABLE_SCREEN
                            current_screen = NETWORK_INFO_SCREEN
                        
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
    left_y += 20
    
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

def main():
    global touch_thread_running, force_timetable_refresh
    
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
    
    # Initialize timetable variables
    timetable_parser = None
    timetable_data = None
    last_timetable_update = 0
    
    # Try to initialize the timetable parser
    try:
        if ICSParser is not None:
            timetable_parser = ICSParser(TIMETABLE_URL)
            if timetable_parser.download_timetable() and timetable_parser.parse_timetable():
                timetable_data = timetable_parser.get_current_day_schedule()
                logging.info(f"Timetable initialized: {timetable_data}")
                last_timetable_update = time.time()
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
    
    try:
        while True:
            current_time = time.time()
            
            # Update system stats periodically rather than every cycle
            stats_updated = False
            if current_time - last_stats_update > STATS_UPDATE_INTERVAL:
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
                    
                    timetable_data = timetable_parser.get_current_day_schedule()
                    last_timetable_update = current_time
                    logging.info(f"Timetable updated: {timetable_data}")
                except Exception as e:
                    logging.error(f"Error updating timetable: {e}")
            
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
                    # For now, we'll use dummy timetable data that changes every minute
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
                    
                    # Do a full refresh periodically
                    if partial_refresh_count >= PARTIAL_REFRESHES_BEFORE_FULL:
                        logging.info(f"Full refresh after {PARTIAL_REFRESHES_BEFORE_FULL} partial refreshes")
                        epd.display_Base(epd.getbuffer(image))
                        partial_refresh_count = 0
                    else:
                        logging.info(f"Partial refresh (timetable time updated) ({partial_refresh_count}/{PARTIAL_REFRESHES_BEFORE_FULL})")
                        epd.display_Partial(epd.getbuffer(image))
                    
                    last_minute = current_minute
            
            time.sleep(REFRESH_INTERVAL)

    except KeyboardInterrupt:
        logging.info("Cleaning up and exiting")
        # Signal touch thread to exit
        touch_thread_running = False
        time.sleep(0.5)  # Give thread time to exit
        
        # Properly shutdown the display without a full refresh
        epd.sleep()
        epd.Dev_exit()
        sys.exit()

if __name__ == '__main__':
    main()