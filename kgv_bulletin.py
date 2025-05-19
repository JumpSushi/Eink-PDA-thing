#!/usr/bin/env python3
# KGV School Bulletin Web Scraper for Year 9
# Retrieves and filters bulletin items for Year 9 students
# Filters out donation requests and feedback forms

import requests
from bs4 import BeautifulSoup
import re
import sys
import argparse
from datetime import datetime
import json
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import time

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def is_feedback_request(item):
    """Check if an item is primarily asking for feedback or form filling"""
    
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
    
    # Items explicitly about donations are not feedback requests, even if they mention forms
    donation_exceptions = [
        "donate books", "books you could donate", "donation drive", 
        "food drive", "donate food", "clothing donation", "support our year 9",
        "non-perishable", "storable foods"
    ]
    
    # If it's clearly a donation-focused post, not a feedback request
    if any(phrase in text_content for phrase in donation_exceptions):
        return False
    
    # Check for form URLs in links
    links = item_text.find_all("a")
    for link in links:
        href = link.get("href", "")
        if ("forms.gle" in href or 
            "docs.google.com/forms" in href or 
            "sites.google.com" in href and "form" in text_content.lower()):
            # Even with a form link, if it's a donation post, don't mark as feedback
            if any(phrase in text_content for phrase in donation_exceptions):
                return False
            return True
    
    # Simple mention of feedback doesn't necessarily make it a feedback request
    return False

def is_donation_request(item):
    """Check if an item is primarily about donations"""
    
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
    for phrase in donation_phrases:
        if phrase in text_content:
            return True
    
    # Check for links that might be about donations
    links = item_text.find_all("a")
    for link in links:
        link_text = link.get_text().lower()
        href = link.get("href", "").lower()
        if any(phrase in link_text for phrase in donation_phrases):
            return True
        if "donate" in href or "donation" in href:
            return True
            
    return False

def generate_headline(text, max_retries=2):
    """Generate a concise headline using Hack Club AI API"""
    
    for attempt in range(max_retries + 1):
        try:
            # Prepare prompt for the AI - designed to get a concise headline
            prompt = (
                f"As a talented headline writer for a school newspaper, create a single-line headline "
                f"(under 10 words) for this school bulletin announcement. Make it catchy, clear, and informative, tell me the most improtant part of the announcement.\n\n"
                f"Return ONLY the headline without quotes, explanation, or additional text:\n\n"
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
            # If it's the last retry, return fallback
            if attempt == max_retries:
                return create_fallback_headline(text)
            
    # Fallback if somehow we exit the loop
    return create_fallback_headline(text)

def create_fallback_headline(text):
    """Create a fallback headline from the original text"""
    # Extract first sentence as fallback
    first_sentence = text.split('.')[0]
    
    # If first sentence is too long, take just first few words
    if len(first_sentence.split()) > 10:
        return ' '.join(first_sentence.split()[:10]) + "..."
    return first_sentence + "..."

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

def main():
    """Main function to run the bulletin scraper"""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="KGV School Bulletin Web Scraper for Year 9",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 kgv_bulletin.py                   # Display top 10 items
  python3 kgv_bulletin.py --save            # Save output to file
  python3 kgv_bulletin.py --items 15        # Display top 15 items
  python3 kgv_bulletin.py --debug           # Show debugging information
  python3 kgv_bulletin.py --ai-headlines    # Add AI-generated headlines
  python3 kgv_bulletin.py --no-color        # Disable colored output
  python3 kgv_bulletin.py --ai-headlines --parallel  # Generate headlines faster
        """
    )
    parser.add_argument("--save", action="store_true", help="Save output to a file")
    parser.add_argument("--items", type=int, default=10, help="Number of items to display (default: 10)")
    parser.add_argument("--url", type=str, default="https://lionel2.kgv.edu.hk/local/mis/bulletin/bulletin.php", 
                       help="URL of the bulletin page")
    parser.add_argument("--debug", action="store_true", help="Show debug information")
    parser.add_argument("--output", type=str, help="Specify output filename (used with --save)")
    parser.add_argument("--ai-headlines", action="store_true", help="Generate concise AI headlines for each item")
    parser.add_argument("--parallel", action="store_true", help="Generate AI headlines in parallel (faster)")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output in terminal")
    args = parser.parse_args()

    # Initialize output file if --save is specified
    output_file = None
    filename = None
    
    # Auto-disable colors if not in a terminal
    if not sys.stdout.isatty():
        args.no_color = True
        
    if args.save:
        # Use custom filename if provided, otherwise generate based on date
        if args.output:
            filename = args.output
        else:
            current_date = datetime.now().strftime("%Y-%m-%d")
            filename = f"kgv_bulletin_{current_date}.txt"
        
        try:
            output_file = open(filename, "w", encoding="utf-8")
            print(f"Saving output to {filename}")
        except Exception as e:
            print(f"Error creating output file: {e}")
            args.save = False

    # Function to print output to both console and file if required
    def print_output(text, color=None, is_bold=False):
        # Apply colors for terminal output only
        console_text = text
        if color and not args.save and not args.no_color:  # No colors when viewing the output in a saved file or when --no-color is used
            if color == "header":
                console_text = f"{Colors.HEADER}{text}{Colors.ENDC}"
            elif color == "blue":
                console_text = f"{Colors.BLUE}{text}{Colors.ENDC}"
            elif color == "green":
                console_text = f"{Colors.GREEN}{text}{Colors.ENDC}"
            elif color == "yellow":
                console_text = f"{Colors.YELLOW}{text}{Colors.ENDC}"
            elif color == "red":
                console_text = f"{Colors.RED}{text}{Colors.ENDC}"
            
            if is_bold:
                console_text = f"{Colors.BOLD}{console_text}{Colors.ENDC}"
                
        print(console_text)
        if output_file:
            output_file.write(text + "\n")  # Plain text for file output

    # Fetch and parse the bulletin page
    try:
        print_output(f"Fetching bulletin from: {args.url}")
        response = requests.get(args.url, timeout=10)
        response.raise_for_status()  # Raise an exception for 4XX/5XX responses
        soup = BeautifulSoup(response.content, "html.parser")
    except requests.exceptions.RequestException as e:
        print_output(f"Error fetching the bulletin: {e}")
        if output_file:
            output_file.close()
        return 1
    except Exception as e:
        print_output(f"Unexpected error: {e}")
        if output_file:
            output_file.close()
        return 1

    # Find the main bulletin content area
    main_content = soup.find("div", class_="studentbuletin")

    # Initialize variables for statistics
    total_found = 0
    y9_items = []

    # Check if main_content was found
    if main_content:
        # Extract the bulletin items (organized in row-fluid divs)
        all_bulletin_items = main_content.find_all("div", class_="row-fluid")
        
        # Filter for items targeted towards Year 9
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
        for i, (item, _) in enumerate(y9_items):
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
                is_feedback = any(pattern.lower() in content.lower() for pattern in feedback_patterns)
                
                if is_normal and not is_feedback:
                    y9_items[i] = (item, False)
                elif is_feedback:
                    y9_items[i] = (item, True)
        
        # Sort items - feedback requests at the end
        # We need to put False (0) first, then True (1)
        y9_items.sort(key=lambda x: 1 if x[1] else 0)
        
        # For debugging, show classifications before limiting
        if args.debug:
            print_output("\nClassified items (before limiting):")
            for i, (item, is_feedback) in enumerate(y9_items[:20], 1):
                item_text = item.find("div", class_="itemtext")
                if item_text:
                    preview = item_text.get_text()[:40].replace('\n', ' ').strip() + "..."
                    is_student = is_from_student(item)
                    item_type = "FEEDBACK REQUEST" if is_feedback else "NORMAL ITEM"
                    source_type = "STUDENT" if is_student else "TEACHER/STAFF"
                    # Note: Donation items are already filtered out at this point
                    print_output(f"Item {i}: {item_type} ({source_type}) - {preview}")
        
        # Save total count before limiting
        total_found = len(y9_items)
        
        # Filter out feedback requests and keep only normal items
        y9_items = [item for item, is_feedback in y9_items if not is_feedback]
        
        # Take only the specified number of items
        y9_items = y9_items[:args.items]
        
        # Generate headlines in parallel if requested
        headlines = {}
        if args.ai_headlines and args.parallel:
            print_output("Generating AI headlines in parallel mode...", color="blue", is_bold=True)
            
            # Prepare the text content for each item
            item_texts = []
            for idx, item in enumerate(y9_items):
                item_text = item.find("div", class_="itemtext")
                if item_text:
                    text_content = item_text.get_text()
                    text_content = re.sub(r'\n\s*\n', '\n\n', text_content).strip()
                    item_texts.append((idx, text_content))
            
            # Set up progress tracking
            total_headlines = len(item_texts)
            completed = 0
            
            # Generate headlines in parallel
            with ThreadPoolExecutor(max_workers=min(5, len(item_texts))) as executor:
                future_to_idx = {executor.submit(generate_headline, text): (idx, text) for idx, text in item_texts}
                for future in concurrent.futures.as_completed(future_to_idx):
                    idx, text = future_to_idx[future]
                    completed += 1
                    
                    try:
                        headline = future.result()
                        headlines[idx] = headline
                        sys.stdout.write(f"\rGenerating headlines: {completed}/{total_headlines} completed")
                        sys.stdout.flush()
                    except Exception as e:
                        headlines[idx] = create_fallback_headline(text)
                        
            # Complete the progress indicator
            print("\nHeadline generation complete!")
        
        print_output("\n" + "=" * 80)
        print_output(f"📢 KGV BULLETIN - YEAR 9 HIGHLIGHTS 📢", color="header", is_bold=True)
        print_output(f"Showing {len(y9_items)} of {total_found} relevant items", color="green")
        print_output("General announcements and Year 9 specific items prioritized")
        print_output("Donation requests and student feedback forms have been filtered out")
        print_output("Posts from teachers with links are still included")
        print_output("=" * 80)
        
        # Process each bulletin item
        for i, item in enumerate(y9_items, 1):
            # Extract the text content from the itemtext div
            item_text = item.find("div", class_="itemtext")
            
            # Print a header for each item
            print_output(f"\nBulletin Item {i}:", color="blue", is_bold=True)
            print_output("-" * 40)
            
            if item_text:
                # Clean up the text content - replace multiple newlines with a single one
                text_content = item_text.get_text()
                # Remove extra whitespace and newlines
                text_content = re.sub(r'\n\s*\n', '\n\n', text_content)
                text_content = text_content.strip()
                
                # Generate AI headline if requested
                if args.ai_headlines:
                    try:
                        if args.parallel and i-1 in headlines:
                            # Use pre-generated headline from parallel processing
                            headline = headlines[i-1]
                        else:
                            # Generate headline on-the-fly
                            headline = generate_headline(text_content)
                            
                        print_output("\n" + "=" * 40)
                        print_output(f"📢 AI HEADLINE: {headline}", color="yellow", is_bold=True)
                        print_output("=" * 40 + "\n")
                    except Exception as e:
                        if args.debug:
                            print_output(f"\nError generating headline: {e}", color="red")
                        # Continue without a headline if there's an error
                
                print_output(text_content)
            else:
                print_output("(No text content)", color="red")
            
            # Extract any attachments
            attachments = item.find("div", class_="itemattachments")
            if attachments and attachments.find_all("a"):
                print_output("\nAttachments:", color="green", is_bold=True)
                for link in attachments.find_all("a"):
                    print_output(f"- {link.get_text(strip=True)}")
                    print_output(f"  Link: {link.get('href')}", color="blue")
            
            # Extract metadata if available
            meta = item.find("div", class_="itemmeta")
            if meta:
                meta_text = meta.get_text(strip=True)
                if meta_text:
                    print_output(f"\nPosted: {meta_text}", color="green")
            
            print_output("=" * 80)
    else:
        print_output("Error: Could not find the bulletin content on the page or no items for Year 9.")
        print_output("The website structure may have changed or there might be connectivity issues.")
        
        if args.debug:
            print_output("\nDebug information:")
            print_output(f"Response status code: {response.status_code}")
            print_output(f"Response content size: {len(response.content)} bytes")
            print_output("\nFirst 5 div elements on the page:")
            for i, div in enumerate(soup.find_all("div")[:5], 1):
                print_output(f"{i}. Class: {div.get('class', 'No class')}, ID: {div.get('id', 'No ID')}")

    # Print summary if items were found
    if total_found > 0:
        print_output("\nSummary:", color="blue", is_bold=True)
        print_output(f"Retrieved {len(y9_items)} of {total_found} bulletin items relevant for Year 9 students", color="green")
        if args.ai_headlines:
            print_output("AI-generated headlines were added to each item", color="yellow")
        if not args.save:
            print_output("Tip: Use --save to save the output to a file", color="blue")

    # Close the output file if it was opened
    if output_file:
        output_file.close()
        print(f"Output saved to {filename}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
