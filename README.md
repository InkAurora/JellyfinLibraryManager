# Jellyfin Library Manager - Modular Structure

## Overview

This is a modularized version of the Jellyfin Library Manager script. The original monolithic script has been broken down into focused, maintainable modules with clear separation of concerns.

## Module Structure

### Core Modules

- **`config.py`** - Configuration settings and constants
- **`utils.py`** - Utility functions for formatting, validation, and common operations
- **`main.py`** - Main application entry point and coordinator

### API Integration Modules

- **`qbittorrent_api.py`** - qBittorrent Web API integration
- **`anilist_api.py`** - AniList API integration for anime search
- **`nyaa_api.py`** - Nyaa.si RSS feed integration for torrent search

### Data Management Modules

- **`database.py`** - Torrent tracking database and notifications management
- **`file_utils.py`** - File system operations and symlink management

### Feature Modules

- **`movie_manager.py`** - Movie library management
- **`anime_manager.py`** - Anime library management
- **`torrent_manager.py`** - Torrent tracking and auto-completion
- **`torrent_display.py`** - Torrent status display and monitoring

### System Modules

- **`ui.py`** - User interface and menu system
- **`background_monitor.py`** - Background monitoring for torrent completion

## Key Improvements

### 1. **Separation of Concerns**

Each module has a single, well-defined responsibility:

- UI logic is separated from business logic
- API integrations are isolated in their own modules
- Database operations are centralized
- File operations are unified

### 2. **Maintainability**

- Smaller, focused files are easier to understand and modify
- Changes to one feature don't affect others
- Clear dependencies between modules

### 3. **Testability**

- Each module can be tested independently
- Mock objects can easily replace dependencies
- Business logic is separated from UI concerns

### 4. **Reusability**

- Modules can be reused in other projects
- API clients can be used standalone
- Common utilities are centralized

### 5. **Configuration Management**

- All settings are centralized in `config.py`
- Easy to modify paths, colors, and other settings
- Environment-specific configurations can be easily managed

## Usage

### Running the Application

```bash
python main.py
```

### Installing Dependencies

```bash
pip install -r requirements.txt
```

### Configuration

Edit `config.py` to customize:

- qBittorrent connection settings
- Media folder paths
- Color schemes
- Monitoring intervals

## Module Dependencies

```
main.py
├── ui.py
├── movie_manager.py
│   ├── file_utils.py
│   ├── ui.py
│   └── utils.py
├── anime_manager.py
│   ├── file_utils.py
│   ├── ui.py
│   ├── anilist_api.py
│   ├── nyaa_api.py
│   ├── qbittorrent_api.py
│   └── database.py
├── torrent_display.py
│   ├── torrent_manager.py
│   ├── database.py
│   └── ui.py
├── background_monitor.py
│   ├── torrent_manager.py
│   └── database.py
└── config.py
```

## Backward Compatibility

The modularized version maintains full backward compatibility by providing legacy function wrappers in each module. This means:

- Existing imports will continue to work
- Function signatures remain the same
- Behavior is preserved

## Future Enhancements

The modular structure makes it easy to add new features:

1. **New Media Types**: Add modules for books, music, etc.
2. **Additional APIs**: Add support for other anime/movie databases
3. **Plugin System**: Create a plugin architecture for custom extensions
4. **Web Interface**: Add a web-based UI module
5. **Database Backends**: Support for different database systems
6. **Cloud Integration**: Add cloud storage support

## Development Guidelines

### Adding New Features

1. Create a new module or extend an existing one
2. Follow the existing naming conventions
3. Add configuration options to `config.py`
4. Update this README with new dependencies

### Testing

1. Test each module independently
2. Verify backward compatibility
3. Test integration points between modules

### Code Style

- Use type hints for better code documentation
- Follow PEP 8 style guidelines
- Add docstrings to all public functions and classes
- Use meaningful variable and function names

## Legacy Script

The original `manager_jellyfin.py` script is preserved for reference. The modular version provides the same functionality with improved organization and maintainability.
