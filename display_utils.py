#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Display Utilities Module

Common helper functions for e-ink display rendering to reduce code duplication.
"""

def has_time_changed(current_minute, last_minute, current_second):
    """Check if the time has changed (minute change or within first 2 seconds of any minute)
    
    This ensures the display updates when:
    1. The minute actually changes (current_minute != last_minute)
    2. We're in the first 2 seconds of any minute (to catch boundary updates)
    
    Args:
        current_minute: Current minute value
        last_minute: Last recorded minute value  
        current_second: Current second value
        
    Returns:
        bool: True if time has changed or we're in first 2 seconds
    """
    return current_minute != last_minute or current_second < 2

def apply_display_rotation(image, config):
    """Apply display rotation if configured
    
    Args:
        image: PIL Image to rotate
        config: Configuration dict with display_rotation setting
        
    Returns:
        PIL Image, rotated if necessary
    """
    if config and config.get('display_rotation') == 180:
        return image.rotate(180)
    return image

def draw_header_bar(draw, epd, fonts, current_time, current_date):
    """Draw the common header bar with time and date
    
    Args:
        draw: ImageDraw object
        epd: E-paper display object
        fonts: Tuple of fonts (font_lg, font_md, font_sm, font_xs)
        current_time: Time string to display
        current_date: Date string to display
    """
    _, _, font_sm, _ = fonts
    draw.rectangle([(0, 0), (epd.height, 15)], outline=0, fill=0)
    draw.text((5, 1), current_time, font=font_sm, fill=255)
    draw.text((epd.height//2 - 10, 1), "|", font=font_sm, fill=255)
    draw.text((epd.height//2, 1), current_date, font=font_sm, fill=255)

def draw_navigation_button(draw, fonts, x1, y1, x2, y2, text, fill_color=0, text_color=255):
    """Draw a navigation button
    
    Args:
        draw: ImageDraw object
        fonts: Tuple of fonts
        x1, y1, x2, y2: Button coordinates
        text: Button text
        fill_color: Button background color (default 0 = black)
        text_color: Text color (default 255 = white)
    """
    _, _, _, font_xs = fonts
    draw.rectangle([(x1, y1), (x2, y2)], outline=0, fill=fill_color)
    draw.text((x1 + 3, y1 + 1), text, font=font_xs, fill=text_color)
