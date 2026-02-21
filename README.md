# 🎬 Jellyfin Library Manager

A comprehensive media library management tool that automates the organization of movies and anime for Jellyfin media servers. This application provides seamless integration with qBittorrent for torrent management, AniList for anime metadata, and Nyaa.si for anime torrent discovery.

## ✨ Features

### 📚 Media Library Management

- **Movie Library**: Organize and manage movie collections with symlink support
- **Anime Library**: Comprehensive anime management with season and episode tracking
- **Automatic File Organization**: Smart file detection and categorization
- **Symlink Management**: Create and manage symbolic links for efficient storage

### 🔄 Torrent Integration

- **qBittorrent Integration**: Direct API integration for torrent management
- **Automatic Torrent Tracking**: Monitor download progress and completion status
- **Background Monitoring**: Continuous tracking of active torrents
- **Nyaa.si Search**: Built-in anime torrent search functionality

### 📊 Metadata & Search

- **AniList Integration**: Rich anime metadata and search capabilities
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
- **`nyaa_api.py`** - Nyaa.si RSS feed parser

### Media Management

- **`movie_manager.py`** - Movie library operations
- **`anime_manager.py`** - Anime library management
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
   ```

4. **Run the application**
   ```bash
   python main.py
   ```

## 📖 Usage Guide

### Main Menu Options

1. **📚 List movies in library** - View all movies in your media folders
2. **➕ Add new movie to library** - Add movies with symlink creation
3. **🗑️ Remove movie from library** - Remove movies and clean up symlinks
4. **📺 List anime in library** - Browse your anime collection
5. **➕ Add new anime to library** - Add anime with AniList integration
6. **🗑️ Remove anime from library** - Remove anime and associated files
7. **📋 View tracked torrents** - Monitor active torrent downloads
8. **🚪 Exit** - Close the application

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
└── Anime/
    ├── Anime Title/
    │   ├── Season 1/
    │   │   ├── episode_01.mkv
    │   │   └── ...
    │   └── Season 2/
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
│   └── nyaa_api.py        # Nyaa.si torrent search
├──
├── Media Management/
│   ├── movie_manager.py   # Movie operations
│   ├── anime_manager.py   # Anime operations
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
