import os
import random
import re
import time
from typing import List, Dict, Optional, Tuple

class WhoAmIGame:
    """Manages a 'Who Am I' game session."""
    
    # Class-level variable to track played characters across all games
    _played_names = set()

    def __init__(self):
        """Initialize the game."""
        self.players: Dict[int, str] = {}  # user_id -> display_name
        self.characters: List[Dict[str, str]] = []  # list of {"name": name, "image": path}
        
        # Game state
        self.turn_order: List[int] = []
        self.current_turn_index: int = 0
        self.character_assignments: Dict[int, Dict[str, str]] = {}
        self.turn_start_time: Optional[float] = None
        self.completion_times: Dict[int, float] = {}  # user_id -> time in seconds
        self.game_over: bool = False

        self._load_characters()

    def _load_characters(self):
        """Load characters from the assets directory."""
        img_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "who-am-I")
        if not os.path.exists(img_dir):
            return

        all_files = os.listdir(img_dir)
        for filename in all_files:
            if filename.startswith('.'): continue
            
            # Extract name by removing extension (Only support JPG and PNG)
            if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
                
            name = re.sub(r'\.(jpeg|jpg|png|JPG|PNG)$', '', filename).strip()
            
            self.characters.append({
                "name": name,
                "image": os.path.join(img_dir, filename)
            })

    def add_player(self, user_id: int, display_name: str = "Player") -> None:
        """Add a player to the game."""
        self.players[user_id] = display_name

    def remove_player(self, user_id: int) -> None:
        """Remove a player from the game."""
        if user_id in self.players:
            del self.players[user_id]

    def start_game(self) -> bool:
        """Start the game, assign characters and determine turn order.
        
        Returns:
            True if started successfully (enough players and characters).
        """
        player_ids = list(self.players.keys())
        if len(player_ids) < 2 or len(self.characters) < len(player_ids):
            return False
            
        # Randomize turn order
        self.turn_order = player_ids.copy()
        random.shuffle(self.turn_order)
        self.current_turn_index = 0
        self.game_over = False
        self.completion_times = {}

        # Assign unique character to each player
        # Filter characters that haven't been played yet
        available = [c for c in self.characters if c['name'] not in WhoAmIGame._played_names]
        
        # If not enough available characters, reset the played set
        if len(available) < len(player_ids):
            WhoAmIGame._played_names.clear()
            available = self.characters.copy()
            
        selected_chars = random.sample(available, len(player_ids))
        for i, pid in enumerate(player_ids):
            char = selected_chars[i]
            self.character_assignments[pid] = char
            WhoAmIGame._played_names.add(char['name'])

        return True

    def get_current_player_id(self) -> Optional[int]:
        """Get the user_id of the player whose turn it is."""
        if not self.turn_order or self.game_over:
            return None
        return self.turn_order[self.current_turn_index]

    def get_current_player_name(self) -> str:
        """Get the name of the player whose turn it is."""
        pid = self.get_current_player_id()
        if pid:
            return self.players.get(pid, "Unknown")
        return "Unknown"

    def get_character_for_player(self, user_id: int) -> Optional[Dict[str, str]]:
        """Get the assigned character for a specific player."""
        return self.character_assignments.get(user_id)

    def swap_character(self, user_id: int) -> bool:
        """Replace the player's character with a new random one from the available pool.
        
        Returns:
            True if a new character was assigned.
        """
        used_names = {c['name'] for c in self.character_assignments.values()}
        
        # Filter available from the global pool first
        available = [c for c in self.characters 
                     if c['name'] not in used_names and c['name'] not in WhoAmIGame._played_names]
        
        # If no characters left in global pool, reset it (but still avoid currently used ones)
        if not available:
            # We don't clear the whole set here to avoid repeating characters in the SAME game
            # but we can clear it and filter out current ones
            temp_pool = [c for c in self.characters if c['name'] not in used_names]
            if not temp_pool:
                return False
            WhoAmIGame._played_names.clear()
            available = temp_pool
            
        new_char = random.choice(available)
        self.character_assignments[user_id] = new_char
        WhoAmIGame._played_names.add(new_char['name'])
        return True

    def start_turn(self) -> None:
        """Record the start time for the current turn."""
        self.turn_start_time = time.time()

    def _normalize_answer(self, text: str) -> str:
        """Normalize answer for comparison (remove special chars, lowercase)."""
        return re.sub(r'[^a-zA-Z0-9]', '', text).lower()

    def check_guess(self, user_id: int, guess: str) -> bool:
        """Check if the current player guessed their assigned character.
        
        Returns:
            True if correct guess.
        """
        if self.game_over or user_id != self.get_current_player_id() or self.turn_start_time is None:
            return False

        assigned_char = self.character_assignments.get(user_id)
        if not assigned_char:
            return False

        normalized_guess = self._normalize_answer(guess)
        normalized_correct = self._normalize_answer(assigned_char["name"])

        # Check for partial match or full match
        if normalized_guess == normalized_correct or normalized_correct in normalized_guess:
            elapsed_time = time.time() - self.turn_start_time
            self.completion_times[user_id] = elapsed_time
            return True
        return False

    def next_turn(self) -> bool:
        """Advance to the next turn.
        
        Returns:
            True if there's a next turn, False if game over.
        """
        self.current_turn_index += 1
        if self.current_turn_index >= len(self.turn_order):
            self.game_over = True
            return False
        self.turn_start_time = None
        return True

    def get_leaderboard(self) -> List[Tuple[int, float]]:
        """Get the scoreboard sorted by shortest time.
        
        Returns:
            List of (user_id, time_seconds) sorted ascending by time.
        """
        # Only include players who completed their turn successfully
        completed = [(pid, t) for pid, t in self.completion_times.items()]
        return sorted(completed, key=lambda x: x[1])

    def get_winners(self) -> List[int]:
        """Get the list of winner user IDs (could be multiple in case of exact tie)."""
        board = self.get_leaderboard()
        if not board:
            return []
        best_time = board[0][1]
        return [pid for pid, t in board if t == best_time]
