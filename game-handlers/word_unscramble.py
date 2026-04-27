import random
from typing import List, Dict, Optional


import json
import os

class WordUnscrambleGame:
    """Manages a single word unscramble game with multiple rounds."""
    def __init__(self, total_rounds: int = 10, word_count: int = 5, endless: bool = False, reveal_time: int = 30):
        """Initialize a new game.
        
        Args:
            total_rounds: Number of rounds to play (default: 10)
            word_count: Length of words to use
            endless: Whether the game is endless
            reveal_time: Time in seconds before revealing the word (default: 30)
        """
        self.total_rounds = total_rounds
        self.word_count = word_count
        self.endless = endless
        self.reveal_time = reveal_time
        self.current_round = 0
        self.scores: Dict[int, int] = {}  # user_id -> score
        self.current_word: Optional[str] = None
        self.current_scrambled: Optional[str] = None
        self.used_words: List[str] = []
        
        # Load words from JSON
        self.words_db = {}
        json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "word-unscramble", "words.json")
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                self.words_db = json.load(f)
        except Exception as e:
            # Fallback if file not found
            self.words_db = {
                "4": ["bird", "cats", "dogs", "fish"],
                "5": ["shore", "brisk", "flint", "cargo"],
                "6": ["hollow", "ripple", "anchor", "sector"]
            }
        
    def set_options(self, word_count: int, total_rounds: int, endless: bool, reveal_time: int = 30) -> None:
        """Update game options during joining phase."""
        self.word_count = word_count
        self.total_rounds = total_rounds
        self.endless = endless
        self.reveal_time = reveal_time

    def add_player(self, user_id: int) -> None:
        """Add a player to the game.
        
        Args:
            user_id: Telegram user ID
        """
        if user_id not in self.scores:
            self.scores[user_id] = 0

    def remove_player(self, user_id: int) -> None:
        """Remove a player from the game.
        
        Args:
            user_id: Telegram user ID
        """
        if user_id in self.scores:
            del self.scores[user_id]
            
    def scramble_word(self, word: str) -> str:
        """Scramble a word ensuring it's different from the original.
        
        Args:
            word: The word to scramble
            
        Returns:
            Scrambled version of the word
        """
        word_list = list(word)
        scrambled = word_list.copy()
        
        # Keep shuffling until we get a different arrangement
        # (or max 50 attempts for very short words)
        attempts = 0
        while ''.join(scrambled) == word and attempts < 50:
            random.shuffle(scrambled)
            attempts += 1
            
        return ''.join(scrambled)
    
    def start_new_round(self) -> tuple[str, int]:
        """Start a new round with a random word.
        
        Returns:
            Tuple of (scrambled_word, round_number)
        """
        self.current_round += 1
        
        # Get the list of words for the current word count
        word_list = self.words_db.get(str(self.word_count), [])
        if not word_list:
            # Fallback if no words of this length exist
            word_list = []
            for words in self.words_db.values():
                word_list.extend(words)
                
        # Select a random word that hasn't been used
        available_words = [w for w in word_list if w not in self.used_words]
        if not available_words:
            # Reset used words for this length if we've gone through all
            self.used_words = [w for w in self.used_words if w not in word_list]
            available_words = word_list
            
        self.current_word = random.choice(available_words)
        self.used_words.append(self.current_word)
        self.current_scrambled = self.scramble_word(self.current_word)
        
        return self.current_scrambled, self.current_round
    
    def check_answer(self, answer: str, user_id: int) -> bool:
        """Check if an answer is correct and award points.
        
        Args:
            answer: The user's answer
            user_id: Telegram user ID
            
        Returns:
            True if answer is correct, False otherwise
        """
        if not self.current_word:
            return False
            
        if answer.lower().strip() == self.current_word.lower():
            # Award point to the user
            if user_id in self.scores:
                self.scores[user_id] += 1
            else:
                self.scores[user_id] = 1
                
            # Store the correct word and clear current_word to prevent duplicate scoring
            self.last_word = self.current_word
            self.current_word = None
            return True
        return False
    
    def get_current_word(self) -> Optional[str]:
        """Get the current unscrambled word (for revealing answer)."""
        return self.current_word or getattr(self, 'last_word', None)
    
    def is_game_over(self) -> bool:
        """Check if the game has ended."""
        if self.endless:
            return False
        return self.current_round >= self.total_rounds
    
    def get_scoreboard(self) -> List[tuple[int, int]]:
        """Get sorted scoreboard.
        
        Returns:
            List of (user_id, score) tuples sorted by score (descending)
        """
        return sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
    
    def get_winners(self) -> List[int]:
        """Get list of user IDs with the highest score.
        
        Returns:
            List of user_ids who have the winning score
        """
        if not self.scores:
            return []
            
        scoreboard = self.get_scoreboard()
        if not scoreboard:
            return []
            
        highest_score = scoreboard[0][1]
        return [user_id for user_id, score in scoreboard if score == highest_score]
    
    def get_player_count(self) -> int:
        """Get number of players in the game."""
        return len(self.scores)
