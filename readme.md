# Kick VOD Downloader

A Python-based tool to automatically download and convert Kick.com VODs (Videos on Demand) to MP3 format. Supports both one-time downloads and continuous monitoring of channels for automatic archiving.

## Features

- ✅ Download VODs from Kick.com channels
- ✅ Automatic conversion to MP3 format
- ✅ Live streaming capture with automatic polling
- ✅ Multi-channel monitoring with auto-runner
- ✅ Docker support for easy deployment
- ✅ Cloudflare bypass using Selenium WebDriver
- ✅ Resume support for interrupted downloads
- ✅ Quality selection (480p, 720p, etc.)

## Requirements

### Local Installation
- Python 3.11+
- FFmpeg (for audio conversion)
- Chrome/Chromium browser
- Dependencies listed in `requirements.txt`

### Docker Installation
- Docker
- Docker Compose (optional, for easier setup)

## Installation

### Option 1: Local Setup

1. **Install FFmpeg**
   - Windows: Download from [ffmpeg.org](https://ffmpeg.org/download.html)
   - macOS: `brew install ffmpeg`
   - Linux: `sudo apt-get install ffmpeg`

2. **Clone the repository**
   ```bash
   git clone https://github.com/mertgulmus/kick-vod-downloader.git
   cd kick-vod-downloader
   ```

3. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

### Option 2: Docker Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/mertgulmus/kick-vod-downloader.git
   cd kick-vod-downloader
   ```

2. **Set up environment variables** using a `.env` file:
   ```bash
   # Copy the example file
   cp env.example .env

   # Edit the .env file with your settings
   # At minimum, set CHANNELS to your channel name(s)
   ```

   Example `.env` file:
   ```env
   CHANNELS=channelname1,channelname2
   QUALITY=480p30
   DOWNLOAD_PATH=./kick_vod_downloads
   DEBUG_HTTP=false
   DEBUG_VERBOSE=false
   ```

3. **Build and run with Docker Compose**
   ```bash
   docker-compose up -d
   ```

## Usage

### One-Time VOD Download (Direct M3U8)

Download a VOD directly from an M3U8 playlist URL:

```bash
python kick_vod_downloader.py --m3u8-url "https://stream.kick.com/.../playlist.m3u8"
```

Options:
- `--m3u8-basename`: Custom output filename (optional)
- `--m3u8-poll-seconds`: Polling interval for live streams (default: 60)
- `--debug-http`: Enable HTTP debugging

### Live Channel Monitoring

Monitor a channel and automatically download the latest VOD:

```bash
python kick_vod_downloader.py --live-channel "channelname" --live-quality "480p30"
```

This will:
1. Wait for the channel to go live
2. Retrieve the latest VOD M3U8 playlist
3. Stream and convert to MP3

### Auto-Runner (Multi-Channel Monitoring)

For continuous monitoring of multiple channels:

```bash
python auto_runner.py
```

Configure via environment variables:
```bash
export CHANNELS="channel1,channel2,channel3"
export QUALITY="480p30"
export POLL_SECONDS=60
export LIVE_CHECK_SECONDS=60
export DOWNLOAD_DIR="./kick_vod_downloads"
```

Or use a `.env` file with Docker Compose.

## Configuration

### Using .env File (Recommended for Docker)

Docker Compose automatically reads environment variables from a `.env` file in the same directory.

**Quick Setup:**
```bash
# Copy the example file
cp env.example .env

# Edit .env with your favorite editor
nano .env  # or vim, code, notepad, etc.

# Start the container
docker-compose up -d
```

Your `.env` file should look like:
```env
CHANNELS=yourchannel1,yourchannel2
QUALITY=480p30
DOWNLOAD_PATH=./kick_vod_downloads
DEBUG_HTTP=false
DEBUG_VERBOSE=false
```

### Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `CHANNELS` | Comma-separated list of channel names | - |
| `QUALITY` | Preferred video quality (e.g., 480p30, 720p30) | 480p30 |
| `POLL_SECONDS` | Seconds between playlist polls during streaming | 60 |
| `LIVE_CHECK_SECONDS` | Seconds between live status checks | 60 |
| `DOWNLOAD_DIR` | Directory for downloaded files (in container) | /downloads |
| `DOWNLOAD_PATH` | Host directory path to mount (Docker only) | ./kick_vod_downloads |
| `DEBUG_HTTP` | Enable HTTP request debugging | false |
| `DEBUG_VERBOSE` | Enable verbose debug logging | false |

### Config File (`libs/config.py`)

You can also modify the `Config` class for persistent settings:

```python
class Config:
    DOWNLOAD_DIR = os.path.join(os.getcwd(), "kick_vod_downloads")
    CONVERT_TO_MP3 = True
    DELETE_ORIGINAL_AFTER_CONVERT = False
    TARGET_CHANNEL = ""
    DEBUG_HTTP = False
    DEBUG_VERBOSE = False
```

## Docker Usage

### Using Docker Compose (Recommended)

1. **Create a `.env` file** in the project root:
   ```env
   CHANNELS=yourchannel
   QUALITY=480p30
   DOWNLOAD_PATH=./kick_vod_downloads
   ```

2. **Start the container**:
   ```bash
   docker-compose up -d
   ```

3. **View logs**:
   ```bash
   docker-compose logs -f
   ```

4. **Stop the container**:
   ```bash
   docker-compose down
   ```

### Using Docker Directly

```bash
docker build -t kick-vod-downloader .
docker run -d \
  --name kick-auto \
  -e CHANNELS="yourchannel" \
  -e QUALITY="480p30" \
  -v /path/to/downloads:/downloads \
  kick-vod-downloader
```

## Output Files

Downloaded files are saved in the format:
```
{channel}_{date}_{time}_{quality}.mp3
```

Example: `channelname_2024-09-30_14-30_480p.mp3`

Temporary files are stored in subdirectories during download and can be safely deleted after conversion.

## Troubleshooting

### FFmpeg Not Found
Ensure FFmpeg is installed and available in your system PATH.

### WebDriver Issues
The tool uses `webdriver-manager` to automatically manage ChromeDriver. If issues persist:
- Ensure Chrome/Chromium is installed
- Check Chrome version compatibility
- Try running with `--debug-http` for more information

### Cloudflare Blocking
The tool uses Selenium with stealth techniques to bypass Cloudflare. If blocked:
- Ensure you're using the latest version
- Try reducing request frequency
- Enable debug mode to inspect requests

### No VODs Found
- Verify the channel name is correct
- Check if the channel has any VODs available
- Ensure the channel is live (for live monitoring mode)

## Architecture

- **kick_vod_downloader.py**: CLI for one-time downloads and live channel monitoring
- **auto_runner.py**: Multi-channel continuous monitoring daemon
- **libs/vod_downloader.py**: Core VOD download and streaming logic
- **libs/web_driver_manager.py**: Selenium WebDriver setup and management
- **libs/file_manager.py**: File operations and debug info saving
- **libs/step_logger.py**: Rich console output for progress tracking
- **libs/config.py**: Configuration management

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This tool is provided as-is for educational purposes. Users are responsible for ensuring compliance with Kick.com's Terms of Service. The authors are not responsible for any misuse of this software.

## Changelog

### Version 1.0
- ✅ Fetch VODs from a given channel
- ✅ Download VODs
- ✅ Schedule downloads
- ✅ Instant download
- ✅ Object-oriented design
- ✅ Code cleaning
- ✅ Improved error handling
- ✅ Docker support
- ✅ Multi-channel monitoring
