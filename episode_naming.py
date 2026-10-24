"""
Episode naming helpers for the Jellyfin Library Manager.

Jellyfin guesses episode numbers from file names. Release names such as
"Cyberpunk Edgerunners 2 - 01" make it pick the number in the show title,
so library links get a clean "Show S01E01.mkv" name when the episode number
is certain, and keep the release name when it is not.
"""

import os
import re
from collections import Counter
from typing import Dict, List, Optional
from config import VIDEO_EXTENSIONS

EXTRAS_FOLDER_NAME = "extras"

_BRACKETED = re.compile(r'\[[^\]]*\]|\([^)]*\)|\{[^}]*\}')
_SEASON_EPISODE = re.compile(r'(?<![a-z0-9])s(\d{1,2})[ ._-]?e(\d{1,4})(?!\d)', re.IGNORECASE)
_CROSS_EPISODE = re.compile(r'(?<![a-z0-9])(\d{1,2})x(\d{2,3})(?!\d)', re.IGNORECASE)
_TAGGED_EPISODE = re.compile(r'(?<![a-z0-9])(?:episode|ep|e(?=\d))[ ._-]*(\d{1,4})(?:v\d{1,2})?(?![a-z0-9]|\.\d)', re.IGNORECASE)
_DASH_EPISODE = re.compile(r'(?<= - )(\d{1,4})(?:v\d{1,2})?(?![a-z0-9]|\.\d)', re.IGNORECASE)
_NUMBER_TOKEN = re.compile(r'(?<![a-z0-9])(\d{1,4})(?:v\d{1,2})?(?![a-z0-9])', re.IGNORECASE)
_SEASON_WORD = re.compile(
    r'(?<![a-z0-9])(?:season[ ._-]?(\d{1,2})|s(\d{1,2})(?=e\d|[^a-z0-9]|$)|(\d{1,2})(?:st|nd|rd|th)[ ._-]?season)(?!\d)',
    re.IGNORECASE,
)
_SPECIALS_WORD = re.compile(r'(?<![a-z0-9])(?:specials?|ovas?|oads?|sp\d{0,2})(?![a-z0-9])', re.IGNORECASE)

_EXTRA_KEYWORDS = r'(?:nc ?op|nc ?ed|creditless|opening|ending|op|ed|pv|cm|menu|preview|trailer|teaser|promo)'
_EXTRA_AT_START = re.compile(
    r'^(?:(?:nc ?)?(?:op|ed)(?: ?\d{1,2}[a-z]?(?: |$)|$)'
    r'|(?:creditless|opening|ending|pv|cm|menu|preview|trailer|teaser|promo)s?(?: ?\d{1,2})?(?: |$))'
)
_EXTRA_AFTER_DASH = re.compile(rf' - {_EXTRA_KEYWORDS}s?(?: ?\d{{1,2}}[a-z]?)?(?: ?v\d)?$')
_EXTRA_ANYWHERE = re.compile(r'(?<![a-z0-9])(?:nc ?op|nc ?ed|creditless|textless)(?![a-z])')
_EXTRAS_FOLDER = re.compile(
    r'^(?:extras?|bonus(?: features)?|featurettes?|interviews?|trailers?|menus?|previews?|pvs?|cms?|op ?(?:&|and|\+)? ?ed)$'
)


def _clean_stem(file_name: str) -> str:
    """Drop a video extension and bracketed tags, and normalize separators."""
    stem, extension = os.path.splitext(file_name)
    if extension.lower() not in VIDEO_EXTENSIONS:
        stem = file_name
    stem = _BRACKETED.sub(' ', stem).replace('_', ' ')
    return ' '.join(stem.split())


def _words(name: str) -> str:
    """Lowercase words for keyword checks, with dots treated as spaces."""
    return ' '.join(_clean_stem(name).replace('.', ' ').lower().split())


def is_extra_video(file_name: str) -> bool:
    """Return True for openings, endings, previews, menus, and similar extras."""
    words = _words(file_name)
    return bool(
        _EXTRA_AT_START.search(words)
        or _EXTRA_AFTER_DASH.search(words)
        or _EXTRA_ANYWHERE.search(words)
    )


def is_extras_folder(folder_name: str) -> bool:
    """Return True for torrent subfolders that hold extras, not episodes."""
    words = _words(folder_name)
    return bool(_EXTRAS_FOLDER.search(words) or _EXTRA_ANYWHERE.search(words))


def is_specials_name(name: str) -> bool:
    """Return True for folder or file names that mark specials or OVAs."""
    return bool(_SPECIALS_WORD.search(_clean_stem(name)))


def season_number_in_name(name: str) -> Optional[int]:
    """Find an explicit season number such as S02E01, 2x01, Season 2, S2, or 2nd Season."""
    stem = _clean_stem(name)
    for pattern in (_SEASON_EPISODE, _CROSS_EPISODE):
        match = pattern.search(stem)
        if match:
            return int(match.group(1))
    match = _SEASON_WORD.search(stem)
    if match:
        return int(next(group for group in match.groups() if group is not None))
    return None


def _explicit_episode(stem: str) -> Optional[int]:
    for pattern, group in ((_SEASON_EPISODE, 2), (_CROSS_EPISODE, 2), (_TAGGED_EPISODE, 1), (_DASH_EPISODE, 1)):
        match = pattern.search(stem)
        if match:
            return int(match.group(group))
    return None


def _varying_position(token_lists: List[List[int]]) -> Optional[int]:
    """Find the first number position that differs between files, if each file has its own value."""
    shortest = min(len(tokens) for tokens in token_lists)
    for position in range(shortest):
        values = {tokens[position] for tokens in token_lists}
        if len(values) == 1:
            continue
        return position if len(values) == len(token_lists) else None
    return None


def detect_episode_numbers(file_names: List[str]) -> Dict[str, Optional[int]]:
    """Detect episode numbers for files from one source folder. Unknown numbers stay None."""
    stems = {file_name: _clean_stem(file_name) for file_name in file_names}
    numbers = {file_name: _explicit_episode(stem) for file_name, stem in stems.items()}

    pending = [file_name for file_name in file_names if numbers[file_name] is None]
    if len(pending) > 1:
        token_lists = {
            file_name: [int(token) for token in _NUMBER_TOKEN.findall(stems[file_name])]
            for file_name in pending
        }
        position = _varying_position(list(token_lists.values()))
        if position is not None:
            for file_name in pending:
                numbers[file_name] = token_lists[file_name][position]
    return numbers


def plan_episode_link_names(source_paths: List[str], show_title: str, season_number: int) -> Dict[str, str]:
    """Map each episode source path to its library link name inside one season folder."""
    episode_by_path: Dict[str, Optional[int]] = {}
    paths_by_folder: Dict[str, List[str]] = {}
    for source_path in source_paths:
        paths_by_folder.setdefault(os.path.dirname(source_path), []).append(source_path)
    for folder_paths in paths_by_folder.values():
        numbers = detect_episode_numbers([os.path.basename(path) for path in folder_paths])
        for path in folder_paths:
            episode_by_path[path] = numbers[os.path.basename(path)]

    episode_counts = Counter(number for number in episode_by_path.values() if number is not None)
    show_name = ' '.join(show_title.split())
    link_names = {}
    for source_path in source_paths:
        episode = episode_by_path[source_path]
        if episode is None or episode_counts[episode] > 1 or not show_name:
            link_names[source_path] = os.path.basename(source_path)
            continue
        extension = os.path.splitext(source_path)[1]
        link_names[source_path] = f"{show_name} S{season_number:02d}E{episode:02d}{extension}"
    return link_names
