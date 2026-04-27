"""
UNO game wrapper for Gamio bot.
Uses the original mau_mau_bot core logic (Game, Player, Deck, Card)
by adding mau_mau_bot/ to sys.path and importing from it directly.
"""

import sys
import os
import logging
import random
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Add mau_mau_bot to path so its internal imports resolve ──────────────────
_MAU_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "mau_mau_bot")
if _MAU_PATH not in sys.path:
    sys.path.insert(0, _MAU_PATH)

# Now import the originals
import card as _c
from deck import Deck
from game import Game
from player import Player
from errors import DeckEmptyError

# ── Re-export constants that main.py imports from this module ─────────────────
COLORS     = _c.COLORS
COLOR_NAMES = {"r": "Red", "b": "Blue", "g": "Green", "y": "Yellow"}
COLOR_ICONS = _c.COLOR_ICONS

# Sticker maps (colorblind set — the ones used at runtime)
CARD_STICKERS: Dict[str, str] = {**_c.STICKERS}          # card_key → file_id
STICKERS_GREY: Dict[str, str] = {**_c.STICKERS_GREY}      # card_key → grey_file_id
STICKER_TO_CARD: Dict[str, str] = {v: k for k, v in CARD_STICKERS.items()}


# ── Minimal chat stub so Game() doesn't crash on `game.chat.id` ─────────────
class _FakeChat:
    def __init__(self, chat_id: int):
        self.id    = chat_id
        self.title = "Gamio UNO"
        self.type  = "supergroup"


# ── Minimal user stub for Player() ───────────────────────────────────────────
class _FakeUser:
    def __init__(self, user_id: int, name: str):
        self.id         = user_id
        self.first_name = name
        self.username   = name


# ── UnoGame wrapper ───────────────────────────────────────────────────────────
class UnoGame:
    """
    Wraps the mau_mau_bot Game/Player objects to fit the Gamio GameSession
    interface (add_player / remove_player / start_game /
    get_scoreboard / get_winners) plus UNO-specific helpers.
    """

    def __init__(self):
        self._game:        Optional[Game]           = None
        self._chat_id:     int                      = 0
        self.players:      Dict[int, str]           = {}   # uid → display_name
        self._player_map:  Dict[int, Player]        = {}   # uid → Player obj
        self.creator_id:   Optional[int]            = None

        self.game_over:    bool       = False
        self.finish_order: List[int]  = []   # uids in winning order
        self.scores:       Dict[int, int] = {}
        self.mode:         str        = "fast"

    # ── GameSession interface ─────────────────────────────────────────────────

    def add_player(self, user_id: int, display_name: str) -> None:
        if not self.players:
            self.creator_id = user_id
        self.players[user_id] = display_name

    def remove_player(self, user_id: int) -> None:
        self.players.pop(user_id, None)
        if self.creator_id == user_id:
            self.creator_id = next(iter(self.players)) if self.players else None

    def get_player_count(self) -> int:
        return len(self.players)

    # ── Start ─────────────────────────────────────────────────────────────────

    def start_game(self) -> str:
        """Initialise the mau_mau_bot Game, add Players, deal, flip first card."""
        self._game = Game(_FakeChat(self._chat_id))
        self._game.mode = self.mode

        # Step 1: Fill the deck FIRST (mirroring game.start() but without dealing yet)
        if self.mode == "wild":
            self._game.deck._fill_wild_()
        else:
            self._game.deck._fill_classic_()

        # Step 2: Add all players (random order)
        uid_list = list(self.players.keys())
        random.shuffle(uid_list)
        for uid in uid_list:
            p = Player(self._game, _FakeUser(uid, self.players[uid]))
            self._player_map[uid] = p

        # Step 3: Deal 7 cards to each player
        for p in self._player_map.values():
            try:
                p.draw_first_hand()
            except DeckEmptyError:
                pass

        # Step 4: Flip first non-special card (mimics game._first_card_())
        self._game._first_card_()
        self._game.started = True

        mode_desc = {"classic": "Classic 🎻", "fast": "Gotta go fast! 🚀", "wild": "Into the Wild~ 🐉"}.get(self.mode, self.mode)
        return f"Mode: {mode_desc}\nFirst card: {self._card_display(self._game.last_card)}"

    # ── State helpers ─────────────────────────────────────────────────────────

    @property
    def last_card(self):
        return self._game.last_card if self._game else None

    @property
    def current_player_id(self) -> Optional[int]:
        if not self._game or not self._game.current_player:
            return None
        return self._game.current_player.user.id

    def get_current_player_name(self) -> str:
        pid = self.current_player_id
        return self.players.get(pid, "Unknown") if pid else "Unknown"

    @property
    def reversed(self) -> bool:
        return self._game.reversed if self._game else False

    @property
    def draw_counter(self) -> int:
        return self._game.draw_counter if self._game else 0

    @property
    def choosing_color(self) -> bool:
        return self._game.choosing_color if self._game else False

    @property
    def drew_this_turn(self) -> bool:
        """Check if the current player has drawn a card this turn."""
        p = self._game.current_player if self._game else None
        return p.drew if p else False

    # ── Card helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _card_display(card) -> str:
        if card is None:
            return "?"
        if card.special == _c.CHOOSE:    return "Wild Card"
        if card.special == _c.DRAW_FOUR: return "Wild +4"
        color_map = {"r": "Red", "b": "Blue", "g": "Green", "y": "Yellow"}
        val_map   = {_c.DRAW_TWO: "Draw Two", _c.REVERSE: "Reverse",
                     _c.SKIP: "Skip"}
        col = color_map.get(card.color, card.color or "")
        val = val_map.get(card.value, card.value or "")
        return f"{col} {val}"

    # ── Playable cards ────────────────────────────────────────────────────────

    def get_playable_cards(self, user_id: int) -> list:
        """Return list of playable card strings for user."""
        p = self._player_map.get(user_id)
        if not p:
            return []
        return p.playable_cards()   # returns Card objects

    # ── Actions ───────────────────────────────────────────────────────────────

    def anticipate_play(self, user_id: int, card_str: str) -> Tuple[bool, str, bool]:
        """
        Allow a non-current player to cut in and play an exact-match card.
        The game rotates the current player pointer to this user, then plays
        normally. All other players in between are skipped.
        Returns (success, message, needs_color_choice).
        """
        if self.game_over:
            return False, "The game is already over.", False
        if user_id == self.current_player_id:
            return False, "It's your turn already! Use the normal play.", False

        p = self._player_map.get(user_id)
        if not p:
            return False, "You are not in the game.", False

        # Check card exists in hand
        card_obj = next((c for c in p.cards if str(c) == card_str), None)
        if card_obj is None:
            return False, "You don't have that card!", False

        # Verify it's an exact match (same color + same value, no specials)
        last = self._game.last_card
        if not last or not last.color:
            return False, "No card to match against.", False
        if card_obj.special or card_obj.color != last.color or card_obj.value != last.value:
            return False, "That card can't be used for anticipation!", False

        # Rotate current player to this user
        self._game.current_player = p
        # Now play normally
        return self.play_card(user_id, card_str)

    def play_card(self, user_id: int, card_str: str) -> Tuple[bool, str, bool]:
        """
        Play card_str for user_id.
        Returns (success, message, needs_color_choice).
        """
        if self.game_over:
            return False, "The game is already over.", False
        if user_id != self.current_player_id:
            return False, "It's not your turn!", False
        if self._game.choosing_color:
            return False, "Please choose a color first!", False

        p = self._player_map.get(user_id)
        if not p:
            return False, "You are not in the game.", False

        # Find card object in hand
        card_obj = next((c for c in p.cards if str(c) == card_str), None)
        if card_obj is None:
            return False, "You don't have that card!", False

        playable = p.playable_cards()
        if card_obj not in playable:
            return False, "That card can't be played right now!", False

        # Play it through the Player (which calls Game.play_card internally)
        p.play(card_obj)
        name = self.players.get(user_id, "Player")
        mention = f'<a href="tg://user?id={user_id}">{name}</a>'
        msg_parts = []

        # UNO detection
        if len(p.cards) == 1:
            msg_parts.append("UNO!")

        # Win detection
        if len(p.cards) == 0:
            self.finish_order.append(user_id)
            pts = self._score_from_remaining()
            self.scores[user_id] = pts
            msg_parts.append(f"{mention} won!")

            # Check if only one player remains
            active = [uid for uid, pl in self._player_map.items()
                      if uid not in self.finish_order and len(pl.cards) > 0]
            if len(active) <= 1:
                self.game_over = True
                if active:
                    self.finish_order.append(active[0])
                    self.scores[active[0]] = 0
            
            if self.game_over:
                msg_parts.append("Game ended!")

            return True, "\n".join(msg_parts), False

        return True, "\n".join(msg_parts), self._game.choosing_color

    def choose_color(self, user_id: int, color: str) -> Tuple[bool, str]:
        """Choose a color after playing a Wild or Draw-4."""
        if not self._game.choosing_color:
            return False, "No color choice needed."
        self._game.choose_color(color)   # handles turn advance
        color_name = COLOR_NAMES.get(color, color)
        color_icon = COLOR_ICONS.get(color, "")
        name = self.players.get(user_id, "Player")
        mention = f'<a href="tg://user?id={user_id}">{name}</a>'
        return True, f"{mention} set color to {color_icon} {color_name}"

    def draw_card(self, user_id: int) -> Tuple[bool, str, List[str]]:
        """
        Draw card(s) for user_id.
        If draw_counter > 0 → penalty draw (turn auto-ends).
        Otherwise → draw 1, player may still play it.
        Returns (success, message, list_of_drawn_card_strings).
        """
        if self.game_over:
            return False, "Game is over.", []
        if user_id != self.current_player_id:
            return False, "It's not your turn!", []
        if self._game.choosing_color:
            return False, "Please choose a color first!", []

        p = self._player_map.get(user_id)
        if not p:
            return False, "You are not in the game.", []

        is_penalty = self._game.draw_counter > 0
        before     = len(p.cards)

        try:
            p.draw()
        except DeckEmptyError:
            return False, "No cards left in the deck!", []

        drawn = [str(c) for c in p.cards[before:]]
        n = len(drawn)
        name  = self.players.get(user_id, "Player")
        mention = f'<a href="tg://user?id={user_id}">{name}</a>'
        msg = f"{mention} drew {n} card" if n == 1 else f"{mention} drew {n} cards"

        if is_penalty:
            # House rule: don't end turn after penalty draw
            return (True, msg, drawn)

        # Voluntary draw (Player.draw() already sets self.drew = True)
        return True, msg, drawn

    def pass_turn(self, user_id: int) -> Tuple[bool, str]:
        """Pass turn after a voluntary draw."""
        if user_id != self.current_player_id:
            return False, "It's not your turn!"
        self._game.turn()
        name = self.players.get(user_id, 'Player')
        mention = f'<a href="tg://user?id={user_id}">{name}</a>'
        return True, f"{mention} passed. Next: {self.get_current_player_name()}"

    # ── Scoring / end-game ────────────────────────────────────────────────────

    def _score_from_remaining(self) -> int:
        total = 0
        for uid, p in self._player_map.items():
            if uid in self.finish_order:
                continue
            for card in p.cards:
                if card.special:
                    total += 50
                elif card.value in (_c.DRAW_TWO, _c.REVERSE, _c.SKIP):
                    total += 20
                else:
                    try:
                        total += int(card.value)
                    except (ValueError, TypeError):
                        pass
        return total

    def get_scoreboard(self) -> List[Tuple[int, int]]:
        scored = {uid: self.scores.get(uid, 0) for uid in self.players}
        return sorted(scored.items(), key=lambda x: x[1], reverse=True)

    def get_winners(self) -> List[int]:
        return self.finish_order[:1]
