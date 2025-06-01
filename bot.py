import logging
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import aiohttp
from github_uploader import GitHubUploader  # Import the GitHubUploader class

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, telegram_token: str, github_token: str, github_repo: str, github_release_tag: str):
        self.telegram_token = telegram_token
        self.github_token = github_token
        self.github_repo = github_repo
        self.github_release_tag = github_release_tag
        self.github_uploader = None  # Initialize as None
        self.app = ApplicationBuilder().token(self.telegram_token).build()
        self.register_handlers()
        
        # Initialize GitHub uploader only when needed
        if all([self.github_token, self.github_repo, self.github_release_tag]):
            self.github_uploader = GitHubUploader(
                token=self.github_token,
                repo=self.github_repo,
                release_tag=self.github_release_tag
            )

    def register_handlers(self):
        """Register all command and message handlers."""
        start_handler = CommandHandler('start', self.start)
        help_handler = CommandHandler('help', self.help_command)
        upload_handler = CommandHandler('upload', self.upload_file)
        list_handler = CommandHandler('list', self.list_files)
        delete_handler = CommandHandler('delete', self.handle_delete_command)
        rename_handler = CommandHandler('rename', self.handle_rename_command)
        message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_text_message)

        self.app.add_handler(start_handler)
        self.app.add_handler(help_handler)
        self.app.add_handler(upload_handler)
        self.app.add_handler(list_handler)
        self.app.add_handler(delete_handler)
        self.app.add_handler(rename_handler)
        self.app.add_handler(message_handler)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a welcome message when the /start command is issued."""
        await update.message.reply_text('Hello! I am your GitHub Release Asset Uploader Bot. Use /help to see available commands.')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a help message with available commands."""
        help_text = (
            "Available commands:\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/upload - Upload a file to GitHub Release\n"
            "/list - List all assets in the release\n"
            "/delete - Delete a file from the release\n"
            "/rename - Rename a file in the release"
        )
        await update.message.reply_text(help_text)

    async def upload_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /upload command to upload a file to GitHub Release."""
        try:
            if not self.github_uploader:
                await update.message.reply_text("❌ GitHub uploader not configured!")
                return

            # Check if the user has sent a file with the command
            if not update.message.document:
                await update.message.reply_text("❌ Please attach a file to upload.")
                return

            file = update.message.document
            file_name = file.file_name
            file_size = file.file_size
            file_id = file.file_id

            # Download the file
            new_file = await context.bot.get_file(file_id)
            file_bytes = await new_file.download_as_bytearray()
            file_data = bytes(file_bytes)

            # Upload the file to GitHub Release
            await update.message.reply_text(f"📤 Uploading {file_name}...")
            try:
                download_url = await self.github_uploader.upload_asset(file_data, file_name)
                await update.message.reply_text(f"✅ Successfully uploaded {file_name}!\n🔗 Download URL: {download_url}")
            except Exception as e:
                logger.error(f"Error uploading file: {e}")
                await update.message.reply_text(f"❌ Failed to upload {file_name}: {str(e)}")

        except Exception as e:
            logger.error(f"Error in upload command: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def list_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /list command to list files in GitHub Release."""
        try:
            if not self.github_uploader:
                await update.message.reply_text("❌ GitHub uploader not configured!")
                return

            await update.message.reply_text("📂 Fetching list of files...")
            assets = await self.github_uploader.list_release_assets()

            if not assets:
                await update.message.reply_text("📂 No files found in the release.")
                return

            message = "📂 Files in the release:\n"
            for asset in assets:
                size_mb = asset['size'] / (1024 * 1024)
                message += f"- {asset['name']} ({size_mb:.1f} MB)\n"

            await update.message.reply_text(message)

        except Exception as e:
            logger.error(f"Error in list command: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def handle_delete_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /delete command"""
        try:
            if not self.github_uploader:
                await update.message.reply_text("❌ GitHub uploader not configured!")
                return

            # Get list of assets
            assets = await self.github_uploader.list_release_assets()
            
            if not assets:
                await update.message.reply_text("📂 No files found to delete!")
                return

            # Show numbered list for deletion
            message = "📂 Available files for deletion:\n\n"
            for i, asset in enumerate(assets[:20], 1):  # Show max 20 files
                size_mb = asset['size'] / (1024 * 1024)
                message += f"{i}. {asset['name']} ({size_mb:.1f} MB)\n"
            
            if len(assets) > 20:
                message += f"\n... and {len(assets) - 20} more files\n"
            
            message += "\n💡 Send the file number(s) to delete (e.g., '1' or '1,2,3' or 'all'):"
            
            await update.message.reply_text(message)
            
            # Store assets in context for the next message
            context.user_data['delete_assets'] = assets
            context.user_data['awaiting_delete'] = True

        except Exception as e:
            logger.error(f"Error in delete command: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def handle_rename_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /rename command"""
        try:
            if not self.github_uploader:
                await update.message.reply_text("❌ GitHub uploader not configured!")
                return

            # Get list of assets
            assets = await self.github_uploader.list_release_assets()
            
            if not assets:
                await update.message.reply_text("📂 No files found to rename!")
                return

            # Show numbered list for renaming
            message = "📂 Available files for renaming:\n\n"
            for i, asset in enumerate(assets[:20], 1):  # Show max 20 files
                size_mb = asset['size'] / (1024 * 1024)
                message += f"{i}. {asset['name']} ({size_mb:.1f} MB)\n"
            
            if len(assets) > 20:
                message += f"\n... and {len(assets) - 20} more files\n"
            
            message += "\n💡 Send the file number to rename (e.g., '1'):"
            
            await update.message.reply_text(message)
            
            # Store assets in context for the next message
            context.user_data['rename_assets'] = assets
            context.user_data['awaiting_rename'] = True

        except Exception as e:
            logger.error(f"Error in rename command: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages"""
        try:
            text = update.message.text.strip()
            
            # Check if user is responding to delete command
            if context.user_data.get('awaiting_delete'):
                await self.process_delete_selection(update, context, text)
                return
            
            # Check if user is responding to rename command
            if context.user_data.get('awaiting_rename'):
                await self.process_rename_selection(update, context, text)
                return
            
            # Check if user is providing new name for rename
            if context.user_data.get('awaiting_rename_newname'):
                await self.process_rename_newname(update, context, text)
                return

            # Handle URL
            if text.startswith("http://") or text.startswith("https://"):
                await update.message.reply_text("🔗 URL detected.  Please use /upload command to upload files.")
            else:
                await update.message.reply_text("💬 I am here to help you manage your GitHub Release assets.  Use /help to see available commands.")

        except Exception as e:
            logger.error(f"Error handling text message: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def process_delete_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Process delete file selection"""
        try:
            assets = context.user_data.get('delete_assets', [])
            
            if text.lower() == 'all':
                # Delete all files
                total_files = len(assets)
                success_count = 0
                failed_count = 0
                
                status_message = await update.message.reply_text("🗑️ Starting deletion process...")
                
                for i, asset in enumerate(assets, 1):
                    try:
                        success = await self.github_uploader.delete_asset_by_name(asset['name'])
                        if success:
                            success_count += 1
                        else:
                            failed_count += 1
                        
                        # Update progress every 5 files
                        if i % 5 == 0 or i == total_files:
                            await status_message.edit_text(
                                f"🗑️ Deleting files... {i}/{total_files}\n"
                                f"✅ Deleted: {success_count}\n"
                                f"❌ Failed: {failed_count}"
                            )
                    except Exception as e:
                        logger.error(f"Error deleting {asset['name']}: {e}")
                        failed_count += 1
                
                final_message = (
                    f"✅ Deletion Complete!\n\n"
                    f"📊 Total files: {total_files}\n"
                    f"✅ Successfully deleted: {success_count}\n"
                    f"❌ Failed: {failed_count}"
                )
                await status_message.edit_text(final_message)
            
            else:
                # Parse specific file numbers
                try:
                    file_numbers = [int(x.strip()) for x in text.split(',')]
                    success_count = 0
                    failed_count = 0
                    
                    for num in file_numbers:
                        if 1 <= num <= len(assets):
                            asset = assets[num - 1]
                            try:
                                success = await self.github_uploader.delete_asset_by_name(asset['name'])
                                if success:
                                    success_count += 1
                                    await update.message.reply_text(f"✅ Deleted: {asset['name']}")
                                else:
                                    failed_count += 1
                                    await update.message.reply_text(f"❌ Failed to delete: {asset['name']}")
                            except Exception as e:
                                failed_count += 1
                                await update.message.reply_text(f"❌ Error deleting {asset['name']}: {str(e)}")
                        else:
                            await update.message.reply_text(f"❌ Invalid file number: {num}")
                    
                    await update.message.reply_text(
                        f"🏁 Deletion Summary:\n"
                        f"✅ Successfully deleted: {success_count}\n"
                        f"❌ Failed: {failed_count}"
                    )
                
                except ValueError:
                    await update.message.reply_text("❌ Invalid input! Please send numbers separated by commas (e.g., '1,2,3') or 'all'")
                    return
            
            # Clear the context
            context.user_data.pop('delete_assets', None)
            context.user_data.pop('awaiting_delete', None)

        except Exception as e:
            logger.error(f"Error processing delete selection: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def process_rename_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Process rename file selection"""
        try:
            assets = context.user_data.get('rename_assets', [])
            
            try:
                file_number = int(text.strip())
                if 1 <= file_number <= len(assets):
                    selected_asset = assets[file_number - 1]
                    context.user_data['rename_selected_asset'] = selected_asset
                    context.user_data['awaiting_rename_newname'] = True
                    context.user_data.pop('awaiting_rename', None)
                    
                    await update.message.reply_text(
                        f"📝 Selected file: {selected_asset['name']}\n\n"
                        f"💡 Please send the new filename:"
                    )
                else:
                    await update.message.reply_text(f"❌ Invalid file number: {file_number}")
            
            except ValueError:
                await update.message.reply_text("❌ Invalid input! Please send a file number (e.g., '1')")

        except Exception as e:
            logger.error(f"Error processing rename selection: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def process_rename_newname(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Process new filename for rename"""
        try:
            selected_asset = context.user_data.get('rename_selected_asset')
            new_filename = text.strip()
            
            if not new_filename:
                await update.message.reply_text("❌ Filename cannot be empty!")
                return
            
            old_filename = selected_asset['name']
            
            status_message = await update.message.reply_text(f"🔄 Renaming '{old_filename}' to '{new_filename}'...")
            
            try:
                # Use the fast rename method
                success = await self.github_uploader.rename_asset_fast(old_filename, new_filename)
                
                if success:
                    await status_message.edit_text(f"✅ Successfully renamed '{old_filename}' to '{new_filename}'")
                else:
                    await status_message.edit_text(f"❌ Failed to rename '{old_filename}'")
            
            except Exception as e:
                await status_message.edit_text(f"❌ Rename Error: {str(e)}")
            
            # Clear the context
            context.user_data.pop('rename_assets', None)
            context.user_data.pop('rename_selected_asset', None)
            context.user_data.pop('awaiting_rename_newname', None)

        except Exception as e:
            logger.error(f"Error processing rename new name: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")

    def run(self):
        """Start the bot."""
        self.app.run_polling()

if __name__ == '__main__':
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    github_token = os.environ.get("GITHUB_TOKEN")
    github_repo = os.environ.get("GITHUB_REPO")
    github_release_tag = os.environ.get("GITHUB_RELEASE_TAG")

    if not all([telegram_token, github_token, github_repo, github_release_tag]):
        logger.error("❌ Missing required environment variables. Please set TELEGRAM_BOT_TOKEN, GITHUB_TOKEN, GITHUB_REPO, and GITHUB_RELEASE_TAG.")
    else:
        bot = TelegramBot(telegram_token, github_token, github_repo, github_release_tag)
        bot.run()
