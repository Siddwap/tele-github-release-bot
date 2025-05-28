
# Telegram GitHub Release Uploader Bot

A Telegram bot that uploads files to GitHub releases with real-time progress tracking and speed monitoring.

## Features

- 📤 Upload files directly from Telegram to GitHub releases
- 🌐 Download files from URLs and upload to GitHub
- 📊 Real-time progress tracking with upload/download speeds
- 💾 Memory-efficient streaming for large files (up to 4GB)
- ⚡ Production-ready with Gunicorn WSGI server
- 🐳 Docker and Docker Compose support

## Prerequisites

1. **Telegram Bot Token**: Create a bot via [@BotFather](https://t.me/BotFather)
2. **Telegram API Credentials**: Get from [my.telegram.org](https://my.telegram.org)
3. **GitHub Personal Access Token**: Create with `repo` permissions
4. **GitHub Repository**: Must have a release with the specified tag

## Quick Start

### Using Docker Compose (Recommended)

1. Clone this repository:
```bash
git clone <your-repo-url>
cd telegram-github-bot
```

2. Copy environment file and configure:
```bash
cp .env.example .env
# Edit .env with your credentials
```

3. Start the bot:
```bash
docker-compose up -d
```

### Using Docker

1. Build the image:
```bash
docker build -t telegram-github-bot .
```

2. Run the container:
```bash
docker run -d \
  --name telegram-github-bot \
  -p 5000:5000 \
  -e TELEGRAM_API_ID=your_api_id \
  -e TELEGRAM_API_HASH=your_api_hash \
  -e TELEGRAM_BOT_TOKEN=your_bot_token \
  -e GITHUB_TOKEN=your_github_token \
  -e GITHUB_REPO=username/repository \
  -e GITHUB_RELEASE_TAG=v1.0.0 \
  telegram-github-bot
```

### Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variables or create `.env` file

3. Run the bot:
```bash
python run.py
```

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_API_ID` | Telegram API ID from my.telegram.org | Yes |
| `TELEGRAM_API_HASH` | Telegram API Hash from my.telegram.org | Yes |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | Yes |
| `GITHUB_TOKEN` | GitHub Personal Access Token | Yes |
| `GITHUB_REPO` | Target repository (format: username/repo) | Yes |
| `GITHUB_RELEASE_TAG` | Release tag to upload to | Yes |
| `LOG_LEVEL` | Logging level (INFO, DEBUG, ERROR) | No (default: INFO) |

### GitHub Setup

1. Create a Personal Access Token:
   - Go to GitHub Settings → Developer settings → Personal access tokens
   - Generate new token with `repo` scope
   - Copy the token

2. Create a release in your repository:
   - Go to your repository → Releases → Create a new release
   - Set a tag (e.g., `v1.0.0`)
   - Publish the release

## Usage

### Bot Commands

- `/start` - Show welcome message and instructions
- `/help` - Show detailed help information
- `/status` - Check current upload status

### File Upload

1. Send any file directly to the bot (up to 4GB)
2. Bot will download from Telegram and upload to GitHub
3. Returns the download URL when complete

### URL Upload

1. Send a direct download URL to the bot
2. Bot will download the file and upload to GitHub
3. Returns the download URL when complete

## Features

### Real-time Progress Tracking
- Download progress from Telegram/URL
- Upload progress to GitHub
- Speed monitoring (MB/s)
- Visual progress bars

### Memory Efficiency
- Streaming downloads and uploads
- No full file loading into memory
- Supports large files up to 4GB

### Production Ready
- Gunicorn WSGI server
- Proper logging
- Error handling
- Docker support

## API Endpoints

- `GET /` - Health check endpoint
- Returns: "Free Storage Server Working"

## Logs

Logs are written to:
- Console output
- `bot.log` file (when running locally)
- Container logs (when using Docker)

## Troubleshooting

### Common Issues

1. **Bot not responding**: Check bot token and network connectivity
2. **GitHub upload fails**: Verify token permissions and release exists
3. **Large file upload fails**: Check available disk space and memory
4. **Speed issues**: Ensure good network connectivity

### Debug Mode

Set `LOG_LEVEL=DEBUG` for verbose logging.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review logs for error details
3. Create an issue on GitHub
