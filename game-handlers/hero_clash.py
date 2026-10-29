"""
Hero Clash game logic.

Flow
----
1. Players join.
2. Heroes are auctioned one at a time.  Every player starts with a
   100 point budget and every player must end up with exactly 5 heroes.
3. After the draft, the battle phase begins.  There are 5 rounds.  In each
   round every player secretly/publicly sends one unused hero.  All submitted
   heroes fight a free-for-all until one hero survives.
4. The player who wins the most rounds wins the game.  A tie is settled with
   sudden-death rounds (tied players may reuse a hero).

Battle maths (stats, roles, HP, counters, crits, clutch, blaster AoE) are
adapted from `assets/Hero Clash/battle-engine.md`.
"""

from __future__ import annotations

import copy
import csv
import os
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STARTING_BUDGET = 100
HEROES_PER_PLAYER = 5
BATTLE_ROUNDS = 5
MAX_SUDDEN_DEATHS = 3
MAX_BATTLE_WAVES = 80

STAT_WEIGHTS: Dict[str, float] = {
    "strength": 1.20,
    "speed": 1.00,
    "power": 1.30,
    "durability": 0.90,
    "combat": 1.10,
    "intelligence": 0.80,
}

TIER_THRESHOLDS = {"S": 560, "A": 470, "B": 380}

HP_MULTIPLIER = 10
TANK_HP_BONUS = 1.10

COUNTER_BONUS = 1.12
COUNTER_PENALTY = 0.88

VARIANCE_MIN = 0.85
VARIANCE_MAX = 1.15
CRIT_MULTIPLIER = 1.50
CLUTCH_THRESHOLD = 0.25
CLUTCH_MULTIPLIER = 1.10

TANK_THRESHOLD = 160
ASSASSIN_THRESHOLD = 160
BLASTER_THRESHOLD = 85
SUPPORT_THRESHOLD = 80

SUPPORT_BUFF = 1.10
BLASTER_AOE_SPLIT = 0.40
ASSASSIN_DAMAGE_BONUS = 1.15


class Role(str, Enum):
    TANK = "Tank"
    ASSASSIN = "Assassin"
    BLASTER = "Blaster"
    SUPPORT = "Support"
    BRUISER = "Bruiser"


@dataclass
class HeroStats:
    intelligence: int
    strength: int
    speed: int
    durability: int
    power: int
    combat: int


@dataclass
class Hero:
    order: int
    name: str
    team: str
    stats: HeroStats
    card_file: str
    avatar_file: str
    card_file_id: Optional[str] = None

    # Computed battle fields
    base_score: float = 0.0
    role: Role = Role.BRUISER
    max_hp: float = 0.0
    current_hp: float = 0.0
    is_alive: bool = True
    owner_id: Optional[int] = None

    def __post_init__(self) -> None:
        self.base_score = calc_base_score(self.stats)
        self.role = classify_role(self.stats)
        self.max_hp = self.stats.durability * HP_MULTIPLIER
        if self.role == Role.TANK:
            self.max_hp *= TANK_HP_BONUS
        self.current_hp = self.max_hp

    @property
    def hp_pct(self) -> float:
        return self.current_hp / self.max_hp if self.max_hp > 0 else 0.0

    @property
    def tier(self) -> str:
        return assign_tier(self.base_score)

    def stat_line(self) -> str:
        s = self.stats
        return (
            f"STR {s.strength} · SPD {s.speed} · PWR {s.power} · "
            f"DUR {s.durability} · CMB {s.combat} · INT {s.intelligence}"
        )


# ---------------------------------------------------------------------------
# Hero library loading
# ---------------------------------------------------------------------------

def _asset_root() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets",
        "Hero Clash",
    )


def _load_hero_library() -> List[Hero]:
    """Load the manifest and build fresh Hero templates."""
    root = _asset_root()
    cards_dir = os.path.join(root, "cards")
    avatars_dir = os.path.join(root, "avatars")
    manifest_path = os.path.join(cards_dir, "manifest.csv")

    if not os.path.exists(manifest_path):
        return []

    # Avatar files are named by the Superhero API id, e.g. "4-abomination.jpg".
    avatar_by_api_id: Dict[int, str] = {}
    if os.path.isdir(avatars_dir):
        for filename in os.listdir(avatars_dir):
            prefix = filename.split("-", 1)[0]
            if prefix.isdigit():
                avatar_by_api_id[int(prefix)] = filename

    heroes: List[Hero] = []
    with open(manifest_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                stat_values = {
                    "strength": int(row["strength"]),
                    "speed": int(row["speed"]),
                    "power": int(row["power"]),
                    "durability": int(row["durability"]),
                    "combat": int(row["combat"]),
                    "intelligence": int(row["intelligence"]),
                }
                card_file = row["file"]
                api_id = int(card_file.split("_", 1)[1].split("-", 1)[0])
            except (KeyError, ValueError, TypeError, IndexError):
                continue

            avatar_file = avatar_by_api_id.get(api_id, card_file)
            heroes.append(
                Hero(
                    order=int(row["order"]),
                    name=row["name"],
                    team=(row.get("alignment") or "").strip() or "Unknown",
                    stats=HeroStats(**stat_values),
                    card_file=card_file,
                    avatar_file=avatar_file,
                )
            )
    return heroes


# ---------------------------------------------------------------------------
# Battle maths
# ---------------------------------------------------------------------------

def calc_base_score(stats: HeroStats) -> float:
    return sum(
        getattr(stats, stat) * weight
        for stat, weight in STAT_WEIGHTS.items()
    )


def assign_tier(base_score: float) -> str:
    for tier, threshold in TIER_THRESHOLDS.items():
        if base_score >= threshold:
            return tier
    return "C"


def classify_role(stats: HeroStats) -> Role:
    if stats.durability + stats.strength > TANK_THRESHOLD:
        return Role.TANK
    if stats.speed + stats.combat > ASSASSIN_THRESHOLD:
        return Role.ASSASSIN
    if stats.power > BLASTER_THRESHOLD:
        return Role.BLASTER
    if stats.intelligence > SUPPORT_THRESHOLD:
        return Role.SUPPORT
    return Role.BRUISER


_COUNTER_MAP: Dict[Role, Role] = {
    Role.TANK: Role.ASSASSIN,
    Role.ASSASSIN: Role.SUPPORT,
    Role.SUPPORT: Role.TANK,
}


def get_matchup_multiplier(attacker: Hero, defender: Hero) -> float:
    if _COUNTER_MAP.get(attacker.role) == defender.role:
        return COUNTER_BONUS
    if _COUNTER_MAP.get(defender.role) == attacker.role:
        return COUNTER_PENALTY
    return 1.0


def calc_base_damage(attacker: Hero, defender: Hero) -> float:
    offence = (
        attacker.stats.strength * 0.50
        + attacker.stats.power * 0.60
        + attacker.stats.combat * 0.40
    )
    defence = defender.stats.durability * 0.30
    return max(1.0, offence - defence)


def roll_variance(attacker: Hero) -> Tuple[float, bool, bool]:
    base = VARIANCE_MIN + random.random() * (VARIANCE_MAX - VARIANCE_MIN)

    crit_chance = attacker.stats.speed / 1000
    is_crit = random.random() < crit_chance
    crit_mult = CRIT_MULTIPLIER if is_crit else 1.0

    is_clutch = attacker.current_hp < attacker.max_hp * CLUTCH_THRESHOLD
    clutch_mult = CLUTCH_MULTIPLIER if is_clutch else 1.0

    return base * crit_mult * clutch_mult, is_crit, is_clutch


def resolve_damage(attacker: Hero, defender: Hero) -> Tuple[float, bool, bool]:
    base = calc_base_damage(attacker, defender)
    matchup = get_matchup_multiplier(attacker, defender)
    variance, crit, clutch = roll_variance(attacker)
    assassin_bonus = ASSASSIN_DAMAGE_BONUS if attacker.role == Role.ASSASSIN else 1.0
    return base * matchup * variance * assassin_bonus, crit, clutch


def _apply_damage(hero: Hero, damage: float) -> float:
    before = hero.current_hp
    hero.current_hp = max(0.0, before - damage)
    if hero.current_hp <= 0.0:
        hero.is_alive = False
    return before - hero.current_hp


def _select_target(attacker: Hero, heroes: List[Hero]) -> Optional[Hero]:
    enemies = [h for h in heroes if h is not attacker and h.is_alive]
    if not enemies:
        return None

    tanks = [h for h in enemies if h.role == Role.TANK]
    non_tanks = [h for h in enemies if h.role != Role.TANK]
    pool = tanks if tanks else non_tanks

    if attacker.role == Role.ASSASSIN:
        supports = [h for h in pool if h.role == Role.SUPPORT]
        if supports:
            return min(supports, key=lambda h: h.current_hp)
        return min(pool, key=lambda h: h.current_hp)

    if attacker.role == Role.SUPPORT:
        return min(pool, key=lambda h: h.current_hp)

    # Tank, Bruiser and Blaster fallback
    return max(pool, key=lambda h: h.base_score)


def run_ffa(combatants: List[Tuple[Hero, int]]) -> Tuple[Hero, List[str], Dict[int, float]]:
    """Run a free-for-all between the submitted heroes.

    `combatants` is a list of (hero, owner_id).  Heroes are mutated in place,
    so callers should pass copies.
    """
    heroes = [hero for hero, _ in combatants]
    damage_by_owner: Dict[int, float] = {owner: 0.0 for _, owner in combatants}

    for hero in heroes:
        hero.is_alive = True
        hero.current_hp = hero.max_hp

    log: List[str] = []
    wave = 0

    while sum(1 for h in heroes if h.is_alive) > 1 and wave < MAX_BATTLE_WAVES:
        wave += 1
        log.append(f"— Wave {wave} —")
        order = sorted(
            [h for h in heroes if h.is_alive],
            key=lambda h: (
                h.stats.speed + (0.5 if h.role == Role.ASSASSIN else 0.0),
                h.stats.power,
            ),
            reverse=True,
        )

        for hero in order:
            if not hero.is_alive:
                continue
            enemies = [h for h in heroes if h is not hero and h.is_alive]
            if not enemies:
                break

            if hero.role == Role.BLASTER:
                for enemy in enemies:
                    if not enemy.is_alive:
                        continue
                    raw, is_crit, is_clutch = resolve_damage(hero, enemy)
                    damage = raw * BLASTER_AOE_SPLIT
                    actual = _apply_damage(enemy, damage)
                    damage_by_owner[hero.owner_id] = (
                        damage_by_owner.get(hero.owner_id, 0.0) + actual
                    )
                    tags = " [AOE]"
                    if is_crit:
                        tags += " [CRIT]"
                    if is_clutch:
                        tags += " [CLUTCH]"
                    log.append(
                        f"{hero.name} -> {enemy.name}: {actual:.0f} dmg{tags} "
                        f"({enemy.name} {enemy.current_hp:.0f} HP)"
                    )
                    if not enemy.is_alive:
                        log.append(f"*** {enemy.name} eliminated! ***")
            else:
                target = _select_target(hero, heroes)
                if target is None:
                    continue
                raw, is_crit, is_clutch = resolve_damage(hero, target)
                actual = _apply_damage(target, raw)
                damage_by_owner[hero.owner_id] = (
                    damage_by_owner.get(hero.owner_id, 0.0) + actual
                )
                tags = ""
                if is_crit:
                    tags += " [CRIT]"
                if is_clutch:
                    tags += " [CLUTCH]"
                log.append(
                    f"{hero.name} -> {target.name}: {actual:.0f} dmg{tags} "
                    f"({target.name} {target.current_hp:.0f} HP)"
                )
                if not target.is_alive:
                    log.append(f"*** {target.name} eliminated! ***")

    alive = [h for h in heroes if h.is_alive]
    if len(alive) == 1:
        winner = alive[0]
    elif alive:
        winner = max(alive, key=lambda h: (h.hp_pct, h.base_score))
    else:
        winner = max(heroes, key=lambda h: h.base_score)

    if wave >= MAX_BATTLE_WAVES and len(alive) > 1:
        log.append("*** Wave limit reached — highest remaining HP wins! ***")

    return winner, log, damage_by_owner


# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------

class HeroClashGame:
    """State + rules for one Hero Clash match."""

    def __init__(self):
        self.players: Dict[int, str] = {}
        self.budgets: Dict[int, int] = {}
        self.rosters: Dict[int, List[Hero]] = {}

        self.phase = "lobby"  # lobby | auction | battle_ready | battle | sudden_death | finished
        self._pool: List[Hero] = []

        # Auction state
        self.auction_num = 0
        self.current_auction_id = 0
        self.current_hero: Optional[Hero] = None
        self.current_bids: Dict[int, int] = {}
        self.card_file_ids: Dict[int, str] = {}
        self.auction_deadline = 0.0

        # Battle state
        self.round_num = 0
        self.wins: Dict[int, int] = {}
        self.total_damage: Dict[int, float] = {}
        self.used_orders: Dict[int, set] = {}
        self.battle_picks: Dict[int, Hero] = {}
        self.required_pickers: List[int] = []
        self.battle_token = 0
        self.battle_resolving = False
        self.battle_deadline = 0.0
        self.sudden_death_count = 0
        self.round_results: List[dict] = []
        self.winner_id: Optional[int] = None

    # -- Lobby ------------------------------------------------------------
    def add_player(self, user_id: int, display_name: str) -> None:
        self.players[user_id] = display_name
        self.budgets.setdefault(user_id, STARTING_BUDGET)
        self.rosters.setdefault(user_id, [])
        self.wins.setdefault(user_id, 0)
        self.total_damage.setdefault(user_id, 0.0)
        self.used_orders.setdefault(user_id, set())

    def remove_player(self, user_id: int) -> None:
        self.players.pop(user_id, None)
        self.budgets.pop(user_id, None)
        self.rosters.pop(user_id, None)
        self.wins.pop(user_id, None)
        self.total_damage.pop(user_id, None)
        self.used_orders.pop(user_id, None)
        self.current_bids.pop(user_id, None)
        self.battle_picks.pop(user_id, None)
        self.required_pickers = [p for p in self.required_pickers if p != user_id]
        if len(self.players) < 2 and self.phase in ("auction", "battle_ready", "battle", "sudden_death"):
            self.phase = "finished"

    def get_player_count(self) -> int:
        return len(self.players)

    # -- Draft / auction --------------------------------------------------
    def start_game(self) -> bool:
        if len(self.players) < 2:
            return False
        if not HERO_TEMPLATES:
            return False

        self._pool = copy.deepcopy(HERO_TEMPLATES)
        random.shuffle(self._pool)

        self.budgets = {uid: STARTING_BUDGET for uid in self.players}
        self.rosters = {uid: [] for uid in self.players}
        self.wins = {uid: 0 for uid in self.players}
        self.total_damage = {uid: 0.0 for uid in self.players}
        self.used_orders = {uid: set() for uid in self.players}
        self.current_bids = {}
        self.current_hero = None
        self.card_file_ids = {}
        self.auction_deadline = 0.0
        self.phase = "auction"
        self.auction_num = 0
        self.current_auction_id = 0
        self.round_num = 0
        self.battle_picks = {}
        self.required_pickers = []
        self.round_results = []
        self.sudden_death_count = 0
        self.winner_id = None
        self.battle_resolving = False
        self.battle_deadline = 0.0
        self.battle_token = 0
        return True

    def active_bidders(self) -> List[int]:
        return [
            uid for uid in self.players
            if len(self.rosters.get(uid, [])) < HEROES_PER_PLAYER
        ]

    def max_bid(self, user_id: int) -> int:
        """Highest legal bid, reserving 1 point per remaining hero slot."""
        slots_left = HEROES_PER_PLAYER - len(self.rosters.get(user_id, []))
        if slots_left <= 0:
            return 0
        remaining = self.budgets.get(user_id, 0)
        reserve = max(0, slots_left - 1)
        return max(0, remaining - reserve)

    def is_drafted(self) -> bool:
        return all(
            len(self.rosters.get(uid, [])) >= HEROES_PER_PLAYER
            for uid in self.players
        )

    def next_auction(self, duration: float = 0.0) -> Optional[Hero]:
        active = self.active_bidders()
        if not active or not self._pool:
            return None

        hero = self._pool.pop()
        self.current_hero = hero
        self.current_bids = {}
        self.current_auction_id += 1
        self.auction_num += 1
        self.auction_deadline = time.monotonic() + max(0.0, duration)
        self.phase = "auction"
        return hero

    def auction_seconds_left(self) -> float:
        if self.phase != "auction" or self.auction_deadline <= 0:
            return 0.0
        return max(0.0, self.auction_deadline - time.monotonic())

    def extend_auction(self, seconds: float) -> None:
        if self.phase == "auction" and self.auction_deadline > 0:
            self.auction_deadline += max(0.0, seconds)

    def place_bid(self, user_id: int, amount: int, auction_id: Optional[int] = None) -> Tuple[bool, str]:
        if auction_id is not None and auction_id != self.current_auction_id:
            return False, "That auction has already ended."
        if self.phase != "auction" or self.current_hero is None:
            return False, "Bidding is not open right now."
        if self.auction_seconds_left() <= 0:
            return False, "Bidding has closed for this hero."
        if user_id not in self.players:
            return False, "You are not in this game."
        if user_id not in self.active_bidders():
            return False, "You already have 5 heroes."
        if amount < 1:
            return False, "Your bid must be at least 1 point."

        max_bid = self.max_bid(user_id)
        if max_bid <= 0:
            return False, "You do not have enough budget to bid."
        if amount > max_bid:
            return False, (
                f"Your maximum bid is {max_bid} points. "
                f"You must keep at least 1 point for each hero slot still open."
            )

        self.current_bids[user_id] = amount
        return True, f"Bid of {amount} points registered."

    def close_auction(self) -> Optional[dict]:
        if self.phase != "auction" or self.current_hero is None:
            return None

        active = self.active_bidders()
        if not active:
            self.current_hero = None
            self.current_bids = {}
            self.auction_deadline = 0.0
            return None

        bids = {
            uid: amount
            for uid, amount in self.current_bids.items()
            if uid in active
        }

        tied = []
        if bids:
            highest = max(bids.values())
            tied = [uid for uid, amount in bids.items() if amount == highest]
            winner = random.choice(tied)
            price = highest
        else:
            # Nobody bid: skip this hero instead of giving it away for free.
            hero = self.current_hero
            self.current_hero = None
            self.current_bids = {}
            self.auction_deadline = 0.0
            return {
                "hero": hero,
                "winner_id": None,
                "price": 0,
                "tied": [],
                "is_auto": False,
                "is_skip": True,
                "budget_left": 0,
                "roster_size": 0,
                "drafted": self.is_drafted(),
            }

        price = max(0, min(price, self.max_bid(winner)))
        self.budgets[winner] -= price

        hero = self.current_hero
        hero.owner_id = winner
        self.rosters[winner].append(hero)
        self.current_hero = None
        self.current_bids = {}
        self.auction_deadline = 0.0

        if self.is_drafted():
            self.phase = "battle_ready"

        return {
            "hero": hero,
            "winner_id": winner,
            "price": price,
            "tied": tied,
            "is_auto": False,
            "is_skip": False,
            "budget_left": self.budgets[winner],
            "roster_size": len(self.rosters[winner]),
            "drafted": self.is_drafted(),
        }

    # -- Battle -----------------------------------------------------------
    def begin_battle(self) -> None:
        self.phase = "battle"
        self.round_num = 1
        self.battle_picks = {}
        self.required_pickers = list(self.players.keys())
        self.battle_resolving = False
        self.battle_deadline = 0.0
        self.sudden_death_count = 0
        self.battle_token += 1
        for uid in self.players:
            self.used_orders[uid] = set()

    def start_battle_round(self, duration: float = 0.0) -> bool:
        if self.phase not in ("battle", "sudden_death"):
            return False
        self.battle_picks = {}
        self.battle_resolving = False
        self.battle_deadline = time.monotonic() + max(0.0, duration)
        self.battle_token += 1
        return True

    def battle_seconds_left(self) -> float:
        if self.phase not in ("battle", "sudden_death") or self.battle_deadline <= 0:
            return 0.0
        return max(0.0, self.battle_deadline - time.monotonic())

    def extend_battle(self, seconds: float) -> None:
        if (
            self.phase in ("battle", "sudden_death")
            and self.battle_deadline > 0
            and not self.battle_resolving
        ):
            self.battle_deadline += max(0.0, seconds)

    def available_heroes(self, user_id: int) -> List[Hero]:
        roster = self.rosters.get(user_id, [])
        if self.phase == "sudden_death":
            return list(roster)
        used = self.used_orders.get(user_id, set())
        return [hero for hero in roster if hero.order not in used]

    def submit_pick(self, user_id: int, hero_order: int, battle_token: Optional[int] = None) -> Tuple[bool, str]:
        if battle_token is not None and battle_token != self.battle_token:
            return False, "That battle round has already moved on."
        if self.phase not in ("battle", "sudden_death"):
            return False, "The battle is not accepting picks right now."
        if user_id not in self.required_pickers:
            return False, "You do not need to pick a hero for this battle."
        if self.battle_resolving:
            return False, "This round is already being resolved."

        hero = next(
            (h for h in self.rosters.get(user_id, []) if h.order == hero_order),
            None,
        )
        if hero is None:
            return False, "You do not own that hero."

        if self.phase == "battle" and hero.order in self.used_orders.get(user_id, set()):
            return False, "That hero has already fought. Pick an unused hero."

        changed = user_id in self.battle_picks
        self.battle_picks[user_id] = hero
        return True, (
            f"Hero changed to {hero.name}."
            if changed
            else f"{hero.name} locked in for this round."
        )

    def all_picks_in(self) -> bool:
        return bool(self.required_pickers) and all(
            uid in self.battle_picks for uid in self.required_pickers
        )

    def auto_pick_missing(self) -> List[Tuple[int, Hero]]:
        auto_picked: List[Tuple[int, Hero]] = []
        for uid in self.required_pickers:
            if uid in self.battle_picks:
                continue
            choices = self.available_heroes(uid)
            if not choices:
                choices = list(self.rosters.get(uid, []))
            if not choices:
                continue
            hero = random.choice(choices)
            self.battle_picks[uid] = hero
            auto_picked.append((uid, hero))
        return auto_picked

    def _resolve_tie_or_finish(self) -> None:
        standings = self.get_standings()
        if not standings:
            self.phase = "finished"
            self.required_pickers = []
            return

        top_wins = self.wins[standings[0]]
        tied = [uid for uid in standings if self.wins[uid] == top_wins]

        if len(tied) == 1:
            self.winner_id = tied[0]
            self.phase = "finished"
            self.required_pickers = []
            return

        if self.sudden_death_count >= MAX_SUDDEN_DEATHS:
            self.winner_id = max(tied, key=lambda uid: self.total_damage.get(uid, 0.0))
            self.phase = "finished"
            self.required_pickers = []
            return

        self.sudden_death_count += 1
        self.phase = "sudden_death"
        self.required_pickers = tied

    def resolve_battle_round(self) -> Optional[dict]:
        if self.battle_resolving or not self.all_picks_in():
            return None

        self.battle_resolving = True
        was_phase = self.phase
        was_round = self.round_num

        combatants: List[Tuple[Hero, int]] = []
        picked_orders: Dict[int, int] = {}
        for uid in self.required_pickers:
            hero = self.battle_picks[uid]
            picked_orders[uid] = hero.order
            combatants.append((copy.deepcopy(hero), uid))

        winner_hero, log_lines, damage_by_owner = run_ffa(combatants)
        winner_id = winner_hero.owner_id

        for uid, order in picked_orders.items():
            if was_phase == "battle":
                self.used_orders.setdefault(uid, set()).add(order)

        self.wins[winner_id] = self.wins.get(winner_id, 0) + 1
        for uid, damage in damage_by_owner.items():
            self.total_damage[uid] = self.total_damage.get(uid, 0.0) + damage

        if was_phase == "sudden_death":
            label = f"Sudden Death {self.sudden_death_count}"
        else:
            label = f"Round {was_round}"

        result = {
            "label": label,
            "round": was_round,
            "is_sudden_death": was_phase == "sudden_death",
            "winner_id": winner_id,
            "winner_hero": winner_hero.name,
            "log_lines": log_lines,
            "damage": damage_by_owner,
            "picks": {
                uid: next(
                    (h.name for h in self.rosters[uid] if h.order == order),
                    "Unknown",
                )
                for uid, order in picked_orders.items()
            },
            "wins": dict(self.wins),
        }

        self.battle_picks = {}
        self.battle_deadline = 0.0

        if was_phase == "battle" and was_round >= BATTLE_ROUNDS:
            self.round_num = BATTLE_ROUNDS
            self._resolve_tie_or_finish()
        elif was_phase == "battle":
            self.round_num = was_round + 1
        else:
            self._resolve_tie_or_finish()

        result["phase"] = self.phase
        result["next_round"] = self.round_num
        result["required_pickers"] = list(self.required_pickers)
        result["sudden_death_count"] = self.sudden_death_count
        self.round_results.append(result)
        self.battle_resolving = False
        return result

    # -- Results ----------------------------------------------------------
    def get_standings(self) -> List[int]:
        return sorted(
            self.players.keys(),
            key=lambda uid: (
                -self.wins.get(uid, 0),
                -self.total_damage.get(uid, 0.0),
                self.players.get(uid, "").lower(),
            ),
        )

    def get_scoreboard(self) -> List[Tuple[int, int]]:
        return [(uid, self.wins.get(uid, 0)) for uid in self.get_standings()]

    def get_winner(self) -> Optional[int]:
        if self.winner_id is not None:
            return self.winner_id
        standings = self.get_standings()
        return standings[0] if standings else None

    @property
    def total_rounds(self) -> int:
        return BATTLE_ROUNDS

    @property
    def current_round(self) -> int:
        return self.round_num

    def get_final_summary(self, escape) -> str:
        """Build the final HTML summary. `escape` is html.escape."""
        standings = self.get_standings()
        winner = self.get_winner()

        def mention(uid: int) -> str:
            name = escape(self.players.get(uid, "Player"))
            return f'<a href="tg://user?id={uid}">{name}</a>'

        lines: List[str] = ["🏆 <b>HERO CLASH — FINAL RESULT</b>", ""]

        if winner is not None:
            lines.append(
                f"🎉 <b>{mention(winner)} wins with "
                f"{self.wins.get(winner, 0)} round wins!</b>"
            )
        else:
            lines.append("No winner could be determined.")

        if self.sudden_death_count:
            lines.append(
                f"<i>Decided after {self.sudden_death_count} sudden-death "
                f"round{'s' if self.sudden_death_count != 1 else ''}.</i>"
            )

        lines.append("")
        lines.append("<blockquote><b>Standings</b>")
        for rank, uid in enumerate(standings, 1):
            wins = self.wins.get(uid, 0)
            damage = self.total_damage.get(uid, 0.0)
            hero_count = len(self.rosters.get(uid, []))
            lines.append(
                f"{rank}. {mention(uid)} — <b>{wins}</b> wins · "
                f"{damage:.0f} damage · {hero_count}/5 heroes"
            )
        lines.append("</blockquote>")

        if self.round_results:
            lines.append("")
            lines.append("<blockquote expandable><b>Round winners</b>")
            for result in self.round_results:
                wname = self.players.get(result["winner_id"], "Player")
                lines.append(
                    f"{escape(result['label'])} — {mention(result['winner_id'])} "
                    f"({escape(result['winner_hero'])})"
                )
            lines.append("</blockquote>")

        lines.append("")
        lines.append("<i>use /start for a new game.</i>")
        return "\n".join(lines)


# Loaded last so Hero.__post_init__ can use the battle-maths helpers above.
HERO_TEMPLATES: List[Hero] = _load_hero_library()
