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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from anilist_api import anilist_search
from config import ANIME_FOLDER, MEDIA_FOLDERS, QBITTORRENT_HOST, SERIES_FOLDER
from database import (
    add_torrent_to_database,
    get_tracked_torrents,
    remove_torrent_from_database_by_infohash,
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
    return {
        "name": name,
        "symlink_path": symlink_path,
        "target_path": target_path,
        "status": "broken" if target_path == "BROKEN LINK" else "ok",
    }


def _grouped_media_payload(item: Tuple[str, List[Tuple[str, str, str]]]) -> Dict[str, Any]:
    name, seasons = item
    return {
        "name": name,
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
                "GET /api/library/anime",
                "POST /api/library/anime",
                "GET /api/library/series",
                "POST /api/library/series",
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
            return _ok(auto_add_completed_torrents())
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
        if len(route) == 2 and route[0] == "torrents":
            return self._delete_torrent(route[1], query)
        if len(route) == 3 and route[:2] == ["qbittorrent", "search"]:
            session = self._get_qb_search_session()
            if not qb_delete_search(session, int(route[2])):
                raise ApiError(502, "Failed to delete qBittorrent search")
            return _ok({"deleted": True})
        raise ApiError(404, "Unknown route")

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
        if not qb_add_torrent(session, torrent_url, download_path):
            raise ApiError(502, "Failed to add torrent to qBittorrent")

        after_torrents = qb_get_torrent_info(session)
        title = str(payload.get("title", "") or "").strip()
        infohash = _find_new_torrent_hash(before_hashes, after_torrents, torrent_url, title)
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
        removed_from_qb = qb_remove_torrent(session, normalized_hash, delete_files=delete_files)
        if not removed_from_qb:
            raise ApiError(502, "Failed to remove torrent from qBittorrent")

        removed_from_database = 0
        removed_library = False
        matching_torrent = next(
            (torrent for torrent in get_tracked_torrents() if str(torrent.get("infohash", "")).lower() == normalized_hash),
            None,
        )
        if delete_library and matching_torrent:
            removed_library = self.torrent_manager.remove_torrent_and_library_entry(matching_torrent)
            removed_from_database = 1 if removed_library else 0
        else:
            removed_from_database = remove_torrent_from_database_by_infohash(normalized_hash)

        return _ok(
            {
                "removed_from_qbittorrent": removed_from_qb,
                "removed_from_database": removed_from_database,
                "removed_library": removed_library,
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
