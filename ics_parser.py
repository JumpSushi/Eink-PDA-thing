#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import os
import requests
import logging
import json
from datetime import datetime, timedelta
from collections import defaultdict

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
                            
                            # For week 1: start from offset
                            # For week 2: start from events_per_week after week 1
                            idx = offset + ((adjusted_week - 1) * events_per_week) + (adjusted_day_idx * 5) + (period - 1)
                            
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
                                
                                # Add to timetable
                                self.timetable[day_name][str(period)].append({
                                    'class': class_display,
                                    'time': time_str,
                                    'week': week,
                                    'description': f"{class_name} {location}"
                                })
                                
                                # Store dates for weeks (use reference date + days offset)
                                base_date = self.reference_date
                                day_offset = days.index(day_name)
                                
                                if week == 1:
                                    week_date = base_date + timedelta(days=day_offset)
                                else:  # week 2
                                    week_date = base_date + timedelta(days=day_offset + 7)
                                    
                                self.weeks[week].add(week_date.date().isoformat())
                
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
    
    def get_day_schedule(self, day_name, week_number=None):
        """Get the schedule for a specific day and week"""
        if week_number is None:
            week_number = self.get_current_week_number()
            
        day_schedule = {}
        
        # Get all periods for the specified day
        for period, classes in self.timetable[day_name].items():
            # Filter classes for the current week and only take the first one
            # (we should only have one unique class per period per week)
            filtered_classes = [c for c in classes if c['week'] == week_number]
            if filtered_classes:
                # Take only the first class for each period - we eliminated duplicates during parsing
                day_schedule[period] = [filtered_classes[0]]
            
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
        return {
            "is_weekend": False,
            "day": day_name,
            "week": week_number,
            "schedule": schedule
        }

def print_full_timetable(parser):
    """Print the full timetable for both weeks"""
    print("\n===== COMPLETE TIMETABLE =====")
    
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    weeks = [1, 2]
    
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
                    print(f"  Period {period} ({time_range}): {class_info['class']}")
    
    print("\n=============================")

# Main execution function
def main():
    logging.basicConfig(level=logging.INFO)
    print("Starting ICS Parser...")
    
    # Define the URL to fetch the calendar file (using the ID 11016 as provided)
    ics_url = "https://lionel2.kgv.edu.hk/local/mis/calendar/timetable.php/11016/e637b5e2f8ec8eb6c5690f745facd66c.ics"
    
    # Initialize the parser
    parser = ICSParser(ics_url)
    
    # Force fresh download and parse
    print("Downloading fresh ICS file...")
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
        else:
            print("Failed to parse ICS file")
    else:
        print("Failed to download ICS file")

# Entry point
if __name__ == "__main__":
    main()
