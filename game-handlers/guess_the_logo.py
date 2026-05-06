import os
import random
import re
from typing import List, Dict, Optional, Tuple

class GuessTheLogoGame:
    """Manages a guess the logo game where players take turns identifying logos."""

    def __init__(self, rounds_limit: int = 20):
        """Initialize the game.
        
        Args:
            rounds_limit: Maximum number of rounds to play.
        """
        self.rounds_limit = rounds_limit
        self.current_round = 0
        self.scores: Dict[int, int] = {}  # user_id -> score
        self.players: Dict[int, str] = {} # user_id -> display_name
        self.logos: List[Tuple[str, str, str]] = [] # list of (filename, answer_key, category)
        self.used_logos: List[str] = []
        
        # Options
        self.category_filter = "All"
        self.mode = "first" # "first" or "turn"
        self.time_limit = 60
        
        self.turn_order: List[int] = []
        self.current_turn_index = 0
        
        # Current round state
        self.current_logo_path: Optional[str] = None
        self.current_answer: Optional[str] = None
        self.waiting_for_answer: bool = False

        self._load_logos()

    def _load_logos(self):
        """Load logo files from the logos directory."""
        logo_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "guess-the-logo")
        if not os.path.exists(logo_dir):
            return

        categories = {}
        cat_path = os.path.join(logo_dir, "categories.json")
        if os.path.exists(cat_path):
            try:
                import json
                with open(cat_path, 'r') as f:
                    categories = json.load(f)
            except Exception:
                pass

        for root, _, files in os.walk(logo_dir):
            for filename in files:
                if filename.lower().endswith(('.webp', '.png', '.jpg', '.jpeg')):
                    clean_name = os.path.splitext(filename)[0]
                    cat = categories.get(filename, ["Global"])[0]
                    self.logos.append((os.path.join(root, filename), clean_name, cat))

    def add_player(self, user_id: int, display_name: str) -> None:
        """Add a player to the game."""
        self.players[user_id] = display_name
        if user_id not in self.scores:
            self.scores[user_id] = 0

    def remove_player(self, user_id: int) -> None:
        """Remove a player from the game."""
        if user_id in self.players:
            del self.players[user_id]
        if user_id in self.scores:
            del self.scores[user_id]

    def _normalize_answer(self, text: str) -> str:
        """Normalize answer for comparison (remove special chars, lowercase)."""
        return re.sub(r'[^a-zA-Z0-9]', '', text).lower()

    def start_game(self) -> None:
        """Start the game."""
        self.current_round = 0
        self.used_logos = []
        self.turn_order = list(self.players.keys())
        random.shuffle(self.turn_order)
        self.current_turn_index = 0

    def start_new_round(self) -> Optional[Tuple[str, int, Optional[int]]]:
        """Start a new round with a NEW logo.
        
        Returns:
            Tuple of (logo_path, round_number, current_player_id) or None if game over/error.
        """
        if self.is_game_over() or not self.players:
            return None

        self.current_round += 1
        
        if self.mode == "turn" and self.turn_order:
            self.current_turn_index = (self.current_turn_index + 1) % len(self.turn_order)
            current_player_id = self.turn_order[self.current_turn_index]
            # Ensure player is still in the game
            while current_player_id not in self.players and self.turn_order:
                self.turn_order.remove(current_player_id)
                if not self.turn_order:
                    return None
                self.current_turn_index = self.current_turn_index % len(self.turn_order)
                current_player_id = self.turn_order[self.current_turn_index]
        else:
            current_player_id = None
        
        # Pick a random logo not used yet
        available_logos = [l for l in self.logos if l[0] not in self.used_logos]
        if self.category_filter != "All":
            available_logos = [l for l in available_logos if l[2] == self.category_filter]
            
        if not available_logos:
            # If we run out in the specific category, just end or reset? Reset used.
            self.used_logos = []
            available_logos = [l for l in self.logos if l[2] == self.category_filter or self.category_filter == "All"]
        
        if not available_logos:
            return None 

        logo_path, answer, cat = random.choice(available_logos)
        self.used_logos.append(logo_path)
        self.current_logo_path = logo_path
        self.current_answer = answer
        self.waiting_for_answer = True
        
        return logo_path, self.current_round, current_player_id

    def check_answer(self, user_id: int, answer: str) -> bool:
        """Check if the answer is correct."""
        if not self.waiting_for_answer:
            return False
            
        if user_id not in self.players:
            pass
            
        if self.mode == "turn":
            if not self.turn_order:
                return False
            current_player = self.turn_order[self.current_turn_index]
            if user_id != current_player:
                return False
            
        if not self.current_answer:
            return False

        normalized_input = self._normalize_answer(answer)
        normalized_correct = self._normalize_answer(self.current_answer)
        
        if normalized_input == normalized_correct:
            self.scores[user_id] = self.scores.get(user_id, 0) + 1
            self.waiting_for_answer = False
            return True
        
        return False
    
    def resolve_round(self, correct: bool = False) -> str:
        """End current round manually. Returns answer."""
        self.waiting_for_answer = False
        return self.current_answer

    def is_game_over(self) -> bool:
        return self.current_round >= self.rounds_limit

    def get_scoreboard(self) -> List[Tuple[int, int]]:
        return sorted(self.scores.items(), key=lambda x: x[1], reverse=True)

    def get_winners(self) -> List[int]:
        if not self.scores:
            return []
        scoreboard = self.get_scoreboard()
        if not scoreboard:
            return []
        highest_score = scoreboard[0][1]
        return [user_id for user_id, score in scoreboard if score == highest_score]

    def get_player_count(self) -> int:
        return len(self.players)
