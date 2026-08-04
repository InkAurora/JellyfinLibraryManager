"""
HTTP JSON API for Jellyfin Library Manager.

Run with:
    python api_server.py
"""

import argparse
import json
import os
import re
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from anilist_api import anilist_search
from config import ANIME_FOLDER, MEDIA_FOLDERS, QBITTORRENT_HOST, SERIES_FOLDER
from database import (
    add_torrent_to_database,
    get_tracked_torrents,
    remove_torrent_from_database_by_infohash,
    update_torrent_status,
)
from file_utils import (
    create_anime_symlinks,
    create_movie_symlink,
    create_series_symlinks,
    find_existing_symlink,
    list_anime,
    list_movies,
    list_series,
)
from imdb_api import IMDBAPI
from nyaa_api import get_torrent_file_list, nyaa_rss_search, sort_torrents
from qbittorrent_api import (
    qb_add_torrent,
    qb_check_connection,
    qb_delete_search,
    qb_get_search_plugins,
    qb_get_search_results,
    qb_get_search_status,
    qb_get_torrent_files,
    qb_get_torrent_info,
    qb_login,
    qb_remove_torrent,
    qb_start_search,
)
from torrent_manager import TorrentManager, auto_add_completed_torrents, sync_torrents_with_qbittorrent
from utils import get_media_folder, is_video_file


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 1024 * 1024
INFOHASH_PATTERN = re.compile(r"^[A-Fa-f0-9]{40,64}$")


class ApiError(Exception):
    """Structured HTTP API error."""

    def __init__(self, status_code: int, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.details = details or {}


def _ok(data: Any = None, status: int = 200) -> Tuple[int, Dict[str, Any]]:
    response = {"ok": True}
    if data is not None:
        response["data"] = data
    return status, response


def _normalize_limit(value: Any, default: int = 25, maximum: int = 100) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, maximum))


def _normalize_int(value: Any, default: int = 0, minimum: int = 0, maximum: int = 100000) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError):
        integer = default
    return max(minimum, min(integer, maximum))


def _bool_query(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _required_str(payload: Dict[str, Any], field: str) -> str:
    value = str(payload.get(field, "") or "").strip()
    if not value:
        raise ApiError(400, f"Missing required field: {field}")
    return value


def _as_abs_path(value: str) -> str:
    return os.path.abspath(os.path.expanduser(str(value or "").strip().strip('"')))


def _season_count(season_path: str) -> int:
    try:
        return len(
            [
                item
                for item in os.listdir(season_path)
                if os.path.isfile(os.path.join(season_path, item)) and is_video_file(item)
            ]
        )
    except OSError:
        return 0


def _season_status(target_path: str) -> str:
    if target_path in {"BROKEN LINK", "ACCESS DENIED", "NO_SYMLINKS", "EMPTY"}:
        return "broken"
    return "ok"


def _movie_payload(movie: Tuple[str, str, str]) -> Dict[str, Any]:
    name, symlink_path, target_path = movie
    library_path = os.path.dirname(symlink_path) if os.path.isfile(symlink_path) or os.path.islink(symlink_path) else symlink_path
    status = "ok" if os.path.islink(symlink_path) and target_path not in {"BROKEN LINK", "NO_SYMLINKS"} else "broken"
    return {
        "name": name,
        "path": library_path,
        "symlink_path": symlink_path,
        "target_path": target_path,
        "status": status,
    }


def _grouped_media_payload(item: Tuple[str, List[Tuple[str, str, str]]]) -> Dict[str, Any]:
    name, seasons = item
    library_path = os.path.dirname(seasons[0][1]) if seasons else ""
    return {
        "name": name,
        "path": library_path,
        "seasons": [
            {
                "name": season_name,
                "path": season_path,
                "target_path": target_path,
                "status": _season_status(target_path),
                "episode_count": _season_count(season_path),
            }
            for season_name, season_path, target_path in seasons
        ],
    }


def _extract_infohash_from_link(torrent_link: str) -> str:
    parsed = urlparse(str(torrent_link or "").strip())
    if parsed.scheme.lower() != "magnet":
        return ""
    for xt_value in parse_qs(parsed.query).get("xt", []):
        xt_value = str(xt_value or "").strip()
        if xt_value.lower().startswith("urn:btih:"):
            return xt_value.split(":")[-1].strip()
    return ""


def _is_same_or_child_path(path: str, parent: str) -> bool:
    try:
        normalized_path = os.path.normcase(os.path.abspath(path))
        normalized_parent = os.path.normcase(os.path.abspath(parent))
        return os.path.commonpath([normalized_path, normalized_parent]) == normalized_parent
    except (OSError, ValueError):
        return False


def _library_roots_for_kind(kind: str) -> List[str]:
    if kind == "movies":
        return MEDIA_FOLDERS
    if kind == "anime":
        return [ANIME_FOLDER]
    if kind == "series":
        return [SERIES_FOLDER]
    return []


def _resolve_symlink_target(path: str) -> str:
    try:
        target = os.readlink(path)
    except OSError:
        return ""
    if os.path.isabs(target):
        return os.path.abspath(target)
    return os.path.abspath(os.path.join(os.path.dirname(path), target))


def _load_track_file(path: str) -> Dict[str, Any]:
    candidates = []
    if os.path.isdir(path):
        candidates.append(os.path.join(path, "track.json"))
    candidates.append(os.path.join(os.path.dirname(path), "track.json"))
    for candidate in candidates:
        try:
            if os.path.isfile(candidate):
                with open(candidate, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _delete_path(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.isdir(path) and os.path.islink(path):
        os.rmdir(path)
    else:
        os.remove(path)


def _find_new_torrent_hash(
    before_hashes: set,
    after_torrents: List[Dict[str, Any]],
    torrent_url: str,
    name_hint: str = "",
) -> str:
    direct_hash = _extract_infohash_from_link(torrent_url)
    if INFOHASH_PATTERN.fullmatch(direct_hash):
        return direct_hash

    candidate_links = {str(torrent_url or "").strip()}
    new_torrents = [
        torrent
        for torrent in after_torrents
        if str(torrent.get("hash", "") or "").strip().lower() not in before_hashes
    ]
    for torrent in new_torrents:
        magnet = str(torrent.get("magnet_uri", "") or "")
        comment = str(torrent.get("comment", "") or "")
        if any(link and link in f"{magnet}\n{comment}" for link in candidate_links):
            return str(torrent.get("hash", "") or "").strip()

    normalized_name_hint = name_hint.strip().lower()
    if normalized_name_hint:
        exact_matches = [
            torrent
            for torrent in new_torrents
            if str(torrent.get("name", "") or "").strip().lower() == normalized_name_hint
        ]
        if len(exact_matches) == 1:
            return str(exact_matches[0].get("hash", "") or "").strip()

    if len(new_torrents) == 1:
        return str(new_torrents[0].get("hash", "") or "").strip()

    # qBittorrent may already have the torrent, or may accept the add before it
    # appears as a new row. Fall back to unique full-list matches so repeated
    # Add clicks can still create the tracking row needed by auto-add.
    for torrent in after_torrents:
        magnet = str(torrent.get("magnet_uri", "") or "")
        comment = str(torrent.get("comment", "") or "")
        if any(link and link in f"{magnet}\n{comment}" for link in candidate_links):
            return str(torrent.get("hash", "") or "").strip()

    if normalized_name_hint:
        exact_matches = [
            torrent
            for torrent in after_torrents
            if str(torrent.get("name", "") or "").strip().lower() == normalized_name_hint
        ]
        if len(exact_matches) == 1:
            return str(exact_matches[0].get("hash", "") or "").strip()
    return ""


def _wait_for_torrent_hash(session: Any, before_hashes: set, torrent_url: str, title: str) -> str:
    for attempt in range(8):
        infohash = _find_new_torrent_hash(before_hashes, qb_get_torrent_info(session), torrent_url, title)
        if INFOHASH_PATTERN.fullmatch(infohash or ""):
            return infohash
        if attempt < 7:
            time.sleep(0.75)
    return ""


class JellyfinApi:
    """Route handlers for the HTTP API."""

    def __init__(self):
        self.imdb = IMDBAPI()
        self.torrent_manager = TorrentManager()
        self._qb_search_session = None
        self._qb_search_session_lock = threading.RLock()

    def handle(self, method: str, path: str, query: Dict[str, List[str]], payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        segments = [segment for segment in path.strip("/").split("/") if segment]
        if segments == [] or segments == ["api"]:
            return _ok(self._route_index())
        if not segments or segments[0] != "api":
            raise ApiError(404, "Unknown route")

        route = segments[1:]
        if method == "GET":
            return self._handle_get(route, query)
        if method == "POST":
            return self._handle_post(route, query, payload)
        if method == "DELETE":
            return self._handle_delete(route, query)
        raise ApiError(405, "Method not allowed")

    def _route_index(self) -> Dict[str, Any]:
        return {
            "name": "Jellyfin Library Manager API",
            "version": 1,
            "routes": [
                "GET /api/health",
                "GET /api/config",
                "GET /api/library/movies",
                "POST /api/library/movies",
                "DELETE /api/library/movies?path=...",
                "GET /api/library/anime",
                "POST /api/library/anime",
                "DELETE /api/library/anime?path=...",
                "GET /api/library/series",
                "POST /api/library/series",
                "DELETE /api/library/series?path=...",
                "GET /api/torrents/tracked",
                "POST /api/torrents/sync",
                "POST /api/torrents/auto-add",
                "DELETE /api/torrents/{infohash}",
                "GET /api/qbittorrent/status",
                "GET /api/qbittorrent/torrents",
                "POST /api/qbittorrent/torrents",
                "GET /api/qbittorrent/torrents/{infohash}/files",
                "GET /api/qbittorrent/search/plugins",
                "POST /api/qbittorrent/search",
                "GET /api/qbittorrent/search/{id}/status",
                "GET /api/qbittorrent/search/{id}/results",
                "DELETE /api/qbittorrent/search/{id}",
                "GET /api/search/anime?q=...",
                "GET /api/search/movies?q=...",
                "GET /api/search/series?q=...",
                "GET /api/search/nyaa?q=...",
                "GET /api/search/nyaa/files?url=...",
            ],
        }

    def _handle_get(self, route: List[str], query: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
        if route == ["health"]:
            return _ok({"status": "ok", "qbittorrent_accessible": qb_check_connection()})
        if route == ["config"]:
            return _ok(
                {
                    "media_folders": MEDIA_FOLDERS,
                    "anime_folder": ANIME_FOLDER,
                    "series_folder": SERIES_FOLDER,
                    "qbittorrent_host": QBITTORRENT_HOST,
                }
            )
        if route == ["library", "movies"]:
            return _ok([_movie_payload(movie) for movie in list_movies()])
        if route == ["library", "anime"]:
            return _ok([_grouped_media_payload(item) for item in list_anime()])
        if route == ["library", "series"]:
            return _ok([_grouped_media_payload(item) for item in list_series()])
        if route == ["torrents", "tracked"]:
            return _ok(get_tracked_torrents())
        if route == ["qbittorrent", "status"]:
            return _ok({"accessible": qb_check_connection()})
        if route == ["qbittorrent", "torrents"]:
            session = self._qb_session()
            return _ok(qb_get_torrent_info(session))
        if len(route) == 4 and route[:2] == ["qbittorrent", "torrents"] and route[3] == "files":
            session = self._qb_session()
            return _ok(qb_get_torrent_files(session, route[2]))
        if route == ["qbittorrent", "search", "plugins"]:
            session = self._qb_session()
            return _ok(qb_get_search_plugins(session))
        if len(route) == 4 and route[:2] == ["qbittorrent", "search"] and route[3] == "status":
            session = self._get_qb_search_session()
            return _ok(qb_get_search_status(session, int(route[2])))
        if len(route) == 4 and route[:2] == ["qbittorrent", "search"] and route[3] == "results":
            session = self._get_qb_search_session()
            limit = _normalize_limit(self._first(query, "limit", 100), default=100, maximum=500)
            offset = _normalize_int(self._first(query, "offset", 0), default=0, minimum=0, maximum=100000)
            return _ok(qb_get_search_results(session, int(route[2]), limit=limit, offset=offset))
        if route == ["search", "anime"]:
            q = self._required_query(query, "q")
            limit = _normalize_limit(self._first(query, "limit", 10), default=10, maximum=50)
            results = anilist_search(q, limit=limit)
            if isinstance(results, str):
                raise ApiError(502, results)
            return _ok([{"title": title, "year": year, "id": anilist_id} for title, year, anilist_id in results])
        if route == ["search", "movies"]:
            q = self._required_query(query, "q")
            limit = _normalize_limit(self._first(query, "limit", 15), default=15, maximum=50)
            return _ok(self.imdb.search_movies(q, limit=limit))
        if route == ["search", "series"]:
            q = self._required_query(query, "q")
            limit = _normalize_limit(self._first(query, "limit", 15), default=15, maximum=50)
            return _ok(self.imdb.search_series(q, limit=limit))
        if route == ["search", "nyaa"]:
            q = self._required_query(query, "q")
            limit = _normalize_limit(self._first(query, "limit", 50), default=50, maximum=100)
            sort_by = str(self._first(query, "sort", "seeds") or "seeds")
            results = nyaa_rss_search(q, limit=limit)
            if isinstance(results, str):
                raise ApiError(502, results)
            return _ok(sort_torrents(results, sort_by))
        if route == ["search", "nyaa", "files"]:
            url = self._required_query(query, "url")
            return _ok(get_torrent_file_list(url))
        raise ApiError(404, "Unknown route")

    def _handle_post(self, route: List[str], query: Dict[str, List[str]], payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if route == ["library", "movies"]:
            return self._add_movie(payload)
        if route == ["library", "anime"]:
            return self._add_anime(payload)
        if route == ["library", "series"]:
            return self._add_series(payload)
        if route == ["torrents", "sync"]:
            torrents, error = sync_torrents_with_qbittorrent()
            if error:
                raise ApiError(502, error)
            return _ok(torrents or [])
        if route == ["torrents", "auto-add"]:
            if _bool_query(self._first(query, "details"), default=False):
                report = self.torrent_manager.auto_add_completed_torrents_report()
                import_failures = [
                    skipped
                    for skipped in report.get("skipped", [])
                    if str(skipped.get("reason", "")).lower().startswith(("could not create", "error adding", "existing movie library entry"))
                ]
                if import_failures:
                    raise ApiError(500, import_failures[0].get("reason", "Library import failed"), {"auto_add": report})
                return _ok(report)
            report = self.torrent_manager.auto_add_completed_torrents_report()
            import_failures = [
                skipped
                for skipped in report.get("skipped", [])
                if str(skipped.get("reason", "")).lower().startswith(("could not create", "error adding", "existing movie library entry"))
            ]
            if import_failures:
                raise ApiError(500, import_failures[0].get("reason", "Library import failed"), {"auto_add": report})
            return _ok(report.get("added", []))
        if route == ["qbittorrent", "torrents"]:
            return self._add_qbittorrent_torrent(payload)
        if route == ["qbittorrent", "search"]:
            session = self._get_qb_search_session()
            pattern = _required_str(payload, "pattern")
            category = str(payload.get("category", "all") or "all")
            plugins = str(payload.get("plugins", "enabled") or "enabled")
            search_id = qb_start_search(session, pattern, category=category, plugins=plugins)
            if search_id is None:
                raise ApiError(502, "Failed to start qBittorrent search")
            return _ok({"id": search_id}, status=201)
        raise ApiError(404, "Unknown route")

    def _handle_delete(self, route: List[str], query: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
        if len(route) == 2 and route[0] == "library" and route[1] in {"movies", "anime", "series"}:
            return self._delete_library_media(route[1], query)
        if len(route) == 2 and route[0] == "torrents":
            return self._delete_torrent(route[1], query)
        if len(route) == 3 and route[:2] == ["qbittorrent", "search"]:
            session = self._get_qb_search_session()
            if not qb_delete_search(session, int(route[2])):
                raise ApiError(502, "Failed to delete qBittorrent search")
            return _ok({"deleted": True})
        raise ApiError(404, "Unknown route")

    def _delete_library_media(self, kind: str, query: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
        target_path = _as_abs_path(self._required_query(query, "path"))
        roots = [os.path.abspath(root) for root in _library_roots_for_kind(kind) if root]
        if not roots or not any(_is_same_or_child_path(target_path, root) for root in roots):
            raise ApiError(400, "Path is outside the configured library folders")
        if not os.path.lexists(target_path):
            raise ApiError(404, "Library path does not exist")

        delete_source = _bool_query(self._first(query, "delete_source"), default=False)
        tracking_payload = _load_track_file(target_path)
        infohashes = set()
        source_paths = []

        def add_source(path_value: Any) -> None:
            raw_path = str(path_value or "").strip().strip('"')
            if not raw_path or raw_path.lower() in {"default", "unknown", "n/a"}:
                return
            source_path = _as_abs_path(raw_path)
            if source_path and source_path not in source_paths:
                source_paths.append(source_path)

        if os.path.islink(target_path):
            add_source(_resolve_symlink_target(target_path))

        if os.path.isdir(target_path):
            for root, dirs, files in os.walk(target_path):
                for folder_name in list(dirs):
                    link_path = os.path.join(root, folder_name)
                    if os.path.islink(link_path):
                        add_source(_resolve_symlink_target(link_path))
                for file_name in files:
                    link_path = os.path.join(root, file_name)
                    if os.path.islink(link_path):
                        add_source(_resolve_symlink_target(link_path))

        track_infohash = str(tracking_payload.get("infohash", "") or "").strip().lower()
        if INFOHASH_PATTERN.fullmatch(track_infohash):
            infohashes.add(track_infohash)
        add_source(tracking_payload.get("source_download_path") or tracking_payload.get("download_path"))
        add_source(tracking_payload.get("qb_content_path"))

        for torrent in get_tracked_torrents():
            library_path = _as_abs_path(str(torrent.get("library_path", "") or ""))
            if library_path and (_is_same_or_child_path(library_path, target_path) or _is_same_or_child_path(target_path, library_path)):
                torrent_infohash = str(torrent.get("infohash", "") or "").strip().lower()
                if INFOHASH_PATTERN.fullmatch(torrent_infohash):
                    infohashes.add(torrent_infohash)
                add_source(torrent.get("source_download_path") or torrent.get("download_path"))
                add_source(torrent.get("qb_content_path"))

        if delete_source and not infohashes and source_paths:
            session = self._qb_session()
            for qb_torrent in qb_get_torrent_info(session):
                torrent_hash = str(qb_torrent.get("hash", "") or "").strip().lower()
                if not INFOHASH_PATTERN.fullmatch(torrent_hash):
                    continue
                qb_paths = [
                    qb_torrent.get("content_path"),
                    qb_torrent.get("root_path"),
                ]
                save_path = str(qb_torrent.get("save_path", "") or "").strip()
                name = str(qb_torrent.get("name", "") or "").strip()
                if save_path and name:
                    qb_paths.append(os.path.join(save_path, name))
                normalized_qb_paths = [_as_abs_path(str(path or "")) for path in qb_paths if str(path or "").strip()]
                if any(
                    _is_same_or_child_path(source_path, qb_path) or _is_same_or_child_path(qb_path, source_path)
                    for source_path in source_paths
                    for qb_path in normalized_qb_paths
                ):
                    infohashes.add(torrent_hash)

        deleted_sources = []
        skipped_sources = []
        removed_from_qbittorrent = []
        if delete_source:
            if infohashes:
                session = self._qb_session()
                qb_torrents_by_hash = {
                    str(qb_torrent.get("hash", "") or "").strip().lower(): qb_torrent
                    for qb_torrent in qb_get_torrent_info(session)
                    if str(qb_torrent.get("hash", "") or "").strip()
                }
                for infohash in sorted(infohashes):
                    qb_torrent = qb_torrents_by_hash.get(infohash)
                    if not qb_torrent:
                        raise ApiError(404, "Tracked torrent was not found in qBittorrent", {"infohash": infohash})
                    add_source(qb_torrent.get("content_path"))
                    add_source(qb_torrent.get("root_path"))
                    save_path = str(qb_torrent.get("save_path", "") or "").strip()
                    name = str(qb_torrent.get("name", "") or "").strip()
                    if save_path and name:
                        add_source(os.path.join(save_path, name))
                    if not qb_remove_torrent(session, infohash, delete_files=True):
                        raise ApiError(502, "Failed to remove torrent from qBittorrent", {"infohash": infohash})
                    removed_from_qbittorrent.append(infohash)

            for source_path in ([] if removed_from_qbittorrent else source_paths):
                if not os.path.exists(source_path):
                    skipped_sources.append({"path": source_path, "reason": "not found"})
                    continue
                if any(_is_same_or_child_path(source_path, root) for root in roots):
                    skipped_sources.append({"path": source_path, "reason": "inside library folder"})
                    continue
                try:
                    _delete_path(source_path)
                    deleted_sources.append(source_path)
                except OSError as exc:
                    raise ApiError(500, "Failed to delete source from disk", {"path": source_path, "error": str(exc)})

        try:
            _delete_path(target_path)
        except OSError as exc:
            raise ApiError(500, "Failed to delete library media", {"path": target_path, "error": str(exc)})

        removed_from_database = 0
        for infohash in sorted(infohashes):
            removed_from_database += remove_torrent_from_database_by_infohash(infohash)

        return _ok(
            {
                "deleted_library_path": target_path,
                "delete_source": delete_source,
                "removed_from_qbittorrent": removed_from_qbittorrent,
                "deleted_sources": deleted_sources,
                "skipped_sources": skipped_sources,
                "removed_from_database": removed_from_database,
            }
        )

    def _add_movie(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        movie_path = _as_abs_path(_required_str(payload, "path"))
        overwrite = bool(payload.get("overwrite", False))
        if not os.path.isfile(movie_path) or not is_video_file(movie_path):
            raise ApiError(400, "Path must be an existing supported video file")

        existing_symlink, existing_subfolder = find_existing_symlink(movie_path, MEDIA_FOLDERS)
        if existing_symlink and not overwrite:
            raise ApiError(
                409,
                "Movie already exists",
                {"symlink_path": existing_symlink, "folder": existing_subfolder},
            )
        if existing_subfolder and overwrite:
            shutil.rmtree(existing_subfolder, ignore_errors=True)

        success, result = create_movie_symlink(movie_path, get_media_folder(movie_path))
        if not success:
            raise ApiError(500, "Failed to create movie symlink", {"error": result})
        return _ok({"symlink_path": result, "source_path": movie_path}, status=201)

    def _add_anime(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        return self._add_episodic_media(payload, media_type="anime")

    def _add_series(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        return self._add_episodic_media(payload, media_type="series")

    def _add_episodic_media(self, payload: Dict[str, Any], media_type: str) -> Tuple[int, Dict[str, Any]]:
        source_path = _as_abs_path(_required_str(payload, "source_path"))
        name = _required_str(payload, "name")
        overwrite = bool(payload.get("overwrite", False))
        try:
            season_number = int(payload.get("season_number", 1) or 1)
        except (TypeError, ValueError):
            raise ApiError(400, "season_number must be an integer")
        if season_number <= 0:
            raise ApiError(400, "season_number must be positive")
        if not os.path.isdir(source_path):
            raise ApiError(400, "source_path must be an existing folder")

        base_folder = ANIME_FOLDER if media_type == "anime" else SERIES_FOLDER
        target_folder = os.path.join(base_folder, name, f"Season {season_number:02d}")
        if os.path.exists(target_folder) and not overwrite:
            raise ApiError(409, f"{media_type} season already exists", {"path": target_folder})
        if os.path.exists(target_folder) and overwrite:
            shutil.rmtree(target_folder, ignore_errors=True)

        if media_type == "anime":
            success, result, episode_count, extras_count = create_anime_symlinks(source_path, name, season_number)
        else:
            success, result, episode_count, extras_count = create_series_symlinks(source_path, name, season_number)
        if not success:
            raise ApiError(500, f"Failed to create {media_type} symlinks", {"error": result})
        return _ok(
            {
                "path": result,
                "source_path": source_path,
                "episode_count": episode_count,
                "extras_count": extras_count,
            },
            status=201,
        )

    def _add_qbittorrent_torrent(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        torrent_url = _required_str(payload, "url")
        download_path = payload.get("download_path")
        if download_path:
            download_path = _as_abs_path(str(download_path))
            if not os.path.isdir(download_path):
                raise ApiError(400, "download_path must be an existing folder")

        session = self._qb_session()
        before_hashes = {
            str(torrent.get("hash", "") or "").strip().lower()
            for torrent in qb_get_torrent_info(session)
            if str(torrent.get("hash", "") or "").strip()
        }
        title = str(payload.get("title", "") or "").strip()
        added_to_qb = qb_add_torrent(session, torrent_url, download_path)
        infohash = _wait_for_torrent_hash(session, before_hashes, torrent_url, title)
        if not added_to_qb and not INFOHASH_PATTERN.fullmatch(infohash or ""):
            raise ApiError(502, "Failed to add torrent to qBittorrent")
        tracked = False
        torrent_id = None
        if bool(payload.get("track", True)) and INFOHASH_PATTERN.fullmatch(infohash or ""):
            media_metadata = payload.get("media_metadata") or payload.get("metadata") or {}
            torrent_info = {
                "title": title or payload.get("name") or "Unknown",
                "size": str(payload.get("size", "Unknown")),
                "seeds": int(payload.get("seeds", 0) or 0),
                "leechers": int(payload.get("leechers", 0) or 0),
                "downloads": int(payload.get("downloads", 0) or 0),
                "infohash": infohash,
                "category": str(payload.get("category", "API") or "API"),
                "link": torrent_url,
                "download_path": download_path or "Default",
                "source_download_path": download_path or "Default",
                "library_path": "",
                "media_type": str(payload.get("media_type", "unknown") or "unknown"),
                "media_metadata": media_metadata,
                "anilist_info": media_metadata if str(payload.get("media_type", "")) == "anime" else {},
            }
            torrent_id = add_torrent_to_database(torrent_info)
            tracked = torrent_id is not None

        return _ok(
            {
                "added": True,
                "tracked": tracked,
                "torrent_id": torrent_id,
                "infohash": infohash or None,
            },
            status=201,
        )

    def _delete_torrent(self, infohash: str, query: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
        normalized_hash = str(infohash or "").strip().lower()
        if not INFOHASH_PATTERN.fullmatch(normalized_hash):
            raise ApiError(400, "Invalid infohash")

        delete_files = _bool_query(self._first(query, "delete_files"), default=False)
        delete_library = _bool_query(self._first(query, "delete_library"), default=False)
        session = self._qb_session()
        matching_torrents = [
            torrent
            for torrent in get_tracked_torrents()
            if str(torrent.get("infohash", "") or "").strip().lower() == normalized_hash
        ]
        if delete_library and not matching_torrents:
            raise ApiError(404, "Tracked torrent was not found")

        normalized_library_paths = {
            os.path.normcase(os.path.abspath(str(torrent.get("library_path", "") or "").strip()))
            for torrent in matching_torrents
            if str(torrent.get("library_path", "") or "").strip()
        }
        if delete_library and len(normalized_library_paths) > 1:
            raise ApiError(409, "Duplicate torrent tracking rows reference different library paths")

        def tracked_row_priority(torrent: Dict[str, Any]) -> Tuple[int, int]:
            has_library_path = 1 if str(torrent.get("library_path", "") or "").strip() else 0
            try:
                torrent_id = int(torrent.get("id", 0))
            except (TypeError, ValueError):
                torrent_id = 0
            return has_library_path, torrent_id

        matching_torrent = max(matching_torrents, key=tracked_row_priority) if matching_torrents else None
        cleanup_retry = bool(
            matching_torrent
            and str(matching_torrent.get("status", "") or "").lower() == "deletion_pending"
        )

        additional_source_paths = []
        cleanup_plan = None
        qb_torrent = None
        if delete_library and matching_torrent:
            qb_torrent = next(
                (
                    torrent
                    for torrent in qb_get_torrent_info(session)
                    if str(torrent.get("hash", "") or "").strip().lower() == normalized_hash
                ),
                None,
            )
            if qb_torrent:
                content_path = str(qb_torrent.get("content_path", "") or "").strip()
                if content_path:
                    additional_source_paths.append(content_path)
                else:
                    save_path = str(qb_torrent.get("save_path", "") or "").strip()
                    torrent_name = str(qb_torrent.get("name", "") or "").strip()
                    if save_path and torrent_name:
                        additional_source_paths.append(os.path.join(save_path, torrent_name))
            if not additional_source_paths:
                for tracked_torrent in matching_torrents:
                    additional_source_paths.extend([
                        tracked_torrent.get("source_download_path"),
                        tracked_torrent.get("download_path"),
                        tracked_torrent.get("qb_content_path"),
                    ])
            try:
                cleanup_plan = self.torrent_manager.plan_torrent_library_cleanup(
                    matching_torrent,
                    additional_source_paths=additional_source_paths,
                )
            except ValueError as exc:
                raise ApiError(400, str(exc)) from exc
            except OSError as exc:
                raise ApiError(500, "Could not inspect related library files", {"error": str(exc)}) from exc

            was_imported = any(
                str(tracked_torrent.get("status", "") or "").lower() == "added_to_library"
                or bool(str(tracked_torrent.get("library_path", "") or "").strip())
                for tracked_torrent in matching_torrents
            )
            planned_library_path = str(cleanup_plan.get("library_path", "") or "")
            if (
                was_imported
                and planned_library_path
                and os.path.lexists(planned_library_path)
                and not cleanup_plan.get("linked_paths")
                and not cleanup_retry
            ):
                raise ApiError(409, "No related library links were found; torrent was not deleted")

        status_marked_for_cleanup = False
        previous_status = ""
        if delete_library and matching_torrent and cleanup_plan and cleanup_plan.get("library_path"):
            previous_status = str(matching_torrent.get("status", "") or "")
            if cleanup_retry:
                status_marked_for_cleanup = True
            else:
                torrent_id = matching_torrent.get("id")
                if torrent_id is None or not update_torrent_status(torrent_id, "deletion_pending"):
                    raise ApiError(500, "Could not mark torrent for library cleanup")
                status_marked_for_cleanup = True

        removed_from_qb = qb_remove_torrent(session, normalized_hash, delete_files=delete_files)
        if not removed_from_qb:
            if status_marked_for_cleanup and not cleanup_retry:
                update_torrent_status(matching_torrent.get("id"), previous_status)
            raise ApiError(502, "Failed to remove torrent from qBittorrent")

        library_cleanup = None
        if delete_library and matching_torrent:
            library_cleanup = self.torrent_manager.remove_torrent_library_files(
                matching_torrent,
                additional_source_paths=additional_source_paths,
                cleanup_plan=cleanup_plan,
            )
            if not library_cleanup.get("success"):
                raise ApiError(
                    500,
                    "Torrent was removed from qBittorrent, but related library files could not be removed",
                    {"library_cleanup": library_cleanup},
                )

        removed_from_database = remove_torrent_from_database_by_infohash(normalized_hash)

        return _ok(
            {
                "removed_from_qbittorrent": removed_from_qb,
                "removed_from_database": removed_from_database,
                "removed_library": bool(library_cleanup and (
                    library_cleanup.get("removed_links")
                    or library_cleanup.get("removed_sidecars")
                    or library_cleanup.get("removed_library_root")
                )),
                "library_cleanup": library_cleanup,
                "delete_files": delete_files,
            }
        )

    def _qb_session(self):
        session = qb_login()
        if not session:
            raise ApiError(502, "Failed to authenticate with qBittorrent")
        return session

    def _get_qb_search_session(self):
        # qBittorrent search jobs are scoped to the web session that created them.
        with self._qb_search_session_lock:
            if self._qb_search_session is None:
                self._qb_search_session = qb_login()
            if not self._qb_search_session:
                self._qb_search_session = None
                raise ApiError(502, "Failed to authenticate with qBittorrent")
            return self._qb_search_session

    @staticmethod
    def _first(query: Dict[str, List[str]], key: str, default: Any = None) -> Any:
        values = query.get(key)
        if not values:
            return default
        return values[0]

    def _required_query(self, query: Dict[str, List[str]], key: str) -> str:
        value = str(self._first(query, key, "") or "").strip()
        if not value:
            raise ApiError(400, f"Missing required query parameter: {key}")
        return value


class ApiRequestHandler(BaseHTTPRequestHandler):
    """HTTP request adapter."""

    api = JellyfinApi()

    def do_OPTIONS(self) -> None:
        self._send_json(204, None)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        try:
            parsed = urlparse(self.path)
            payload = self._read_json_body() if method in {"POST", "DELETE"} else {}
            status, response = self.api.handle(method, parsed.path, parse_qs(parsed.query), payload)
            self._send_json(status, response)
        except ApiError as exc:
            body = {"ok": False, "error": exc.message}
            if exc.details:
                body["details"] = exc.details
            self._send_json(exc.status_code, body)
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": "Internal server error", "details": {"error": str(exc)}})

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "Request body too large")
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            raise ApiError(400, "Request body must be valid JSON")
        if not isinstance(payload, dict):
            raise ApiError(400, "Request body must be a JSON object")
        return payload

    def _send_json(self, status: int, body: Optional[Dict[str, Any]]) -> None:
        if body is None:
            data = b""
        else:
            data = json.dumps(body, indent=2, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer((host, port), ApiRequestHandler)
    print(f"Jellyfin Library Manager API listening on http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Jellyfin Library Manager HTTP API")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port (default: {DEFAULT_PORT})")
    args = parser.parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
