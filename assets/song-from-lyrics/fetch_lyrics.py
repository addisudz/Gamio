#!/usr/bin/env python3
"""
fetch_lyrics.py
───────────────
Automatically fetches song data (artist, title, lyrics, and cover)
from multiple sources and saves them in the format required for the game.
"""

import os
import re
import sys
import json
import time
import argparse
import requests
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

OUTPUT_DIR = Path(__file__).parent  # assets/song-from-lyrics/
COVERS_DIR = OUTPUT_DIR / "covers"
COVERS_DIR.mkdir(exist_ok=True)

APPLE_CHART_URL    = "https://itunes.apple.com/us/rss/topsongs/limit={limit}/json"
LAST_FM_CHART_URL  = "https://www.last.fm/charts?page={page}"
LYRICS_OVH_URL     = "https://api.lyrics.ovh/v1/{artist}/{title}"
GENIUS_SEARCH_URL  = "https://api.genius.com/search"

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str, emoji: str = ""):
    prefix = f"{emoji} " if emoji else ""
    print(f"{prefix}{msg}")


def clean_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = name.strip(". ")
    return name or "unknown"


def normalize(text: str) -> str:
    return text.strip().lower()


def existing_song_titles() -> set:
    titles = set()
    for f in OUTPUT_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if "title" in data:
                titles.add(normalize(data["title"]))
        except Exception:
            titles.add(normalize(f.stem))
    return titles


# ── Song List ─────────────────────────────────────────────────────────────────

def get_top_songs(limit: int) -> list[dict]:
    url = APPLE_CHART_URL.format(limit=limit)
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        entries = data.get("feed", {}).get("entry", [])
        tracks = []
        for entry in entries:
            title  = entry.get("im:name", {}).get("label")
            artist = entry.get("im:artist", {}).get("label")
            date   = entry.get("im:releaseDate", {}).get("label", "")
            year   = int(date[:4]) if date and len(date) >= 4 else None
            if title and artist:
                tracks.append({"title": title, "artist": artist, "year": year})
        return tracks
    except Exception as e:
        log(f"Error fetching Apple Music: {e}", "⚠️")
        return []


def get_lastfm_charts(num_pages: int) -> list[dict]:
    tracks = []
    seen = set()
    for page in range(1, num_pages + 1):
        log(f"  Scraping Last.fm page {page}...", "🌐")
        try:
            resp = requests.get(LAST_FM_CHART_URL.format(page=page), 
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.raise_for_status()
            matches = re.findall(r'href="/music/([^/]+)/_/([^/?#"]+)"', resp.text)
            for a_raw, t_raw in matches:
                a = urllib.parse.unquote(a_raw).replace("+", " ").strip()
                t = urllib.parse.unquote(t_raw).replace("+", " ").strip()
                if a and t:
                    key = normalize(f"{t} {a}")
                    if key not in seen:
                        seen.add(key); tracks.append({"title": t, "artist": a, "year": None})
            if page < num_pages: time.sleep(1.0)
        except Exception as e:
            log(f"Error scraping Last.fm: {e}", "⚠️"); break
    return tracks


# ── Data Fetching ─────────────────────────────────────────────────────────────

def get_song_year_genius(title: str, artist: str) -> int | None:
    token = os.getenv("GENIUS_ACCESS_TOKEN", "").strip()
    if not token: return None
    try:
        resp = requests.get(GENIUS_SEARCH_URL, headers={"Authorization": f"Bearer {token}"},
                            params={"q": f"{title} {artist}"}, timeout=5)
        hits = resp.json().get("response", {}).get("hits", [])
        if hits:
            res = hits[0].get("result", {})
            rd = res.get("release_date_components")
            if rd and "year" in rd: return rd["year"]
    except Exception: pass
    return None


def fetch_lyrics_ovh(artist: str, title: str) -> list[str] | None:
    try:
        url = LYRICS_OVH_URL.format(artist=requests.utils.quote(artist), title=requests.utils.quote(title))
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            raw = resp.json().get("lyrics", "")
            if raw:
                lines = parse_lyrics_text(raw)
                if len(lines) >= 5: return lines
    except Exception: pass
    return None


def get_lyrics_and_cover_genius(artist: str, title: str) -> tuple[list[str] | None, str | None]:
    token = os.getenv("GENIUS_ACCESS_TOKEN", "").strip()
    if not token: return None, None
    try:
        resp = requests.get(GENIUS_SEARCH_URL, headers={"Authorization": f"Bearer {token}"},
                            params={"q": f"{title} {artist}"}, timeout=10)
        hits = resp.json().get("response", {}).get("hits", [])
        for hit in hits[:3]:
            res = hit.get("result", {})
            ha = normalize(res.get("primary_artist", {}).get("name", ""))
            ta = normalize(artist)
            if ta in ha or ha in ta or not artist:
                cover = res.get("song_art_image_url")
                url = res.get("url", "")
                lines = scrape_genius_lyrics(url) if url else None
                return lines, cover
    except Exception as e:
        log(f"Genius error: {e}", "⚠️")
    return None, None


def scrape_genius_lyrics(url: str) -> list[str] | None:
    try:
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        resp = requests.get(url, headers={"User-Agent": ua}, timeout=15)
        if resp.status_code != 200: return None
        chunks = re.findall(r'data-lyrics-container="true".*?>(.*?)</div>', resp.text, re.DOTALL)
        if not chunks: chunks = re.findall(r'class="lyrics".*?>(.*?)</div>', resp.text, re.DOTALL)
        raw = ""
        for chunk in chunks:
            chunk = re.sub(r"<br\s*/?>", "\n", chunk, flags=re.IGNORECASE)
            chunk = re.sub(r"<(?!/?\n)[^>]+>", "", chunk)
            chunk = re.sub(r"<[^>]+>", "", chunk)
            raw += chunk + "\n"
        if raw.strip():
            lines = parse_lyrics_text(raw)
            if len(lines) >= 5: return lines
    except Exception: pass
    return None


def parse_lyrics_text(raw: str) -> list[str]:
    raw = re.sub(r"\[.*?\]", "", raw)
    lines = [line.strip() for line in raw.splitlines()]
    return [l for l in lines if l and not re.fullmatch(r"[\d\W]+", l)]


def download_image(url: str, dest: Path):
    try:
        resp = requests.get(url, stream=True, timeout=15)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(1024): f.write(chunk)
    except Exception as e:
        log(f"Image error: {e}", "⚠️")


def get_all_data(artist: str, title: str) -> tuple[list[str] | None, str | None]:
    # 1. Try OVH for lyrics first
    lines = fetch_lyrics_ovh(artist, title)
    # 2. Try Genius for cover and (if needed) lyrics
    glines, cover = get_lyrics_and_cover_genius(artist, title)
    return (lines or glines), cover


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch song data.")
    parser.add_argument("--popular", action="store_true")
    parser.add_argument("--charts",  action="store_true")
    parser.add_argument("--pages",   type=int, default=5)
    parser.add_argument("--file",    metavar="PATH")
    parser.add_argument("--limit",   type=int, default=100)
    parser.add_argument("--skip-year", type=int, default=2026)
    args = parser.parse_args()

    log("Song Lyrics & Cover Fetcher", "🎵")
    
    tracks = []
    if args.file:
        for line in Path(args.file).read_text().splitlines():
            line = line.strip()
            if not line: continue
            for sep in [" — ", " —", "— ", "—", " - ", "-"]:
                if sep in line:
                    t, a = line.split(sep, 1)
                    t = re.sub(r'^\d+[\.\)\-\s]+', '', t.strip())
                    tracks.append({"title": t.strip(), "artist": a.strip(), "year": None})
                    break
    elif args.charts:
        tracks = get_lastfm_charts(args.pages)
    elif args.popular:
        # (Popular list removed for brevity, can be added back if needed)
        pass
    else:
        tracks = get_top_songs(args.limit)

    log(f"Processing {len(tracks)} tracks...", "✅")

    success, skipped = 0, 0
    for i, track in enumerate(tracks, 1):
        title, artist, year = track["title"], track["artist"], track["year"]
        clean_title = clean_filename(title)
        json_path = OUTPUT_DIR / f"{clean_title}.json"
        
        lyrics = None
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if data.get("cover") and (COVERS_DIR / Path(data["cover"]).name).exists():
                    skipped += 1; continue
                lyrics = data.get("lyrics")
            except Exception: pass

        if year is None and args.skip_year:
            year = get_song_year_genius(title, artist)
        if args.skip_year and year == args.skip_year:
            skipped += 1; continue

        log(f"[{i:3d}/{len(tracks)}] 🔍 {title} — {artist}")
        
        final_lyrics, cover_url = (lyrics, None)
        if not lyrics:
            final_lyrics, cover_url = get_all_data(artist, title)
        else:
            _, cover_url = get_lyrics_and_cover_genius(artist, title)

        if final_lyrics:
            img_name = f"{clean_title}.jpg"
            if cover_url:
                log("        📸 Downloading cover...")
                download_image(cover_url, COVERS_DIR / img_name)
            
            song_data = {
                "artist": artist, "title": title, "lyrics": final_lyrics,
                "cover": f"covers/{img_name}" if cover_url else None
            }
            json_path.write_text(json.dumps(song_data, indent=2), encoding="utf-8")
            log(f"        ✅ Saved {len(final_lyrics)} lines")
            success += 1
        else:
            log("        ❌ Lyrics not found")
        
        time.sleep(0.5)

    log(f"Done! Saved: {success} | Skipped: {skipped}", "🏁")

if __name__ == "__main__":
    main()
