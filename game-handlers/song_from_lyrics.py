import json
import os
import random
import re
from typing import Dict, List, Optional, Tuple


class SongFromLyricsGame:
    """Guess the Song Title & Artist from its lyrics, one line at a time."""

    ASSETS_DIR = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "assets", "song-from-lyrics"
    )

    def __init__(self, total_rounds: int = 10, endless: bool = False):
        """
        Args:
            total_rounds: Number of songs to play (ignored when endless=True).
            endless:      If True, keep playing until /newsong is used to advance.
        """
        self.total_rounds = total_rounds
        self.endless = endless
        self.current_round = 0

        self.scores: Dict[int, int] = {}       # user_id -> score
        self.players: Dict[int, str] = {}      # user_id -> display_name

        self.songs: List[dict] = []
        self.used_indices: List[int] = []

        # Current-round state
        self.current_song: Optional[dict] = None
        self.revealed_lines: int = 1           # how many lines are currently shown
        self.round_in_progress: bool = False
        self.title_guessed: bool = False
        self.artist_guessed: bool = False
        self.title_guesser_id: Optional[int] = None
        self.artist_guesser_id: Optional[int] = None

        self._load_songs()

    # ─────────────────────────── loading ──────────────────────────────────────

    def _load_songs(self) -> None:
        """Load all JSON song files from the assets directory."""
        self.songs = []
        try:
            for fname in os.listdir(self.ASSETS_DIR):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(self.ASSETS_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # Require at least title + at least one lyric line
                    if data.get("title") and data.get("lyrics"):
                        self.songs.append(data)
                except Exception:
                    pass
        except Exception as e:
            print(f"[SongFromLyricsGame] Error loading songs: {e}")

    # ─────────────────────────── player management ────────────────────────────

    def add_player(self, user_id: int, display_name: str = "Player") -> None:
        self.players[user_id] = display_name
        if user_id not in self.scores:
            self.scores[user_id] = 0

    def remove_player(self, user_id: int) -> None:
        self.players.pop(user_id, None)
        self.scores.pop(user_id, None)

    # ─────────────────────────── round flow ───────────────────────────────────

    def start_new_round(self) -> bool:
        """Pick a new song and reset per-round state.

        Returns True if a round was started, False if game is over.
        """
        if not self.endless and self.current_round >= self.total_rounds:
            return False

        if not self.songs:
            return False

        # Reset used list when all songs have been played
        if len(self.used_indices) >= len(self.songs):
            self.used_indices = []

        available = [i for i in range(len(self.songs)) if i not in self.used_indices]
        idx = random.choice(available)
        self.used_indices.append(idx)

        self.current_song = self.songs[idx]
        self.current_round += 1
        self.revealed_lines = 1
        self.round_in_progress = True
        self.title_guessed = False
        self.artist_guessed = False
        self.title_guesser_id = None
        self.artist_guesser_id = None

        return True

    def get_current_lyrics_block(self) -> str:
        """Return the currently revealed lyrics as a formatted string."""
        if not self.current_song:
            return ""
        lines = self.current_song.get("lyrics", [])
        shown = lines[: self.revealed_lines]
        return "\n".join(f"{i+1}. {line}" for i, line in enumerate(shown))

    def reveal_next_line(self, user_id: int) -> Tuple[bool, str]:
        """Reveal one more lyric line and subtract 1 point from the revealer.

        Returns:
            (line_was_revealed, updated_lyrics_block)
            line_was_revealed is False when all lines are already shown.
        """
        if not self.current_song or not self.round_in_progress:
            return False, ""

        lines = self.current_song.get("lyrics", [])
        if self.revealed_lines >= len(lines):
            return False, self.get_current_lyrics_block()

        # Deduct 1 point (floor at 0)
        current = self.scores.get(user_id, 0)
        self.scores[user_id] = max(0, current - 1)

        self.revealed_lines += 1
        return True, self.get_current_lyrics_block()

    def all_lines_revealed(self) -> bool:
        """Return True when every lyric line is already shown."""
        if not self.current_song:
            return True
        return self.revealed_lines >= len(self.current_song.get("lyrics", []))

    # ─────────────────────────── answer checking ──────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", text.lower())

    def check_title(self, user_id: int, text: str) -> bool:
        """Check if the text matches the song title (2 pts)."""
        if not self.current_song or not self.round_in_progress:
            return False
        if self.title_guessed:
            return False
        if user_id not in self.players:
            return False

        norm_guess = self._normalize(text)
        norm_title = self._normalize(self.current_song.get("title", ""))

        if norm_guess == norm_title:
            self.title_guessed = True
            self.title_guesser_id = user_id
            self.scores[user_id] = self.scores.get(user_id, 0) + 2
            return True
        return False

    def check_artist(self, user_id: int, text: str) -> bool:
        """Check if the text matches the artist name (2 pts)."""
        if not self.current_song or not self.round_in_progress:
            return False
        if self.artist_guessed:
            return False
        if user_id not in self.players:
            return False

        artist = self.current_song.get("artist", "")
        if not artist:
            return False

        norm_guess = self._normalize(text)
        norm_artist = self._normalize(artist)

        if norm_guess == norm_artist:
            self.artist_guessed = True
            self.artist_guesser_id = user_id
            self.scores[user_id] = self.scores.get(user_id, 0) + 2
            return True
        return False

    def is_round_complete(self) -> bool:
        """Both title and artist have been guessed (or artist is missing)."""
        if not self.current_song:
            return False
        artist = self.current_song.get("artist", "")
        if not artist:
            return self.title_guessed
        return self.title_guessed and self.artist_guessed

    # ─────────────────────────── info helpers ─────────────────────────────────

    def get_current_title(self) -> str:
        return self.current_song.get("title", "") if self.current_song else ""

    def get_current_artist(self) -> str:
        return self.current_song.get("artist", "") if self.current_song else ""

    def get_cover_path(self) -> Optional[str]:
        """Return absolute path to the cover image if it exists, else None."""
        if not self.current_song:
            return None
        cover_rel = self.current_song.get("cover", "")
        if not cover_rel:
            return None
        # cover field is like "covers/WHATS POPPIN.jpg"
        path = os.path.join(self.ASSETS_DIR, cover_rel)
        return path if os.path.exists(path) else None

    # ─────────────────────────── game state ───────────────────────────────────

    def is_game_over(self) -> bool:
        if self.endless:
            return False
        return self.current_round >= self.total_rounds

    def get_scoreboard(self) -> List[Tuple[int, int]]:
        return sorted(self.scores.items(), key=lambda x: x[1], reverse=True)

    def get_winners(self) -> List[int]:
        if not self.scores:
            return []
        board = self.get_scoreboard()
        if not board:
            return []
        top_score = board[0][1]
        return [uid for uid, s in board if s == top_score]

    def get_player_count(self) -> int:
        return len(self.players)
