
import descarca_saptamana
import csv
import json
import mimetypes
import os
import re
import threading
import time
import traceback
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import country_top_200


ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / "Music_Library"
OUTPUT = ROOT / "output"
DOWNLOADS = Path.home() / "Downloads"
JOBS = {}
JOBS_LOCK = threading.Lock()
JOB_CANCEL_EVENTS = {}
COUNTRY_CACHE = {}
COUNTRY_CACHE_TTL = 15 * 60
COUNTRY_CACHE_LOCK = threading.Lock()
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")


def clean_name(value):
    return re.sub(r'[<>:"/\\|?*]', "", str(value)).strip()


def read_tracks():
    filename = OUTPUT / "top_200_clean.csv"
    if not filename.exists():
        return []
    with filename.open("r", encoding="utf-8-sig", newline="") as file:
        rows = csv.DictReader(file)
        return [
            {"artist": (row.get("artist") or "").strip(),
             "track": (row.get("track") or "").strip()}
            for row in rows
            if (row.get("artist") or "").strip()
            and (row.get("track") or "").strip()
        ]


def library_preview(artist, track):
    expected = f"{clean_name(artist)} - {clean_name(track)}".casefold()
    for path in LIBRARY.glob("*"):
        if path.is_file() and expected in path.stem.casefold():
            return f"/library/{path.name}"
    return None

def ensure_preview(artist, track):
    existing = library_preview(artist, track)

    if existing:
        return existing

    LIBRARY.mkdir(parents=True, exist_ok=True)

    result = descarca_saptamana.descarca_melodie(
        1,
        artist,
        track,
    )

    if not result:
        raise RuntimeError(
            "Preview could not be downloaded for this track."
        )

    preview = library_preview(artist, track)

    if not preview:
        raise RuntimeError(
            "Preview file was downloaded but could not be found."
        )

    return preview

def serialize_tracks(tracks):
    result = []
    for position, track in enumerate(tracks, start=1):
        if isinstance(track, dict):
            artist = track["artist"]
            title = track["track"]
            spotify_id = track.get("spotify_id")
        else:
            artist = track.artist
            title = track.title
            spotify_id = track.spotify_id
        result.append({
            "position": position,
            "artist": artist,
            "track": title,
            "spotify_id": spotify_id,
            "preview_url": library_preview(artist, title),
            "spotify_url": (
                f"https://open.spotify.com/track/{spotify_id}"
                if spotify_id else None
            ),
        })
    return result


def set_job(job_id, **values):
    with JOBS_LOCK:
        JOBS.setdefault(job_id, {}).update(values)


def run_week_download(
    job_id,
    country,
    selected_tracks=None,
    organize_by_day=False,
):
    try:
        import descarca_saptamana

        def update_progress(done, total, phase):
            if JOB_CANCEL_EVENTS[job_id].is_set():
                raise RuntimeError("Descărcarea a fost oprită de utilizator.")
            set_job(
                job_id,
                phase=phase,
                done=done,
                total=total,
                progress=round(done / total * 100) if total else 0,
            )

        if selected_tracks:
            songs = selected_tracks
        else:
            tracks = country_top_200.generate_country_tracks(country)
            songs = [
                {"artist": track.artist, "track": track.title}
                for track in tracks
            ]
        downloaded = descarca_saptamana.descarca_toate(
            songs,
            progress_callback=update_progress,
            cancel_event=JOB_CANCEL_EVENTS[job_id],
        )
        if not downloaded:
            raise RuntimeError("Nu a fost descărcată nicio melodie.")
        if JOB_CANCEL_EVENTS[job_id].is_set():
            set_job(job_id, status="cancelled", phase="cancelled")
            return
        if organize_by_day:
            week_tracks = descarca_saptamana.genereaza_saptamana(
                downloaded
            )
            descarca_saptamana.creeaza_zip(
                week_tracks,
                progress_callback=update_progress,
            )
        else:
            descarca_saptamana.creeaza_zip_simplu(
                downloaded,
                progress_callback=update_progress,
            )
        archive = Path(descarca_saptamana.NUME_ZIP)
        set_job(
            job_id,
            status="done",
            archive=str(archive),
            downloaded=len(downloaded),
            phase="done",
            done=len(downloaded),
            total=len(downloaded),
            progress=100,
        )
    except Exception as error:
        if JOB_CANCEL_EVENTS[job_id].is_set():
            set_job(job_id, status="cancelled", phase="cancelled")
            return
        traceback.print_exc()
        set_job(job_id, status="error", error=str(error))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format_string, *args):
        print(f"[web] {self.address_string()} - {format_string % args}")

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path == "/api/country":
                country = country_top_200.normalize_country(
                    query.get("country", ["ro"])[0]
                )
                now = time.time()
                with COUNTRY_CACHE_LOCK:
                    cached = COUNTRY_CACHE.get(country)
                if cached and now - cached["created_at"] < COUNTRY_CACHE_TTL:
                    tracks = cached["tracks"]
                else:
                    tracks = country_top_200.generate_country_tracks(country)
                    with COUNTRY_CACHE_LOCK:
                        COUNTRY_CACHE[country] = {
                            "created_at": now,
                            "tracks": tracks,
                        }
                self.send_json({
                    "country": country,
                    "tracks": serialize_tracks(tracks),
                })
                return
            if path == "/api/preview":
                artist = query.get("artist", [""])[0]
                track = query.get("track", [""])[0]
                if not artist or not track:
                    self.send_json({"error": "Parametrii lipsă."}, 400)
                    return
                preview_url = ensure_preview(artist, track)
                self.send_json({"preview_url": preview_url})
                return
            if path == "/api/current":
                self.send_json({"tracks": serialize_tracks(read_tracks())})
                return
            if path == "/api/download-top-clean":
                csv_file = OUTPUT / "top_200_clean.csv"
                if not csv_file.is_file():
                    self.send_json(
                        {"error": "Fișierul top_200_clean.csv nu există încă."},
                        404,
                    )
                    return
                self.send_file(
                    csv_file,
                    "text/csv; charset=utf-8",
                    "top_200_clean.csv",
                )
                return
            if path == "/api/download-status":
                job_id = query.get("job", [""])[0]
                with JOBS_LOCK:
                    job = dict(JOBS.get(job_id, {"status": "missing"}))
                self.send_json(job)
                return
            if path == "/api/download-file":
                job_id = query.get("job", [""])[0]
                with JOBS_LOCK:
                    job = dict(JOBS.get(job_id, {}))
                archive = Path(job.get("archive", ""))
                if job.get("status") != "done" or not archive.is_file():
                    self.send_json({"error": "Arhiva nu este gata."}, 404)
                    return
                self.send_file(archive, "application/zip", "Radio_BLAJ_Saptamana.zip")
                return
            if path.startswith("/library/"):
                filename = Path(path.removeprefix("/library/")).name
                candidate = LIBRARY / filename
                if candidate.is_file():
                    self.send_file(candidate, mimetypes.guess_type(candidate.name)[0])
                    return
                self.send_json({"error": "Fișierul nu există."}, 404)
                return
            self.serve_index()
        except (ValueError, RuntimeError) as error:
            self.send_json({"error": str(error)}, 400)
        except Exception as error:
            traceback.print_exc()
            self.send_json({"error": str(error)}, 500)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/download-week":
            self.send_json({"error": "Endpoint necunoscut."}, 404)
            return
        query = parse_qs(parsed.query)
        country = country_top_200.normalize_country(
            query.get("country", ["ro"])[0]
        )
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self.send_json({"error": f"Date JSON invalide: {error}"}, 400)
            return
        selected_tracks = payload.get("tracks")
        organize_by_day = payload.get("organize_by_day", False)
        if not isinstance(organize_by_day, bool):
            self.send_json(
                {"error": "Opțiunea de organizare pe zile este invalidă."},
                400,
            )
            return
        if selected_tracks is not None:
            if (
                not isinstance(selected_tracks, list)
                or not all(
                    isinstance(item, dict)
                    and isinstance(item.get("artist"), str)
                    and isinstance(item.get("track"), str)
                    for item in selected_tracks
                )
            ):
                self.send_json({"error": "Lista de melodii este invalidă."}, 400)
                return
            selected_tracks = [
                {
                    "artist": item["artist"].strip(),
                    "track": item["track"].strip(),
                }
                for item in selected_tracks
                if item["artist"].strip() and item["track"].strip()
            ]
            if not selected_tracks:
                self.send_json({"error": "Playlistul nu conține melodii."}, 400)
                return
        job_id = os.urandom(8).hex()
        JOB_CANCEL_EVENTS[job_id] = threading.Event()
        set_job(job_id, status="running", country=country)
        threading.Thread(
            target=run_week_download,
            args=(job_id, country, selected_tracks, organize_by_day),
            daemon=True,
        ).start()
        self.send_json({"job": job_id, "status": "running"}, 202)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/download-cancel":
            self.send_json({"error": "Endpoint necunoscut."}, 404)
            return
        job_id = parse_qs(parsed.query).get("job", [""])[0]
        event = JOB_CANCEL_EVENTS.get(job_id)
        if not event:
            self.send_json({"error": "Descărcarea nu există."}, 404)
            return
        event.set()
        set_job(job_id, status="cancelling", phase="cancelling")
        self.send_json({"job": job_id, "status": "cancelling"})

    def serve_index(self):
        self.send_file(ROOT / "index.html", "text/html; charset=utf-8")

    def send_file(self, path, content_type, download_name=None):
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Content-Length", str(size))
        if download_name:
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{download_name}"',
            )
        self.end_headers()
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                self.wfile.write(chunk)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    print(f"MUVO running on port {port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()