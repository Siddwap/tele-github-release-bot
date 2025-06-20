
# Bot Integration Instructions

To integrate the new txt file handling with bot.py, add these lines:

## 1. Import at the top of bot.py:
```python
from main_bot_integration import initialize_bot_integration, bot_integration
```

## 2. After creating the config object, initialize the integration:
```python
# Initialize bot integration
initialize_bot_integration(config)
```

## 3. In your message handler function, add this as the FIRST check:
```python
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if our integration handles this message
    if bot_integration and await bot_integration.handle_message(update, context):
        return  # Message was handled, don't process further
    
    # ... rest of your existing message handling code
```

## 4. Update the help text in bot.py to include:
```python
help_text += """
📋 **TXT File Commands:**
• /txt_upload - Upload files from txt file
• /txt_links - Upload files and get GitHub links
• /txt_help - Detailed txt upload help
"""
```

This integration will:
- Handle /txt_upload and /txt_links commands properly
- Distinguish between M3U8 and regular files
- Return GitHub links in txt format when requested
- Maintain backward compatibility with existing functionality
