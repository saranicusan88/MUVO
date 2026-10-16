import csv
import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

# Schimbi doar țara aici.
#
# ro = Romania
# de = Germany
# at = Austria
# us = USA
# gb = United Kingdom
# fr = France
# it = Italy
# es = Spain
# etc.
#
# Pentru GLOBAL:
# COUNTRY = "global"

COUNTRY = "ro"

TARGET_TRACKS = 200

# 8 este rapid, dar suficient de prudent cu Spotify.
MAX_WORKERS = 8

# Câte piese verificăm într-un lot.
CHECK_BATCH_SIZE = 80

# Maximum de candidați pe care îi luăm din pagina Totals.
# În practică 1500 este mai mult decât suficient.
MAX_TOTALS_CANDIDATES = 1500

OUTPUT_DIR = Path("output")

EXPLICIT_CACHE_FILE = Path("explicit_cache.json")

MANELE_FILE = Path("manele_artists.txt")


# ============================================================
# URLS
# ============================================================

KWORB_BASE = "https://kworb.net/spotify/country"

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

SPOTIFY_TRACK_URL = "https://api.spotify.com/v1/tracks/{track_id}"


# ============================================================
# DATA STRUCTURE
# ============================================================

@dataclass
class Track:
    spotify_id: str
    artist: str
    title: str
    source: str
    source_position: int


# ============================================================
# THREAD LOCAL HTTP SESSION
# ============================================================

thread_local = threading.local()


def get_session():
    """
    Fiecare thread primește propriul requests.Session.
    """

    if not hasattr(thread_local, "session"):

        session = requests.Session()

        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/154.0 Safari/537.36"
            )
        })

        thread_local.session = session

    return thread_local.session


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):
    """
    Transformă:
        Tzancă Uraganu
    în:
        tzanca uraganu

    Ajută foarte mult la filtrul de manele.
    """

    text = str(text).lower().strip()

    text = unicodedata.normalize("NFD", text)

    text = "".join(
        char
        for char in text
        if unicodedata.category(char) != "Mn"
    )

    text = text.replace("’", "'")

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text


# ============================================================
# LOAD MANELE ARTISTS
# ============================================================

def load_manele_artists():
    if not MANELE_FILE.exists():

        print(
            f"ATENȚIE: {MANELE_FILE} nu există."
        )

        return set()

    artists = set()

    with open(
        MANELE_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        for line in file:

            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            artists.add(
                normalize_text(line)
            )

    return artists


MANELE_ARTISTS = load_manele_artists()


# ============================================================
# MANELE FILTER
# ============================================================

MANELE_KEYWORDS = {
    "manele vtm",
    "manea",
    "manele",
    "lautare",
    "lautar",
}

def get_manele_reason(track):
    complete_text = normalize_text(
        f"{track.artist} {track.title}"
    )

    for blocked_artist in MANELE_ARTISTS:

        blocked = normalize_text(
            blocked_artist
        )

        if blocked in complete_text:
            return f"artist/colaborator: {blocked_artist}"

    return None


def is_manele(track):
    artist_text = normalize_text(track.artist)
    title_text = normalize_text(track.title)

    complete_text = normalize_text(
        f"{track.artist} {track.title}"
    )

    # ========================================================
    # 1. ARTIST SAU COLABORATOR DIN BLACKLIST
    # ========================================================

    for blocked_artist in MANELE_ARTISTS:

        blocked_artist = normalize_text(
            blocked_artist
        )

        if blocked_artist in complete_text:
            return True

    # ========================================================
    # 2. INDICATORI CLARI DE MANELE
    # ========================================================

    strong_keywords = {
        "manea",
        "manele",
        "manele vtm",
        "ministerul manelelor",
    }

    for keyword in strong_keywords:

        if normalize_text(keyword) in complete_text:
            return True

    return False


# ============================================================
# KWORB URL
# ============================================================

COUNTRY_ALIASES = {
    "romania": "ro",
    "românia": "ro",
    "spania": "es",
    "spain": "es",
    "germania": "de",
    "germany": "de",
    "anglia": "gb",
    "marea britanie": "gb",
    "united kingdom": "gb",
    "franta": "fr",
    "franța": "fr",
    "france": "fr",
    "italia": "it",
    "austria": "at",
    "statele unite": "us",
    "sua": "us",
    "united states": "us",
}


def normalize_country(country):
    value = str(country or "").lower().strip()
    return COUNTRY_ALIASES.get(value, value)


def kworb_url(country, chart_type):
    country = normalize_country(country)

    if country == "global":

        if chart_type == "daily":
            return "https://kworb.net/spotify/country/global_daily.html"

        if chart_type == "weekly":
            return "https://kworb.net/spotify/country/global_weekly.html"

        if chart_type == "totals":
            return "https://kworb.net/spotify/country/global_daily_totals.html"

    if chart_type == "daily":

        return (
            f"{KWORB_BASE}/"
            f"{country}_daily.html"
        )

    if chart_type == "weekly":

        return (
            f"{KWORB_BASE}/"
            f"{country}_weekly.html"
        )

    if chart_type == "totals":

        return (
            f"{KWORB_BASE}/"
            f"{country}_daily_totals.html"
        )

    raise ValueError(
        f"Tip chart necunoscut: {chart_type}"
    )


# ============================================================
# FIND SPOTIFY TRACK ID
# ============================================================

def extract_spotify_id(row):
    """
    Caută link de forma:

    /spotify/track/XXXXXXXXXXXXXXXXXXXXXX.html
    """

    links = row.find_all(
        "a",
        href=True
    )

    for link in links:

        href = link.get(
            "href",
            ""
        )

        match = re.search(
            r"/spotify/track/"
            r"([A-Za-z0-9]+)"
            r"\.html",
            href
        )

        if match:
            return match.group(1)

        # Kworb folosește uneori link relativ:
        # ../track/ID.html

        match = re.search(
            r"(?:^|/)"
            r"track/"
            r"([A-Za-z0-9]+)"
            r"\.html",
            href
        )

        if match:
            return match.group(1)

    return None


# ============================================================
# PARSE ARTIST AND TITLE
# ============================================================

def parse_artist_title(row):
    """
    Identifică celula Artist and Title.

    În Kworb textul este în mod normal:

    Artist - Title
    """

    cells = row.find_all("td")

    if not cells:
        return None, None

    # Căutăm celula care conține linkul de track.

    target_cell = None

    for cell in cells:

        if extract_spotify_id(cell):
            target_cell = cell
            break

    if target_cell is None:
        return None, None

    full_text = target_cell.get_text(
        " ",
        strip=True
    )

    if " - " not in full_text:
        return None, None

    artist, title = full_text.split(
        " - ",
        1
    )

    artist = artist.strip()
    title = title.strip()

    if not artist or not title:
        return None, None

    return artist, title


# ============================================================
# GET KWORB CHART
# ============================================================

def get_kworb_chart(
    country,
    chart_type,
    max_tracks=None
):
    url = kworb_url(
        country,
        chart_type
    )

    print()
    print(
        f"Descarc {chart_type.upper()}:"
    )
    print(url)

    session = get_session()

    response = session.get(
        url,
        timeout=30
    )

    response.raise_for_status()
    response.encoding = "utf-8"

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    tracks = []

    rows = soup.find_all("tr")

    position = 0

    for row in rows:

        spotify_id = extract_spotify_id(
            row
        )

        if not spotify_id:
            continue

        artist, title = parse_artist_title(
            row
        )

        if not artist or not title:
            continue

        position += 1

        tracks.append(
            Track(
                spotify_id=spotify_id,
                artist=artist,
                title=title,
                source=chart_type,
                source_position=position
            )
        )

        if (
            max_tracks is not None
            and len(tracks) >= max_tracks
        ):
            break

    print(
        f"Găsite: {len(tracks)}"
    )

    return tracks


# ============================================================
# EXPLICIT CACHE
# ============================================================

cache_lock = threading.Lock()


def load_explicit_cache():
    if not EXPLICIT_CACHE_FILE.exists():
        return {}

    try:

        with open(
            EXPLICIT_CACHE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {}


explicit_cache = load_explicit_cache()


def save_explicit_cache():
    """
    Salvează cache-ul pe disc.

    Data viitoare piesele cunoscute nu mai trebuie
    verificate la Spotify.
    """

    with cache_lock:

        temp_file = Path(
            str(EXPLICIT_CACHE_FILE)
            + ".tmp"
        )

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                explicit_cache,
                file,
                indent=2,
                ensure_ascii=False
            )

        temp_file.replace(
            EXPLICIT_CACHE_FILE
        )


# ============================================================
# SPOTIFY TOKEN MANAGER
# ============================================================

token_lock = threading.Lock()

spotify_token = None
spotify_token_expiry = 0


def get_spotify_token():
    global spotify_token
    global spotify_token_expiry

    current_time = time.time()

    # Token încă valid.
    if (
        spotify_token
        and current_time
        < spotify_token_expiry - 60
    ):
        return spotify_token

    with token_lock:

        current_time = time.time()

        if (
            spotify_token
            and current_time
            < spotify_token_expiry - 60
        ):
            return spotify_token

        client_id = os.getenv(
            "SPOTIFY_CLIENT_ID"
        )

        client_secret = os.getenv(
            "SPOTIFY_CLIENT_SECRET"
        )

        if not client_id:
            raise RuntimeError(
                "Lipsește SPOTIFY_CLIENT_ID din .env"
            )

        if not client_secret:
            raise RuntimeError(
                "Lipsește SPOTIFY_CLIENT_SECRET din .env"
            )

        session = get_session()

        response = session.post(
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type":
                "client_credentials"
            },
            auth=(
                client_id,
                client_secret
            ),
            timeout=20
        )

        response.raise_for_status()

        data = response.json()

        spotify_token = data[
            "access_token"
        ]

        expires_in = data.get(
            "expires_in",
            3600
        )

        spotify_token_expiry = (
            time.time()
            + expires_in
        )

        return spotify_token


# ============================================================
# SPOTIFY EXPLICIT CHECK
# ============================================================

def spotify_is_explicit(track_id):
    """
    Returnează:
        True  = explicit
        False = non-explicit
        None  = nu am putut verifica
    """

    with cache_lock:

        if track_id in explicit_cache:
            return explicit_cache[
                track_id
            ]

    # --------------------------------------------
    # MAX 6 ATTEMPTS
    # --------------------------------------------

    for attempt in range(6):

        try:

            token = get_spotify_token()

            session = get_session()

            response = session.get(
                SPOTIFY_TRACK_URL.format(
                    track_id=track_id
                ),
                headers={
                    "Authorization":
                    f"Bearer {token}"
                },
                params={
                    "market":
                    COUNTRY.upper()
                    if COUNTRY != "global"
                    else "US"
                },
                timeout=20
            )

            # ------------------------------------
            # SUCCESS
            # ------------------------------------

            if response.status_code == 200:

                data = response.json()

                explicit = bool(
                    data.get(
                        "explicit",
                        False
                    )
                )

                with cache_lock:

                    explicit_cache[
                        track_id
                    ] = explicit

                return explicit

            # ------------------------------------
            # RATE LIMIT
            # ------------------------------------

            if response.status_code == 429:

                retry_after = response.headers.get(
                    "Retry-After",
                    "2"
                )

                try:
                    retry_after = float(
                        retry_after
                    )

                except ValueError:
                    retry_after = 2

                print(
                    f"Spotify rate limit. "
                    f"Aștept {retry_after}s..."
                )

                time.sleep(
                    retry_after + 0.25
                )

                continue

            # ------------------------------------
            # TOKEN PROBLEM
            # ------------------------------------

            if response.status_code == 401:

                global spotify_token
                global spotify_token_expiry

                with token_lock:

                    spotify_token = None
                    spotify_token_expiry = 0

                continue

            # ------------------------------------
            # NOT FOUND
            # ------------------------------------

            if response.status_code == 404:

                return None

            # ------------------------------------
            # OTHER SERVER ERRORS
            # ------------------------------------

            if response.status_code >= 500:

                time.sleep(
                    1.5 * (attempt + 1)
                )

                continue

            print(
                "Spotify error:",
                response.status_code,
                track_id
            )

            return None

        except requests.RequestException:

            time.sleep(
                1.5 * (attempt + 1)
            )

    return None


# ============================================================
# VALIDATE ONE TRACK
# ============================================================

def validate_track(track):
    """
    Returnează track dacă este bun.

    None dacă:
    - manea
    - explicit
    - Spotify error
    """

    # Filtru local = foarte rapid
    if is_manele(track):
        return None

    explicit = spotify_is_explicit(
        track.spotify_id
    )

    if explicit is None:
        return None

    if explicit:
        return None

    return track


# ============================================================
# DEDUPE
# ============================================================

def track_text_key(track):
    return (
        normalize_text(track.artist),
        normalize_text(track.title)
    )


def build_unique_candidates(
    daily,
    weekly,
    totals
):
    """
    Prioritatea este:

    1. Daily actual
    2. Weekly
    3. Totals

    Astfel piesele actuale sunt mereu favorizate.
    """

    result = []

    seen_ids = set()
    seen_names = set()

    sources = [
        daily,
        weekly,
        totals
    ]

    for tracks in sources:

        for track in tracks:

            if (
                track.spotify_id
                in seen_ids
            ):
                continue

            text_key = track_text_key(
                track
            )

            if text_key in seen_names:
                continue

            seen_ids.add(
                track.spotify_id
            )

            seen_names.add(
                text_key
            )

            result.append(
                track
            )

    return result


# ============================================================
# PARALLEL VALIDATION
# ============================================================

def validate_batch(tracks):
    """
    Verifică mai multe piese simultan.
    """

    results = {}

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {
            executor.submit(
                validate_track,
                track
            ): index

            for index, track
            in enumerate(tracks)
        }

        for future in as_completed(
            future_map
        ):

            index = future_map[
                future
            ]

            try:

                result = future.result()

            except Exception as error:

                print(
                    "Eroare:",
                    tracks[index].artist,
                    "-",
                    tracks[index].title,
                    error
                )

                result = None

            results[index] = result

    # Thread-urile termină în ordine diferită.
    # Noi refacem ordinea originală.

    valid = []

    for index in range(
        len(tracks)
    ):

        result = results.get(
            index
        )

        if result is not None:
            valid.append(
                result
            )

    return valid


# ============================================================
# FIND EXACTLY 200
# ============================================================

def find_200_clean_tracks(
    candidates
):
    final_tracks = []

    total_candidates = len(
        candidates
    )

    index = 0

    print()
    print(
        "Încep verificarea Spotify..."
    )

    print(
        f"Workers: {MAX_WORKERS}"
    )

    print(
        f"Total candidați disponibili: "
        f"{total_candidates}"
    )

    while (
        len(final_tracks)
        < TARGET_TRACKS
        and index < total_candidates
    ):

        # ----------------------------------------
        # FILTRARE MANELE ÎNAINTE DE SPOTIFY
        # ----------------------------------------

        batch = []

        while (
            len(batch)
            < CHECK_BATCH_SIZE
            and index < total_candidates
        ):

            track = candidates[
                index
            ]

            index += 1

            if is_manele(track):
                continue

            batch.append(
                track
            )

        if not batch:
            continue

        # ----------------------------------------
        # PARALLEL SPOTIFY CHECK
        # ----------------------------------------

        valid = validate_batch(
            batch
        )

        # ----------------------------------------
        # ADD VALID TRACKS
        # ----------------------------------------

        for track in valid:

            final_tracks.append(
                track
            )

            if (
                len(final_tracks)
                >= TARGET_TRACKS
            ):
                break

        save_explicit_cache()

        print(
            f"Avem {len(final_tracks)}/"
            f"{TARGET_TRACKS} melodii curate "
            f"(analizați {index}/"
            f"{total_candidates})"
        )

    return final_tracks[
        :TARGET_TRACKS
    ]


# ============================================================
# CSV EXPORT
# ============================================================

def save_csv(
    tracks,
    country
):
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    filename = (
        OUTPUT_DIR
        / f"top_200_clean.csv"
    )

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.writer(
            file
        )

        # EXACT CE AI CERUT
        writer.writerow([
            "track",
            "artist"
        ])

        for track in tracks:

            writer.writerow([
                track.title,
                track.artist
            ])

    return filename


# ============================================================
# STATISTICS
# ============================================================

def print_preview(
    tracks,
    limit=20
):
    print()
    print("=" * 80)

    print(
        "PREVIEW"
    )

    print("=" * 80)

    for position, track in enumerate(
        tracks[:limit],
        start=1
    ):

        print(
            f"{position:3}. "
            f"{track.artist} - "
            f"{track.title}"
        )


def generate_country_tracks(country):
    """Return the validated top 200 for an API caller."""
    country = normalize_country(country or COUNTRY)
    if not re.fullmatch(r"[a-z]{2,12}", country):
        raise ValueError("Codul țării poate conține doar litere.")

    daily = get_kworb_chart(country, "daily", max_tracks=200)
    weekly = get_kworb_chart(country, "weekly", max_tracks=200)
    totals = get_kworb_chart(
        country,
        "totals",
        max_tracks=MAX_TOTALS_CANDIDATES
    )
    candidates = build_unique_candidates(daily, weekly, totals)
    tracks = find_200_clean_tracks(candidates)
    if len(tracks) < TARGET_TRACKS:
        raise RuntimeError(
            f"Am găsit doar {len(tracks)} melodii curate pentru {country.upper()}."
        )
    save_csv(tracks, country)
    save_explicit_cache()
    return tracks


# ============================================================
# MAIN
# ============================================================

def main():
    print()
    print("=" * 80)

    print(
        "COUNTRY TOP 200 CLEAN"
    )

    print("=" * 80)

    country=input("Introdu țara (ex: ro, de, at, us, gb, fr, it, es): ").strip().lower()
    COUNTRY = country if country else COUNTRY
    print(
        f"Țară: {COUNTRY.upper()}"
    )

    print(
        f"Țintă: {TARGET_TRACKS}"
    )

    # ========================================================
    # 1. CURRENT DAILY CHART
    # ========================================================

    daily = get_kworb_chart(
        COUNTRY,
        "daily",
        max_tracks=200
    )

    # ========================================================
    # 2. CURRENT WEEKLY CHART
    # ========================================================

    weekly = get_kworb_chart(
        COUNTRY,
        "weekly",
        max_tracks=200
    )

    # ========================================================
    # 3. LARGE COUNTRY POOL
    # ========================================================

    totals = get_kworb_chart(
        COUNTRY,
        "totals",
        max_tracks=MAX_TOTALS_CANDIDATES
    )

    # ========================================================
    # UNIQUE CANDIDATES
    # ========================================================

    candidates = build_unique_candidates(
        daily,
        weekly,
        totals
    )

    print()
    print(
        f"Total candidați unici: "
        f"{len(candidates)}"
    )

    # ========================================================
    # FAST LOCAL MANELE COUNT
    # ========================================================

    manele_count = sum(
        1
        for track in candidates
        if is_manele(track)
    )

    print(
        f"Eliminate local ca manele: "
        f"{manele_count}"
    )

    # ========================================================
    # FIND EXACT 200
    # ========================================================

    final_tracks = (
        find_200_clean_tracks(
            candidates
        )
    )

    # ========================================================
    # CHECK
    # ========================================================

    if (
        len(final_tracks)
        < TARGET_TRACKS
    ):

        print()
        print(
            "EROARE:"
        )

        print(
            f"Am găsit doar "
            f"{len(final_tracks)} "
            f"melodii valide."
        )

        print(
            "Mărește "
            "MAX_TOTALS_CANDIDATES."
        )

        return

    # ========================================================
    # SAVE
    # ========================================================

    filename = save_csv(
        final_tracks,
        COUNTRY
    )

    save_explicit_cache()

    print_preview(
        final_tracks
    )

    print()
    print("=" * 80)

    print(
        "GATA!"
    )

    print(
        f"CSV: {filename}"
    )

    print(
        f"Melodii: "
        f"{len(final_tracks)}"
    )

    print(
        "Explicit: 0"
    )

    print(
        "Manele detectate: 0"
    )

    print("=" * 80)


if __name__ == "__main__":
    main()