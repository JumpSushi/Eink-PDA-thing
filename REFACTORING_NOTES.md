# Code Refactoring Notes

## Overview
This document describes the code duplication refactoring performed on the Eink-PDA-thing project.

## Changes Summary

### New File: `display_utils.py`
A new shared utility module containing common display-related functions:

#### Functions:
1. **`has_time_changed(current_minute, last_minute, current_second)`**
   - Purpose: Detect when the display time needs updating
   - Returns: True if minute changed or within first 2 seconds of any minute
   - Usage: Replaces 3 instances of duplicated time checking logic

2. **`apply_display_rotation(image, config)`**
   - Purpose: Apply 180° rotation if configured
   - Returns: Rotated or original image
   - Usage: Replaces 5 instances of rotation logic across drawing functions

3. **`draw_header_bar(draw, epd, fonts, current_time, current_date)`**
   - Purpose: Draw the standard header with time and date
   - Usage: Shared between timetable and other screens

4. **`draw_navigation_button(draw, fonts, x1, y1, x2, y2, text, fill_color, text_color)`**
   - Purpose: Draw navigation buttons with consistent styling
   - Usage: Replaces duplicated button drawing code

### Modified Files

#### `main.py`
- **Imports:** Added display_utils imports with fallback implementations
- **Removed:** Duplicated helper function definitions (~51 line reduction)
- **Added:** `render_current_screen()` function to consolidate screen rendering
- **Updated:** All drawing functions now use shared utilities:
  - `draw_time_image()`
  - `draw_network_info_screen()`
  - `draw_timetable_screen()`
  - `draw_bulletin_screen()` wrapper

- **Eliminated:** Second touch event handling block (~80 lines removed)

#### `bulletin_utils.py`
- **Imports:** Added display_utils imports with fallback implementations
- **Updated:** Uses `draw_navigation_button()` and `apply_display_rotation()`
- **Preserved:** Custom header logic for "< Back" button functionality

## Benefits

### Maintainability
- **Single Source of Truth:** Common functionality now exists in one place
- **Easier Updates:** Changes to shared logic only need to be made once
- **Reduced Bugs:** Less duplicated code means fewer places for bugs to hide

### Testability
- **Isolated Functions:** Utility functions can be tested independently
- **Clear Contracts:** Well-documented function interfaces
- **Verified Behavior:** All utilities have been tested

### Code Quality
- **DRY Principle:** Don't Repeat Yourself - followed throughout
- **Clean Code:** More readable and maintainable
- **Documented:** Comprehensive docstrings for all functions

## Backward Compatibility

All changes maintain backward compatibility:
- **Fallback Implementations:** Each module includes fallback versions of utilities
- **Graceful Degradation:** Import errors are handled without crashing
- **No Breaking Changes:** All existing functionality preserved

## Testing Done

1. **Syntax Validation:** All Python files compile without errors
2. **Unit Tests:** Helper functions tested with edge cases
3. **Security Scan:** CodeQL analysis shows 0 vulnerabilities
4. **Code Review:** Addressed all review feedback

## Usage Examples

### Using `has_time_changed()`
```python
current_time_struct = time.localtime()
current_minute = current_time_struct.tm_min
current_second = current_time_struct.tm_sec

if has_time_changed(current_minute, last_minute, current_second):
    # Update the display
    update_display()
    last_minute = current_minute
```

### Using `apply_display_rotation()`
```python
# Create your image
image = Image.new('1', (epd.height, epd.width), 255)
# ... draw content ...

# Apply rotation if configured
image = apply_display_rotation(image, config)
return image
```

### Using `draw_header_bar()`
```python
draw = ImageDraw.Draw(image)
current_time = time.strftime("%H:%M")
current_date = time.strftime("%d/%m/%Y")

draw_header_bar(draw, epd, fonts, current_time, current_date)
```

### Using `draw_navigation_button()`
```python
# Draw a "Next" button in the top right
draw_navigation_button(draw, fonts, 270, 0, 295, 15, "Next")
```

## Migration Guide

If you're updating custom code that used the old patterns:

1. **For time checking:** Replace inline logic with `has_time_changed()`
2. **For rotation:** Replace `if config.get('display_rotation') == 180: image.rotate(180)` with `apply_display_rotation(image, config)`
3. **For headers:** Use `draw_header_bar()` for standard headers
4. **For buttons:** Use `draw_navigation_button()` for consistent button styling

## Future Improvements

Potential areas for further refactoring (not critical):
- Consider creating a context object for `render_current_screen()` to reduce parameter count
- Additional shared drawing utilities for common UI patterns
- Configuration management utilities

## Questions?

If you have questions about these changes or need help understanding the refactoring, please refer to:
- This document for high-level overview
- `display_utils.py` for detailed function documentation
- Git history for specific changes and reasoning
