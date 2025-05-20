#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import os
import requests
import logging
import json
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

class ICSParser:
    def __init__(self, ics_url, cache_dir=None):
        self.ics_url = ics_url
        
        # Set cache directory or default to user's home directory
        if cache_dir is None:
            self.cache_dir = os.path.expanduser("~/.timetable_cache")
        else:
            self.cache_dir = cache_dir
            
        self.cache_file = os.path.join(self.cache_dir, "timetable.ics")
        self.parsed_cache_file = os.path.join(self.cache_dir, "timetable.json")
        
        # Make sure cache directory exists
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
        
        self.timetable = defaultdict(lambda: defaultdict(list))
        self.weeks = {1: [], 2: []}
        
        # Week 1 Monday reference date (May 19, 2025)
        self.reference_date = datetime(2025, 5, 19)
        self.reference_week = 1
        
        # If we're running this on May 17, 2025 (weekend before Week 1)
        # We need to handle this specially since get_current_week_number will be 
        # based on this reference date
        current_date = datetime.now().date()
        if current_date < self.reference_date.date():
            logging.info(f"Current date {current_date} is before reference date, using Week 1 as current week")
            
        # Define the period times for each day
        self.period_times = {
            "Monday": {
                "1": "08:15-09:05",  # 50-minute periods on Monday
                "2": "09:15-10:05",
                "3": "10:45-11:35",
                "4": "11:45-12:35",
                "5": "13:15-14:05"
            },
            "Tuesday": {
                "1": "08:15-09:15",  # 60-minute periods
                "2": "09:15-10:15",
                "3": "11:15-12:15",
                "4": "12:25-13:25",
                "5": "14:20-15:20"
            },
            "Wednesday": {
                "1": "08:15-09:15",
                "2": "09:15-10:15",
                "3": "11:15-12:15",
                "4": "12:25-13:25",
                "5": "14:20-15:20"
            },
            "Thursday": {
                "1": "08:15-09:15",
                "2": "09:15-10:15",
                "3": "11:15-12:15",
                "4": "12:25-13:25",
                "5": "14:20-15:20"
            },
            "Friday": {
                "1": "08:15-09:15",
                "2": "09:15-10:15",
                "3": "11:15-12:15",
                "4": "12:25-13:25",
                "5": "14:20-15:20"
            }
        }
        
        # Headers for making requests to the school server
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.5',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'Host': 'lionel2.kgv.edu.hk',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0'
        }
        
    def download_timetable(self, force=False):
        """Download the ICS file from the URL and save it to cache"""
        if os.path.exists(self.cache_file) and not force:
            logging.info("Using cached timetable file")
            return True
            
        try:
            logging.info(f"Downloading timetable from {self.ics_url}")
            response = requests.get(self.ics_url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                with open(self.cache_file, 'wb') as f:
                    f.write(response.content)
                logging.info("Timetable downloaded successfully")
                return True
            else:
                logging.error(f"Failed to download timetable: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logging.error(f"Error downloading timetable: {e}")
            return False
    
    def parse_timetable(self, force=False):
        """Parse the cached ICS file into a structured timetable using direct parsing approach"""
        
        # Custom JSON encoder to handle date objects
        class DateTimeEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                elif hasattr(obj, 'isoformat'):
                    return obj.isoformat()
                return super(DateTimeEncoder, self).default(obj)
        
        # Check if we have already parsed the timetable
        if os.path.exists(self.parsed_cache_file) and not force:
            try:
                with open(self.parsed_cache_file, 'r') as f:
                    cache_data = json.load(f)
                    self.timetable = defaultdict(lambda: defaultdict(list))
                    
                    # Convert the JSON back to our structure
                    for day_key, periods in cache_data['timetable'].items():
                        for period_key, classes in periods.items():
                            self.timetable[day_key][period_key] = classes
                    
                    self.weeks = cache_data['weeks']
                    logging.info("Loaded parsed timetable from cache")
                    return True
            except Exception as e:
                logging.error(f"Error loading parsed timetable: {e}")
                # Continue to parse the original file
        
        # Ensure we have a timetable file to parse
        if not os.path.exists(self.cache_file):
            success = self.download_timetable(force=True)
            if not success:
                return False
        
        # Clear existing timetable and weeks data
        self.timetable = defaultdict(lambda: defaultdict(list))
        self.weeks = {1: set(), 2: set()}
        
        try:
            # Parse the ICS file directly using a similar approach to timetableScraper.py
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                raw_ics = f.read().split("BEGIN:VEVENT")
            
            class_list = []
            location_list = []
            datetime_list = []
            
            # Extract class names, locations, and dates from the ICS file
            for event in raw_ics:
                class_name = None
                location = None
                dt_start = None
                
                for line in event.split('\n'):
                    if line.startswith("SUMMARY:"):
                        class_name = line[8:]
                        class_list.append(class_name)
                    elif line.startswith("LOCATION:"):
                        location = line[9:]
                        location_list.append(location)
                    elif line.startswith("DTSTART:"):
                        dt_start = line[8:]
                        datetime_list.append(dt_start)
                    elif line.startswith("DESCRIPTION:") and not location:
                        # Some events might have location in description
                        description = line[12:]
                        parts = description.split()
                        if parts:
                            location = parts[-1]
                            location_list.append(location)
            
            # If we have any classes, let's process them
            if len(class_list) > 0:
                # Calculate the number of events per week (5 days * 5 periods = 25)
                events_per_week = 25
                
                # We need to offset the data to get Week 1 and Week 2 correctly
                # The raw data often starts with Week 2, so we may need to adjust
                offset = 0
                
                # Determine if we need to adjust to get Week 1 first
                # We'll check dates of the first few events to determine
                if len(datetime_list) > 0:
                    try:
                        # Parse the first date
                        first_date_str = datetime_list[0]
                        # Format: YYYYMMDDTHHMMSSZ
                        first_date = datetime.strptime(first_date_str, "%Y%m%dT%H%M%SZ")
                        
                        # Calculate the week number for the first event
                        days_diff = (first_date.date() - self.reference_date.date()).days
                        weeks_diff = days_diff // 7
                        first_event_week = (self.reference_week + weeks_diff) % 2
                        if first_event_week == 0:
                            first_event_week = 2
                        
                        # If the first event is Week 2, shift to get Week 1 first
                        if first_event_week == 2:
                            offset = events_per_week
                    except Exception as e:
                        logging.warning(f"Couldn't parse first date, using default offset: {e}")
                
                # Days of the week
                days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
                
                # Process data for each week
                for week in range(1, 3):
                    for day_idx in range(5):  # 5 days
                        day_name = days[day_idx]
                        
                        for period in range(1, 6):  # 5 periods
                            # Calculate index in the class_list and location_list
                            # Adjust the index calculation to fix the off-by-one day issue and swap Week 1/Week 2
                            # We need to shift the day_idx by -1 (with wrapping) to get correct day alignment
                            adjusted_day_idx = (day_idx - 1) % 5
                            
                            # Swap weeks 1 and 2 for correct data alignment
                            adjusted_week = 3 - week  # This swaps 1 -> 2 and 2 -> 1
                            
                            # Original idx calculation:
                            # idx = offset + ((adjusted_week - 1) * events_per_week) + (adjusted_day_idx * 5) + (period - 1)

                            # Corrected idx calculation:
                            idx_intra_week = (adjusted_day_idx * 5) + (period - 1)
                            
                            # Determine the base index for the current adjusted_week's data
                            if offset == events_per_week and adjusted_week == 2:
                                # ICS starts with Week 2 (offset=25), and we are currently processing for (timetable label) Week 2.
                                # Actual Week 2 data is at the beginning of class_list.
                                idx_base = 0
                            else:
                                # This covers:
                                # 1. ICS starts with Week 1 (offset=0):
                                #    - For timetable label Week 1 (adjusted_week=1): base = 0 + ((1-1)*25) = 0 (Actual Week 1 data)
                                #    - For timetable label Week 2 (adjusted_week=2): base = 0 + ((2-1)*25) = 25 (Actual Week 2 data)
                                # 2. ICS starts with Week 2 (offset=25):
                                #    - For timetable label Week 1 (adjusted_week=1): base = 25 + ((1-1)*25) = 25 (Actual Week 1 data)
                                #    (The case for offset=25 and adjusted_week=2 is handled by the 'if' branch above)
                                idx_base = offset + ((adjusted_week - 1) * events_per_week)
                            
                            idx = idx_base + idx_intra_week
                            
                            # Check if we have data for this index
                            if idx < len(class_list) and idx < len(location_list):
                                class_name = class_list[idx]
                                location = location_list[idx]
                                
                                # Skip empty classes or handle PE classes
                                if not class_name or class_name.strip() == '':
                                    continue
                                    
                                if location.startswith("DESCRIPTION"):
                                    location = 'PE'
                                
                                # Get the time for this period
                                time_str = self.period_times[day_name][str(period)].split('-')[0]
                                
                                # Format the class display
                                class_display = f"{class_name} in {location}"
                                
                                # Add to timetable - use the proper week number (from our loop, not adjusted)
                                # Invert weeks: Fix for issue where Week 1 and Week 2 data were swapped
                                # The data from the ICS file doesn't align with actual Week 1/Week 2 
                                # (e.g., What should be Week 1 is labeled as Week 2 in the data)
                                actual_week = 3 - week  # This inverts the week (1 becomes 2, 2 becomes 1)
                                self.timetable[day_name][str(period)].append({
                                    'class': class_display,
                                    'time': time_str,
                                    'week': actual_week,  # Use the inverted week
                                    'description': f"{class_name} {location}"
                                })
                                
                                # Store dates for weeks (use reference date + days offset)
                                base_date = self.reference_date
                                day_offset = days.index(day_name)
                                
                                # Store the date in the inverted week's list
                                if actual_week == 1:
                                    week_date = base_date + timedelta(days=day_offset)
                                else:  # actual_week 2
                                    week_date = base_date + timedelta(days=day_offset + 7)
                                    
                                self.weeks[actual_week].add(week_date.date().isoformat())
                
                logging.info(f"Successfully parsed {len(class_list)} classes from ICS file")
            else:
                logging.error("No classes found in the ICS file")
                return False
            
            # Convert sets to lists for JSON serialization
            for week in self.weeks:
                self.weeks[week] = sorted(list(self.weeks[week]))
            
            # Save the parsed data to cache
            cache_data = {
                'timetable': {k: dict(v) for k, v in self.timetable.items()},
                'weeks': self.weeks
            }
            
            with open(self.parsed_cache_file, 'w') as f:
                json.dump(cache_data, f, cls=DateTimeEncoder)
                
            logging.info("Timetable parsed and cached successfully")
            return True
                
        except Exception as e:
            logging.error(f"Error parsing timetable: {e}")
            return False
    
    def get_current_week_number(self):
        """Determine the current week number (1 or 2) based on the reference date"""
        today = datetime.now().date()
        
        # If we're before the reference date, handle this special case
        if today < self.reference_date.date():
            # Since we know the reference date (May 19, 2025) is Week 1 Monday,
            # and the current date is May 17, 2025 (weekend before),
            # we'll return Week 1
            logging.info(f"Current date {today} is before reference date, using Week 1")
            return 1
            
        # Calculate days from reference date
        days_from_reference = (today - self.reference_date.date()).days
        
        # Calculate how many weeks have passed since the reference date
        weeks_passed = days_from_reference // 7
        
        # The current week number alternates between 1 and 2
        current_week = (self.reference_week + weeks_passed) % 2
        if current_week == 0:
            current_week = 2
            
        return current_week
    
    def clear_cache(self):
        """Clear the timetable cache, forcing a fresh download on next request"""
        try:
            # Delete cache files if they exist
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
                logging.info(f"Removed cache file: {self.cache_file}")
                
            if os.path.exists(self.parsed_cache_file):
                os.remove(self.parsed_cache_file)
                logging.info(f"Removed parsed cache file: {self.parsed_cache_file}")
                
            return True
        except Exception as e:
            logging.error(f"Error clearing cache: {e}")
            return False
    
    def get_day_schedule(self, day_name, week_number=None):
        """Get the schedule for a specific day and week"""
        if week_number is None:
            week_number = self.get_current_week_number()
            
        logging.info(f"Getting schedule for {day_name}, Week {week_number}")
        day_schedule = {}
        found_any_classes = False
        
        # Log all available classes for this day for debugging
        for period, classes in self.timetable[day_name].items():
            for c in classes:
                logging.debug(f"Available class: Period {period}: {c['class']} (Week {c['week']})")
        
        # Get all periods for the specified day
        for period, classes in self.timetable[day_name].items():
            # Filter classes for the current week and only take the first one
            # (we should only have one unique class per period per week)
            filtered_classes = [c for c in classes if c['week'] == week_number]
            
            if filtered_classes:
                # Take only the first class for each period - we eliminated duplicates during parsing
                day_schedule[period] = [filtered_classes[0]]
                logging.info(f"Found class for Period {period}: {filtered_classes[0]['class']} (Week {filtered_classes[0]['week']})")
                found_any_classes = True
            else:
                logging.warning(f"Period {period}: No class found for Week {week_number}")
        
        # Check if we found any classes for this day/week
        if not found_any_classes:
            logging.warning(f"No classes found for {day_name}, Week {week_number}!")
            
            # Check if we have classes for the other week as a fallback
            other_week = 1 if week_number == 2 else 2
            logging.warning(f"Looking for classes for Week {other_week} as fallback...")
            for period, classes in self.timetable[day_name].items():
                filtered_classes = [c for c in classes if c['week'] == other_week]
                if filtered_classes:
                    logging.warning(f"Found classes for {day_name}, Week {other_week} instead!")
                    # Add the classes for the other week with a warning indicator
                    day_schedule[period] = [filtered_classes[0]]
            
            # If we still have no classes, try forcing a refresh of the timetable data
            if not day_schedule:
                logging.warning(f"Attempting to refresh timetable data for {day_name}, Week {week_number}")
                self.download_timetable(force=True)
                self.parse_timetable(force=True)
                # Try once more after refresh
                for period, classes in self.timetable[day_name].items():
                    filtered_classes = [c for c in classes if c['week'] == week_number]
                    if filtered_classes:
                        day_schedule[period] = [filtered_classes[0]]
        
        # Verify the week numbers in the returned schedule match the requested week
        for period, classes in day_schedule.items():
            if classes and classes[0]['week'] != week_number:
                logging.warning(f"Week number mismatch for {day_name}, Period {period}: " 
                               f"Expected Week {week_number}, got Week {classes[0]['week']}")
                # Fix the week number to match what was requested
                classes[0]['week'] = week_number
                
        return day_schedule
    
    def get_current_day_schedule(self):
        """Get the schedule for the current day"""
        today = datetime.now()
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_name = day_names[today.weekday()]
        
        week_number = self.get_current_week_number()
        
        # Check if it's a weekend (5=Saturday, 6=Sunday)
        if today.weekday() >= 5:
            # For weekends, we'll show the next Monday's schedule
            next_monday_name = "Monday"
            
            # Calculate the week number for next Monday
            days_until_monday = (7 - today.weekday()) % 7  # Days until next Monday
            next_monday_date = today.date() + timedelta(days=days_until_monday)
            
            # Calculate week number for next Monday
            if next_monday_date < self.reference_date.date():
                # If next Monday is before our reference date, use Week 1
                next_week_number = 1
            else:
                # Calculate based on days from reference
                days_from_reference = (next_monday_date - self.reference_date.date()).days
                weeks_passed = days_from_reference // 7
                next_week_number = (self.reference_week + weeks_passed) % 2
                if next_week_number == 0:
                    next_week_number = 2
            
            # Get the next Monday's schedule
            next_monday_schedule = self.get_day_schedule(next_monday_name, next_week_number)
            
            return {
                "is_weekend": True,
                "day": day_name,
                "week": week_number,
                "next_day": next_monday_name,
                "next_week": next_week_number,
                "next_schedule": next_monday_schedule
            }
        
        # Regular weekday
        schedule = self.get_day_schedule(day_name, week_number)
        result = {
            "is_weekend": False,
            "day": day_name,
            "week": week_number,
            "schedule": schedule
        }
        
        # Add validation to check week numbers match what we expect
        logging.info("CURRENT DAY SCHEDULE VALIDATION START ---------------")
        logging.info(f"Expected week number: {week_number}")
        for period, classes in schedule.items():
            if classes:
                if classes[0]['week'] != week_number:
                    logging.warning(f"⚠️ Week mismatch in period {period}: Expected {week_number}, got {classes[0]['week']}")
                else:
                    logging.info(f"✓ Period {period}: {classes[0]['class']} (Week: {classes[0]['week']})")
        logging.info("CURRENT DAY SCHEDULE VALIDATION END -----------------")
        
        return result
        
    def get_schedule_for_display(self):
        """
        Gets the appropriate schedule for display based on current time and day.
        Shows next day's schedule if:
        - It's after 3:20 PM on a regular weekday
        - It's after 2:05 PM on a Monday
        
        Returns:
            A dictionary with timetable data for display
        """
        # Get current time and day
        current_datetime = datetime.now()
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        current_day_name = day_names[current_datetime.weekday()]
        current_hour = current_datetime.hour
        current_minute = current_datetime.minute
        
        # Check if we should show the next day's schedule based on day and time
        show_next_day = False
        
        # Check if it's a weekday (0-4 means Monday-Friday)
        if current_datetime.weekday() <= 4:  # It's a weekday
            if current_day_name == "Monday" and (current_hour > 14 or (current_hour == 14 and current_minute >= 5)):
                # After 2:05 PM on Monday
                show_next_day = True
            elif current_day_name != "Monday" and (current_hour > 15 or (current_hour == 15 and current_minute >= 20)):
                # After 3:20 PM on other weekdays
                show_next_day = True
                
        # First, get the current day's schedule
        current_schedule = self.get_current_day_schedule()
        
        # If we should show the next day's schedule and it's not already the weekend
        if show_next_day and not current_schedule.get("is_weekend", False):
            # Calculate next day
            next_day_datetime = current_datetime + timedelta(days=1)
            next_day_idx = next_day_datetime.weekday()
            
            # If next day is weekend (Saturday or Sunday), show Monday
            if next_day_idx >= 5:  # It's a weekend
                # Use the weekend logic which will show next Monday's schedule
                return self.get_current_day_schedule()
            else:
                # Get next day's name
                next_day_name = day_names[next_day_idx]
                
                # Calculate week number for the next day based on the reference date
                # This ensures consistent week calculation based on the actual date
                # rather than special-casing certain day transitions
                next_day_date = current_datetime.date() + timedelta(days=1)
                
                # Get current week number to check if we're staying in the same week
                current_week_number = self.get_current_week_number()
                
                # For all day transitions within a work week (Monday through Friday),
                # we should stay in the same week number. Only when transitioning to a new
                # work week (Sunday -> Monday) should the week number potentially change.
                
                # Check if we're still within the same work week (Monday to Friday)
                if current_datetime.weekday() < 5 and next_day_idx < 5:
                    # Use current week number for the next day
                    next_week_number = current_week_number
                    logging.info(f"Staying in the same week {next_week_number} when moving from {current_day_name} to {next_day_name}")
                else:
                    # For week transitions (Friday -> Saturday, Saturday -> Sunday, Sunday -> Monday),
                    # calculate using the reference date
                    days_from_reference = (next_day_date - self.reference_date.date()).days
                    
                    # Calculate how many weeks have passed since the reference date
                    weeks_passed = days_from_reference // 7
                    
                    # The week number alternates between 1 and 2
                    next_week_number = (self.reference_week + weeks_passed) % 2
                    if next_week_number == 0:
                        next_week_number = 2
                    logging.info(f"Calculated new week {next_week_number} when moving from {current_day_name} to {next_day_name}")
                    
                # Get the schedule for the next day
                next_day_schedule = self.get_day_schedule(next_day_name, next_week_number)
                
                # Log the schedule details for debugging
                logging.info(f"Next day schedule - Day: {next_day_name}, Week: {next_week_number}")
                for period, classes in next_day_schedule.items():
                    if classes:
                        # Check if the class's actual week matches the requested week
                        if classes[0]['week'] != next_week_number:
                            logging.warning(f"Period {period}: Class week mismatch! Requested Week {next_week_number}, got {classes[0]['week']}")
                        logging.info(f"Period {period}: {classes[0]['class']} (Week {classes[0]['week']})")
                
                # Construct the result similar to get_current_day_schedule output
                result = {
                    "is_weekend": False,
                    "day": next_day_name,
                    "week": next_week_number,
                    "schedule": next_day_schedule,
                    "is_next_day": True  # Flag to indicate this is the next day's schedule
                }
                
                # Add additional validation at the end to ensure week numbers match what we expect
                logging.info("SCHEDULE VALIDATION START ---------------")
                logging.info(f"Expected week number: {next_week_number}")
                for period, classes in next_day_schedule.items():
                    if classes:
                        if classes[0]['week'] != next_week_number:
                            logging.warning(f"⚠️ Week mismatch in period {period}: Expected {next_week_number}, got {classes[0]['week']}")
                        else:
                            logging.info(f"✓ Period {period}: {classes[0]['class']} (Week: {classes[0]['week']})")
                logging.info("SCHEDULE VALIDATION END -----------------")
                
                return result
        
        # Final sanity check - let's directly check what week flags the classes have
        logging.info("🔍 DIRECT CLASS DATA VERIFICATION 🔍")
        weekday = datetime.now().weekday()
        if weekday < 5:  # Only for weekdays (0-4)
            day_name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"][weekday]
            logging.info(f"Checking raw data for {day_name}:")
            for period, classes in self.timetable[day_name].items():
                for class_info in classes:
                    logging.info(f"  Period {period}: {class_info['class']} (Week: {class_info['week']})")
        
        # Default: return current day's schedule
        return current_schedule

def print_full_timetable(parser):
    """Print the full timetable for both weeks"""
    print("\n===== COMPLETE TIMETABLE =====")
    
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    weeks = [1, 2]
    
    current_week = parser.get_current_week_number()
    print(f"Current week: {current_week}")
    print(f"Reference date: {parser.reference_date.strftime('%A, %B %d, %Y')} (Week {parser.reference_week})")
    today = datetime.now()
    print(f"Today's date: {today.strftime('%A, %B %d, %Y')}")
    days_from_reference = (today.date() - parser.reference_date.date()).days
    print(f"Days from reference: {days_from_reference}")
    weeks_passed = days_from_reference // 7
    print(f"Weeks passed: {weeks_passed}")
    calc_week = (parser.reference_week + weeks_passed) % 2
    if calc_week == 0:
        calc_week = 2
    print(f"Calculated week: {calc_week}")
    
    for week_number in weeks:
        print(f"\n--- WEEK {week_number} ---")
        
        for day_name in days:
            print(f"\n{day_name}:")
            
            schedule = parser.get_day_schedule(day_name, week_number)
            periods = sorted(schedule.keys())
            
            if not periods:
                print("  No classes scheduled")
                continue
                
            for period in periods:
                for class_info in schedule[period]:
                    time_range = parser.period_times[day_name][period]
                    print(f"  Period {period} ({time_range}): {class_info['class']} (Week flag: {class_info['week']})")
    
    print("\n=============================")

# Add a utility function to debug week numbering and class filtering
def debug_timetable_data(parser):
    print("\n===== DEBUGGING TIMETABLE DATA =====")
    today = datetime.now()
    current_week = parser.get_current_week_number()
    
    # Print key timetable data
    print(f"Today's date: {today.strftime('%A, %B %d, %Y')}")
    print(f"Reference date: {parser.reference_date.strftime('%A, %B %d, %Y')} (Week {parser.reference_week})")
    print(f"Current calculated week: {current_week}")
    
    # Print raw class data for today's day
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_name = day_names[today.weekday()]
    
    print(f"\nRaw class data for {day_name}:")
    for period, classes in parser.timetable[day_name].items():
        for class_info in classes:
            print(f"  Period {period}: {class_info['class']} (Week: {class_info['week']})")
    
    # Print filtered classes for both weeks
    for week in [1, 2]:
        print(f"\nFiltered classes for {day_name}, Week {week}:")
        day_schedule = {}
        for period, classes in parser.timetable[day_name].items():
            filtered_classes = [c for c in classes if c['week'] == week]
            if filtered_classes:
                day_schedule[period] = filtered_classes
                for class_info in filtered_classes:
                    print(f"  Period {period}: {class_info['class']} (Week: {class_info['week']})")
    
    print("\n=============================")

# Main execution function
def main():
    logging.basicConfig(level=logging.INFO)
    print("Starting ICS Parser...")
    
    # Define the URL to fetch the calendar file (using the ID 11016 as provided)
    ics_url = os.getenv("ICS_PARSER_TEST_URL")
    
    # Initialize the parser
    parser = ICSParser(ics_url)
    
    # Force fresh download and parse
    print("Downloading fresh ICS file...")
    parser.clear_cache()  # Clear the cache first
    download_success = parser.download_timetable(force=True)
    
    if download_success:
        print("\nParsing ICS file...")
        parse_success = parser.parse_timetable(force=True)
        
        if parse_success:
            # Print today's date and current week number
            today = datetime.now()
            current_week = parser.get_current_week_number()
            print(f"\nToday is {today.strftime('%A, %B %d, %Y')} (Week {current_week})")
            
            # Get and print current day schedule
            print("\nToday's schedule:")
            schedule = parser.get_current_day_schedule()
            
            if schedule.get('is_weekend', False):
                print(f"Today is {schedule['day']} (Weekend)")
                print(f"Next Monday (Week {schedule['next_week']}):")
                for period, classes in sorted(schedule['next_schedule'].items()):
                    if classes:
                        time_range = parser.period_times["Monday"][period]
                        print(f"  Period {period} ({time_range}): {classes[0]['class']}")
            else:
                for period, classes in sorted(schedule['schedule'].items()):
                    if classes:
                        time_range = parser.period_times[schedule['day']][period]
                        print(f"  Period {period} ({time_range}): {classes[0]['class']}")
            
            # Print the full timetable for reference
            print_full_timetable(parser)
            
            # Run debugging to analyze timetable data in detail
            debug_timetable_data(parser)
        else:
            print("Failed to parse ICS file")
    else:
        print("Failed to download ICS file")

# Entry point
if __name__ == "__main__":
    main()
