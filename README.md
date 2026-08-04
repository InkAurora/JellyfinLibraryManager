# 🎬 Jellyfin Library Manager

A comprehensive media library management tool that automates the organization of movies, anime, and series for Jellyfin media servers. This application provides seamless integration with qBittorrent for torrent management/search, AniList for anime metadata, IMDb for movie/series metadata, and Nyaa.si for anime torrent discovery.

## ✨ Features

### 📚 Media Library Management

- **Movie Library**: Organize and manage movie collections with symlink support
- **Anime Library**: Comprehensive anime management with season and episode tracking
- **Series Library**: Season/episode cataloging with anime-style season structure
- **Automatic File Organization**: Smart file detection and categorization
- **Symlink Management**: Create and manage symbolic links for efficient storage

### 🔄 Torrent Integration

- **qBittorrent Integration**: Direct API integration for torrent management
- **qBittorrent Search API**: Built-in torrent search for movies and series
- **Automatic Torrent Tracking**: Monitor download progress and completion status
- **Background Monitoring**: Continuous tracking of active torrents
- **Nyaa.si Search**: Built-in anime torrent search functionality

### 📊 Metadata & Search

- **AniList Integration**: Rich anime metadata and search capabilities
- **IMDb Integration**: Movie/series metadata search and selection (API-key-less)
- **Interactive Search**: User-friendly search interface for anime discovery
- **Real-time Updates**: Live torrent status and progress monitoring

### 🎨 User Experience

- **Intuitive Console UI**: Clean, colorful terminal interface
- **Navigation-friendly**: Arrow key navigation with keyboard shortcuts
- **Real-time Feedback**: Live updates and status indicators
- **Platform support**: Currently optimized for Windows terminals

## 🏗️ Architecture

This project follows a modular architecture with clear separation of concerns:

### Core Components

- **`main.py`** - Application entry point and main coordinator
- **`config.py`** - Centralized configuration management
- **`ui.py`** - Terminal-based user interface system
- **`utils.py`** - Common utilities and helper functions

### API Integrations

- **`qbittorrent_api.py`** - qBittorrent Web API client
- **`anilist_api.py`** - AniList GraphQL API integration
- **`imdb_api.py`** - IMDb metadata integration for movie/series metadata
- **`nyaa_api.py`** - Nyaa.si RSS feed parser

### Media Management

- **`movie_manager.py`** - Movie library operations
- **`anime_manager.py`** - Anime library management
- **`series_manager.py`** - Series library management
- **`file_utils.py`** - File system operations and symlink handling

### Torrent Management

- **`torrent_manager.py`** - Torrent tracking and management
- **`torrent_display.py`** - Torrent status visualization
- **`background_monitor.py`** - Background torrent monitoring

### Data Persistence

- **`database.py`** - JSON file storage for torrent tracking and notifications (`torrent_database.json`, `torrent_notifications.json`)

## 🚀 Quick Start

### Prerequisites

- Python 3.7 or higher
- qBittorrent with Web UI enabled
- Internet connection for API access
- Windows OS (current interactive input/navigation relies on `msvcrt`)

### Platform Notes

The current interactive console stack is Windows-oriented because the following modules use `msvcrt`:

- `ui.py`
- `anilist_api.py`
- `nyaa_api.py`
- `custom_autocomplete.py`
- `torrent_display.py`

Core API and data modules are mostly platform-neutral, but menu/search/keyboard UX paths currently target Windows.

### Installation

1. **Clone or download the project**

   ```bash
   git clone https://github.com/InkAurora/JellyfinLibraryManager.git
   cd JellyfinLibraryManager
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the application**

   Edit `config.py` to match your setup:

   ```python
   # qBittorrent settings
   QBITTORRENT_HOST = "localhost:8080"  # Your qBittorrent Web UI address
   QBITTORRENT_USERNAME = "admin"
   QBITTORRENT_PASSWORD = "your_password"

   # Media folder paths
   MEDIA_FOLDERS = [r"C:\Media", r"D:\Media"]  # Your movie directories
   ANIME_FOLDER = r"D:\Anime"                  # Your anime directory
   SERIES_FOLDER = r"D:\Series"                # Your series directory

   # Metadata provider
   METADATA_PROVIDER = "imdb"
   ```

4. **Run the application**
   ```bash
   python main.py
   ```

5. **Run the HTTP API**
   ```bash
   python api_server.py
   ```

   The API listens on `http://127.0.0.1:8765` by default and has no authentication.
   Use `--host` and `--port` to bind elsewhere:

   ```bash
   python api_server.py --host 0.0.0.0 --port 8765
   ```

## HTTP API

The API returns JSON envelopes:

```json
{ "ok": true, "data": {} }
```

Errors use:

```json
{ "ok": false, "error": "Message" }
```

### Core endpoints

- `GET /api` - list available routes
- `GET /api/health` - API health and qBittorrent accessibility
- `GET /api/config` - configured media paths and qBittorrent host, without password

### Library endpoints

- `GET /api/library/movies`
- `POST /api/library/movies`
- `DELETE /api/library/movies?path=...&delete_source=false`
- `GET /api/library/anime`
- `POST /api/library/anime`
- `DELETE /api/library/anime?path=...&delete_source=false`
- `GET /api/library/series`
- `POST /api/library/series`
- `DELETE /api/library/series?path=...&delete_source=false`

Add a movie symlink:

```bash
curl -X POST http://127.0.0.1:8765/api/library/movies ^
  -H "Content-Type: application/json" ^
  -d "{\"path\":\"D:\\Downloads\\Movie.mkv\",\"overwrite\":false}"
```

Add anime or series symlinks:

```bash
curl -X POST http://127.0.0.1:8765/api/library/anime ^
  -H "Content-Type: application/json" ^
  -d "{\"source_path\":\"D:\\Downloads\\Anime Season\",\"name\":\"Anime Name\",\"season_number\":1}"
```

Use `/api/library/series` with the same body for TV series.

Delete a library item:

```bash
curl -X DELETE "http://127.0.0.1:8765/api/library/series?path=D%3A%5CSeries%5CShow%20Name&delete_source=true"
```

`delete_source=false` removes only the Jellyfin library symlink or folder. `delete_source=true` removes tracked torrents through qBittorrent with `delete_files=true` and trusts qBittorrent to delete the source files, matching the CLI behavior. Untracked media falls back to deleting the symlink target when it is outside the configured library folders.

### Torrent endpoints

- `GET /api/torrents/tracked` - tracked torrent database
- `POST /api/torrents/sync` - sync tracked torrents with qBittorrent
- `POST /api/torrents/auto-add` - add completed tracked torrents to the library
- `DELETE /api/torrents/{infohash}?delete_files=false&delete_library=false`

For completed tracked torrents, use `delete_files=true&delete_library=true`. JLM removes the selected torrent and payload through qBittorrent, then removes only library symlinks and episode sidecars owned by that torrent. Other torrents contributing episodes to the same Series remain intact. Empty season/Series folders are removed, and `track.json` is moved to a remaining tracked torrent when needed.

### qBittorrent endpoints

- `GET /api/qbittorrent/status`
- `GET /api/qbittorrent/torrents`
- `POST /api/qbittorrent/torrents`
- `GET /api/qbittorrent/torrents/{infohash}/files`
- `GET /api/qbittorrent/search/plugins`
- `POST /api/qbittorrent/search` - start a torrent search using a custom `pattern`
- `GET /api/qbittorrent/search/{id}/status`
- `GET /api/qbittorrent/search/{id}/results?limit=100&offset=0`
- `DELETE /api/qbittorrent/search/{id}`

Start a custom qBittorrent search:

```bash
curl -X POST http://127.0.0.1:8765/api/qbittorrent/search ^
  -H "Content-Type: application/json" ^
  -d "{\"pattern\":\"The Sopranos S01 1080p\",\"category\":\"all\",\"plugins\":\"enabled\"}"
```

Add and optionally track a torrent:

```bash
curl -X POST http://127.0.0.1:8765/api/qbittorrent/torrents ^
  -H "Content-Type: application/json" ^
  -d "{\"url\":\"magnet:?xt=urn:btih:...\",\"media_type\":\"movie\",\"media_metadata\":{\"title\":\"Movie Name\",\"year\":\"2026\"}}"
```

### Search endpoints

- `GET /api/search/anime?q=one%20piece&limit=10`
- `GET /api/search/movies?q=alien&limit=15`
- `GET /api/search/series?q=lost&limit=15`
- `GET /api/search/nyaa?q=anime%20name&limit=50&sort=seeds`
- `GET /api/search/nyaa/files?url=https%3A%2F%2Fnyaa.si%2Fview%2F...`

## 📖 Usage Guide

### Main Menu Options

1. **📚 List movies in library** - View all movies in your media folders
2. **📺 List anime in library** - Browse your anime collection
3. **📺 List series in library** - Browse your series collection
4. **➕ Add new media** - Branch to add Anime, Movie, or Series
5. **🗑️ Remove media** - Branch to remove Anime, Movie, or Series
6. **📋 View tracked torrents** - Monitor active torrent downloads
7. **🚪 Exit** - Close the application

### Navigation

- **Arrow Keys**: Navigate through menus
- **Enter**: Select an option
- **Escape**: Go back or exit
- **Page Up/Down**: Navigate long lists

### Key Features in Action

#### Adding Anime

1. Search for anime using AniList integration
2. Select from search results with rich metadata
3. Choose torrent from Nyaa.si feeds
4. Automatic tracking and organization upon completion

#### Torrent Monitoring

- Real-time progress tracking
- Automatic completion detection
- Background monitoring system
- Notification system for completed downloads

## ⚙️ Configuration

### qBittorrent Setup

1. Enable Web UI in qBittorrent settings
2. Set username and password
3. Note the port (default: 8080)
4. Update `config.py` with your credentials

### Media Folder Structure

```
Media/
├── Movies/
│   ├── Movie Title (Year)/
│   │   └── movie_file.mkv
│   └── ...
├── Anime/
│   ├── Anime Title/
│   │   ├── Season 1/
│   │   │   ├── episode_01.mkv
│   │   │   └── ...
│   │   └── Season 2/
│   └── ...
└── Series/
    ├── Series Title/
    │   ├── Season 01/
    │   ├── Season 02/
    │   └── Season 00/   # Specials/extras
    └── ...
```

### Color Customization

Modify the `Colors` class in `config.py` to customize the terminal appearance:

```python
class Colors:
    CYAN = '\033[96m'      # Movie titles
    YELLOW = '\033[93m'    # Paths and seasons
    GREEN = '\033[92m'     # Success messages
    RED = '\033[91m'       # Errors
    MAGENTA = '\033[95m'   # Anime titles
    RESET = '\033[0m'      # Reset
```

## 🔧 Dependencies

This project uses the following Python packages:

- **`requests`** (≥2.28.0) - HTTP requests for API communication
- **`feedparser`** (≥6.0.10) - RSS feed parsing for Nyaa.si integration
- **`beautifulsoup4`** (≥4.11.0) - HTML parsing and web scraping

Install all dependencies with:

```bash
pip install -r requirements.txt
```

## 🏆 Key Advantages

### Modular Design

- **Single Responsibility**: Each module has a focused purpose
- **Maintainable**: Easy to understand, modify, and extend
- **Testable**: Independent modules can be tested in isolation
- **Reusable**: Components can be used in other projects

### User Experience

- **Intuitive Interface**: Clean terminal UI with visual feedback
- **Keyboard Navigation**: Efficient navigation without mouse dependency
- **Real-time Updates**: Live monitoring of torrents and downloads
- **Error Handling**: Graceful error recovery and user feedback

### Integration Capabilities

- **API-First**: Native integration with popular services
- **Extensible**: Easy to add new APIs and features
- **Platform support**: Windows-first in the current release
- **Automation**: Background processes for hands-off operation

## 🛠️ Development

### Project Structure

```
jellyfin-library-manager/
├── main.py                 # Application entry point
├── config.py              # Configuration settings
├── requirements.txt       # Python dependencies
├── README.md             # This file
├──
├── Core Modules/
│   ├── ui.py             # User interface system
│   ├── utils.py          # Common utilities
│   └── database.py       # JSON persistence (torrent + notification tracking)
├──
├── API Integrations/
│   ├── qbittorrent_api.py # qBittorrent client
│   ├── anilist_api.py     # AniList integration
│   ├── imdb_api.py        # IMDb movie/series metadata
│   └── nyaa_api.py        # Nyaa.si torrent search
├──
├── Media Management/
│   ├── movie_manager.py   # Movie operations
│   ├── anime_manager.py   # Anime operations
│   ├── series_manager.py  # Series operations
│   └── file_utils.py      # File system utilities
└──
└── Torrent Management/
    ├── torrent_manager.py    # Torrent tracking
    ├── torrent_display.py    # Status visualization
    └── background_monitor.py # Background monitoring
```

### Adding New Features

1. **Create a new module** or extend existing functionality
2. **Follow naming conventions** and maintain consistency
3. **Add configuration options** to `config.py` if needed
4. **Update imports** in relevant modules
5. **Test thoroughly** before committing changes

### Code Style Guidelines

- Follow PEP 8 Python style guidelines
- Use type hints for better code documentation
- Add comprehensive docstrings to functions and classes
- Use meaningful variable and function names
- Keep functions focused and modular

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch
3. Make your changes with proper documentation
4. Test your changes thoroughly
5. Submit a pull request with a clear description

## 📄 License

This project is open source. Please refer to the license file for details.

## 🆘 Support & Troubleshooting

### Common Issues

**Connection Problems**

- Verify qBittorrent Web UI is enabled and accessible
- Check firewall settings and port availability
- Ensure correct credentials in `config.py`

**File Path Issues**

- Use absolute paths in configuration
- Ensure media folders exist and are accessible
- Check file permissions for symlink creation

**API Rate Limits**

- AniList and Nyaa.si may have rate limits
- The application includes reasonable delays between requests
- Avoid excessive rapid searches

### Getting Help

If you encounter issues:

1. Check the configuration settings
2. Verify all dependencies are installed
3. Review the console output for error messages
4. Check file and folder permissions

## 🔮 Future Enhancements

### Planned Features

- **Web Interface**: Browser-based management interface
- **Mobile Support**: Responsive design for mobile devices
- **Plugin System**: Extensible architecture for custom plugins
- **Additional APIs**: Support for more anime and movie databases
- **Cloud Integration**: Support for cloud storage providers
- **Advanced Filtering**: Enhanced search and filtering capabilities

### Potential Integrations

- **Plex Support**: Alternative to Jellyfin integration
- **Sonarr/Radarr**: Integration with popular \*arr applications
- **Discord Notifications**: Real-time notifications via Discord
- **Telegram Bot**: Mobile notifications and control
- **Trakt Integration**: Watch history and recommendations
