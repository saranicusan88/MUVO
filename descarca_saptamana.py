import csv
import os
import random
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# FFMPEG
# ============================================================

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass


import yt_dlp


# ============================================================
# CONFIGURARE
# ============================================================

FISIER_CSV = os.path.join(
    "output",
    "top_200_clean.csv"
)

FOLDER_LIBRARY = "Music_Library"

MAX_WORKERS = 4

NUMAR_MELODII_PE_ZI = 200

ZILE = [
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
]


# Folder Downloads
DOWNLOADS_FOLDER = os.path.join(
    os.path.expanduser("~"),
    "Downloads"
)

os.makedirs(
    DOWNLOADS_FOLDER,
    exist_ok=True
)


NUME_ZIP = os.path.join(
    DOWNLOADS_FOLDER,
    "Radio_BLAJ_Saptamana.zip"
)


# ============================================================
# CURATARE NUME
# ============================================================

def curata_nume(text):

    text = str(text).strip()

    text = re.sub(
        r'[<>:"/\\|?*]',
        "",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# CITIRE CSV
# ============================================================

def citeste_csv():

    if not os.path.exists(FISIER_CSV):

        print()
        print(
            f"EROARE: Nu gasesc fisierul "
            f"'{FISIER_CSV}'."
        )

        print(
            "Pune melodii.csv in acelasi folder "
            "cu scriptul."
        )

        sys.exit(1)

    melodii = []
    vazute = set()

    with open(
        FISIER_CSV,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        if not reader.fieldnames:

            print(
                "EROARE: CSV-ul nu are antet."
            )

            sys.exit(1)

        coloane = {
            nume.strip().lower(): nume
            for nume in reader.fieldnames
            if nume
        }

        if (
            "artist" not in coloane
            or
            "track" not in coloane
        ):

            print()
            print(
                "EROARE: CSV-ul trebuie sa aiba:"
            )

            print(
                "artist,track"
            )

            print()
            print(
                "Coloane gasite:"
            )

            print(
                reader.fieldnames
            )

            sys.exit(1)

        artist_col = coloane["artist"]
        track_col = coloane["track"]

        for row in reader:

            artist = (
                row.get(
                    artist_col,
                    ""
                )
                or ""
            ).strip()

            track = (
                row.get(
                    track_col,
                    ""
                )
                or ""
            ).strip()

            if not artist or not track:
                continue

            key = (
                artist.casefold(),
                track.casefold()
            )

            if key in vazute:
                continue

            vazute.add(key)

            melodii.append({
                "artist": artist,
                "track": track
            })

    return melodii


# ============================================================
# NUME FISIER MP3
# ============================================================

def cale_mp3(index, artist, track):

    artist = curata_nume(artist)
    track = curata_nume(track)


    nume = f"{index:03d} - {artist} - {track}.mp3"

    return os.path.join(
        FOLDER_LIBRARY,
        nume
    )


# ============================================================
# DOWNLOAD O MELODIE
# ============================================================

def descarca_melodie(
    index,
    artist,
    track
):

    final_mp3 = cale_mp3(
        index,
        artist,
        track
    )

    # Cache
    if os.path.exists(final_mp3):

        print(
            f"[{index:03d}] DEJA EXISTA: "
            f"{artist} - {track}"
        )

        return {
            "index": index,
            "artist": artist,
            "track": track,
            "path": final_mp3
        }

    baza = os.path.splitext(
        final_mp3
    )[0]

    output_template = (
        baza
        + ".%(ext)s"
    )

    query = (
        f"{artist} - "
        f"{track} official audio"
    )

    print(
        f"[{index:03d}] START: "
        f"{artist} - {track}"
    )

    options = {

        "format":
            "bestaudio/best",

        "outtmpl":
            output_template,

        "noplaylist":
            True,

        "quiet":
            True,

        "no_warnings":
            True,

        "retries":
            3,

        "fragment_retries":
            3,

        "continuedl":
            True,

        "postprocessors": [
            {
                "key":
                    "FFmpegExtractAudio",

                "preferredcodec":
                    "mp3",

                "preferredquality":
                    "192",
            }
        ],
    }

    try:

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            ydl.download([
                f"ytsearch1:{query}"
            ])

        if not os.path.exists(
            final_mp3
        ):

            raise FileNotFoundError(
                "Fisierul MP3 nu a fost creat."
            )

        print(
            f"[{index:03d}] GATA: "
            f"{artist} - {track}"
        )

        return {
            "index": index,
            "artist": artist,
            "track": track,
            "path": final_mp3
        }

    except Exception as error:

        print()
        print(
            f"[{index:03d}] EROARE: "
            f"{artist} - {track}"
        )

        print(error)

        return None


# ============================================================
# DOWNLOAD PARALEL
# ============================================================

def descarca_toate(melodii, progress_callback=None, cancel_event=None):

    rezultate = []

    total = len(melodii)

    print()
    print("=" * 60)

    print(
        f"DESCARC {total} MELODII"
    )

    print(
        f"THREADURI: {MAX_WORKERS}"
    )

    print("=" * 60)
    print()

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for index, melodie in enumerate(
            melodii,
            start=1
        ):

            future = executor.submit(
                descarca_melodie,
                index,
                melodie["artist"],
                melodie["track"]
            )

            futures[future] = index

        terminate = 0

        for future in as_completed(
            futures
        ):

            terminate += 1

            if cancel_event and cancel_event.is_set():
                for pending in futures:
                    pending.cancel()
                raise RuntimeError("Descărcarea a fost oprită de utilizator.")

            try:

                rezultat = (
                    future.result()
                )

                if rezultat:
                    rezultate.append(
                        rezultat
                    )

            except Exception as error:

                print(
                    "Eroare thread:",
                    error
                )

            print(
                f"PROGRES: "
                f"{terminate}/{total}"
            )
            if progress_callback:
                progress_callback(terminate, total, "download")

    rezultate.sort(
        key=lambda x:
            x["index"]
    )

    return rezultate


# ============================================================
# GENERARE SAPTAMANA
# ============================================================

def genereaza_saptamana(
    melodii
):

    rezultat = {}

    if not melodii:
        return rezultat

    melodii_unice = []
    chei_vazute = set()

    for melodie in melodii:
        cheie = (
            str(melodie.get("artist", "")).strip().casefold(),
            str(melodie.get("track", "")).strip().casefold(),
        )
        if cheie in chei_vazute:
            continue
        chei_vazute.add(cheie)
        melodii_unice.append(melodie)

    for i, zi in enumerate(ZILE):

        rng = random.Random(
            1000 + i
        )

        lista = melodii_unice.copy()

        rng.shuffle(lista)
        lista = lista[:NUMAR_MELODII_PE_ZI]

        rezultat[zi] = lista

    return rezultat


# ============================================================
# CREARE ZIP
# ============================================================

def creeaza_zip(
    saptamana,
    progress_callback=None
):

    if os.path.exists(
        NUME_ZIP
    ):

        os.remove(
            NUME_ZIP
        )

    print()
    print("=" * 60)
    print("CREEZ ZIP-UL")
    print("=" * 60)
    print()

    total_files = sum(len(saptamana[zi]) for zi in ZILE)
    archived_files = 0

    with zipfile.ZipFile(
        NUME_ZIP,
        "w",
        compression=zipfile.ZIP_STORED,
        allowZip64=True
    ) as archive:

        for zi in ZILE:

            lista = saptamana[zi]

            print(
                f"{zi}: "
                f"{len(lista)} melodii"
            )

            for pozitie, melodie in enumerate(
                lista,
                start=1
            ):

                artist = curata_nume(
                    melodie["artist"]
                )

                track = curata_nume(
                    melodie["track"]
                )

                nume_zip = (
                    f"{zi}/"
                    f"{pozitie:03d} - "
                    f"{artist} - "
                    f"{track}.mp3"
                )

                archive.write(
                    melodie["path"],
                    arcname=nume_zip
                )
                archived_files += 1
                if progress_callback:
                    progress_callback(
                        archived_files,
                        total_files,
                        "zip"
                    )


def creeaza_zip_simplu(
    melodii,
    progress_callback=None
):
    """Create one flat archive without weekday folders."""
    if os.path.exists(NUME_ZIP):
        os.remove(NUME_ZIP)

    total_files = len(melodii)

    with zipfile.ZipFile(
        NUME_ZIP,
        "w",
        compression=zipfile.ZIP_STORED,
        allowZip64=True
    ) as archive:
        for position, melodie in enumerate(melodii, start=1):
            artist = curata_nume(melodie["artist"])
            track = curata_nume(melodie["track"])
            archive_name = (
                f"{position:03d} - {artist} - {track}.mp3"
            )
            archive.write(
                melodie["path"],
                arcname=archive_name
            )
            if progress_callback:
                progress_callback(
                    position,
                    total_files,
                    "zip"
                )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("RADIO BLAJ - WEEK DOWNLOADER")
    print("=" * 60)
    print()

    start = time.time()

    os.makedirs(
        FOLDER_LIBRARY,
        exist_ok=True
    )

    # 1. Citire CSV

    melodii = citeste_csv()

    print(
        f"Melodii unice gasite: "
        f"{len(melodii)}"
    )

    if not melodii:

        print(
            "Nu exista melodii."
        )

        return

    # 2. Download

    descarcate = (
        descarca_toate(
            melodii
        )
    )

    print()
    print(
        f"Melodii descarcate: "
        f"{len(descarcate)}"
    )

    if not descarcate:

        print(
            "Nu exista melodii disponibile."
        )

        return

    # 3. ZIP unic, fără împărțire pe zile

    print()
    print("Creez un ZIP unic cu toate melodiile...")

    creeaza_zip_simplu(
        descarcate
    )

    durata = (
        time.time()
        -
        start
    )

    minute = int(
        durata // 60
    )

    secunde = int(
        durata % 60
    )

    print()
    print("=" * 60)
    print("GATA!")
    print("=" * 60)

    print(
        f"Timp total: "
        f"{minute} min "
        f"{secunde} sec"
    )

    print()
    print(
        "ZIP salvat aici:"
    )

    print(
        NUME_ZIP
    )

    print()

    try:

        os.startfile(
            DOWNLOADS_FOLDER
        )

    except Exception:
        pass

    input(
        "Apasa ENTER pentru a inchide..."
    )


if __name__ == "__main__":
    main()