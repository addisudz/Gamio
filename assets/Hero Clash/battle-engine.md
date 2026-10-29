# Battle Engine — Full Technical Specification (Python)

> Marvel Hero Battle System · v1.0  
> Stats source: Superhero API · 302 characters · 6 stats per hero  
> Python 3.10+ · zero external dependencies

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Data Models](#2-data-models)
3. [Stat Weights & Base Score](#3-stat-weights--base-score)
4. [Role Classification](#4-role-classification)
5. [HP & Survivability](#5-hp--survivability)
6. [Team Score (Multi-Hero)](#6-team-score-multi-hero)
7. [Matchup Matrix](#7-matchup-matrix)
8. [Budget Bonus](#8-budget-bonus)
9. [Battle Modes](#9-battle-modes)
10. [Round Loop](#10-round-loop)
11. [Variance Engine (RNG)](#11-variance-engine-rng)
12. [Targeting Logic](#12-targeting-logic)
13. [Win Condition & Output](#13-win-condition--output)
14. [Battle Log Schema](#14-battle-log-schema)
15. [Constants Reference](#15-constants-reference)
16. [Connecting to the Superhero API](#16-connecting-to-the-superhero-api)
17. [Full Pseudocode](#17-full-pseudocode)

---

## 1. Project Structure

```
battle_engine/
├── __init__.py       # public exports
├── constants.py      # all tunable numbers
├── models.py         # dataclasses: Hero, Player, BattleResult, LogEntry
└── engine.py         # all logic functions + run_battle()
```

No third-party packages required. Uses only:
- `dataclasses` — models
- `enum` — Role and BattleMode
- `random` — variance rolls
- `collections.Counter` — synergy detection

---

## 2. Data Models

```python
# models.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Role(str, Enum):
    TANK     = "Tank"
    ASSASSIN = "Assassin"
    BLASTER  = "Blaster"
    SUPPORT  = "Support"
    BRUISER  = "Bruiser"


class BattleMode(str, Enum):
    DUEL = "1v1"
    TEAM = "team"
    FFA  = "ffa"


@dataclass
class HeroStats:
    intelligence: int   # 0–100
    strength:     int   # 0–100
    speed:        int   # 0–100
    durability:   int   # 0–100
    power:        int   # 0–100
    combat:       int   # 0–100


@dataclass
class Hero:
    id:           int
    name:         str
    team:         str           # affiliation from API e.g. "Avengers"
    stats:        HeroStats

    # computed at battle init — do not set manually
    base_score:   float = 0.0
    role:         Role  = Role.BRUISER
    max_hp:       float = 0.0
    current_hp:   float = 0.0
    is_alive:     bool  = True

    # internal Support buff tracking
    _support_buff_active: bool  = field(default=False, repr=False)
    _pre_buff_score:      float = field(default=0.0,   repr=False)

    @property
    def hp_pct(self) -> float:
        """Current HP as a fraction of max HP (0.0–1.0)."""
        return self.current_hp / self.max_hp if self.max_hp > 0 else 0.0


@dataclass
class Player:
    id:            str
    heroes:        list[Hero] = field(default_factory=list)
    draft_budget:  int  = 100
    spent_budget:  int  = 0
    is_eliminated: bool = False

    # set by engine at init — do not set manually
    _team_score:   float = field(default=0.0, repr=False)

    @property
    def remaining_budget(self) -> int:
        return self.draft_budget - self.spent_budget

    @property
    def alive_heroes(self) -> list[Hero]:
        return [h for h in self.heroes if h.is_alive]

    @property
    def team_score(self) -> float:
        return self._team_score

    @team_score.setter
    def team_score(self, value: float) -> None:
        self._team_score = value


@dataclass
class LogEntry:
    type:   str
    round:  int
    data:   dict = field(default_factory=dict)


@dataclass
class BattleResult:
    winner:           Optional[Player]
    mvp_hero:         str
    mvp_damage:       float
    is_upset:         bool
    rounds_played:    int
    log:              list[LogEntry]
    player_summaries: list[dict]
```

### Why these models?

`Hero` keeps both raw API stats (`HeroStats`) and computed battle fields (`base_score`, `role`, `max_hp`) on the same object. This means every targeting and damage function only needs the hero — no external lookups.

`Player.remaining_budget` is a computed property so it stays in sync automatically as `spent_budget` is updated during the auction draft.

`_support_buff_active` and `_pre_buff_score` use the `field(repr=False)` convention so they are hidden from `print()` output but still accessible internally. Support buffs must be reverted at the end of every round — these fields make that safe.

---

## 3. Stat Weights & Base Score

The six stats are not equally useful in a fight. Power dominates because cosmic and energy abilities define Marvel combat at the high end. Intelligence is penalised slightly because it enables team effects (Support role) rather than direct damage.

```python
# constants.py
STAT_WEIGHTS: dict[str, float] = {
    "strength":     1.20,
    "speed":        1.00,
    "power":        1.30,
    "durability":   0.90,
    "combat":       1.10,
    "intelligence": 0.80,
}
```

```python
# engine.py
from .constants import STAT_WEIGHTS
from .models import HeroStats

def calc_base_score(stats: HeroStats) -> float:
    """
    Weighted sum across all six stats.
    Maximum possible score (all stats = 100):
        100 × (1.20 + 1.00 + 1.30 + 0.90 + 1.10 + 0.80) = 630
    """
    return sum(
        getattr(stats, stat) * weight
        for stat, weight in STAT_WEIGHTS.items()
    )
```

**Weight rationale:**

| Stat | Weight | Reason |
|---|---|---|
| Power | 1.30 | Energy / cosmic abilities dominate at top tier |
| Strength | 1.20 | Direct physical damage |
| Combat | 1.10 | Skill multiplies every other offensive stat |
| Speed | 1.00 | Sets turn order; balanced offence/defence |
| Durability | 0.90 | Defensive only — reduces incoming damage, not output |
| Intelligence | 0.80 | Indirect; drives Support synergy bonuses instead |

**Tier thresholds** (for post-draft display):

```python
# constants.py
TIER_THRESHOLDS = {"S": 560, "A": 470, "B": 380}   # below 380 → "C"

# engine.py
def assign_tier(base_score: float) -> str:
    for tier, threshold in TIER_THRESHOLDS.items():
        if base_score >= threshold:
            return tier
    return "C"
```

Real examples from the API data:

| Hero | Score | Tier |
|---|---|---|
| Thor | 597 | S |
| Thanos | 558 | A |
| Iron Man | 517 | A |
| Storm | 379 | C |
| Black Widow | 262 | C |

---

## 4. Role Classification

Roles are assigned automatically at battle initialisation from raw stats. Priority order matters — the first condition that matches wins.

```python
# constants.py
TANK_THRESHOLD     = 160   # DUR + STR
ASSASSIN_THRESHOLD = 160   # SPD + CMB
BLASTER_THRESHOLD  = 85    # POW
SUPPORT_THRESHOLD  = 80    # INT
```

```python
# engine.py
from .models import HeroStats, Role
from .constants import (
    TANK_THRESHOLD, ASSASSIN_THRESHOLD,
    BLASTER_THRESHOLD, SUPPORT_THRESHOLD,
)

def classify_role(stats: HeroStats) -> Role:
    """
    Priority order:
      1. Tank     — high physical durability
      2. Assassin — high speed + combat skill
      3. Blaster  — high raw power (energy / cosmic)
      4. Support  — high intelligence
      5. Bruiser  — default; no special conditions met
    """
    s = stats
    if s.durability + s.strength > TANK_THRESHOLD:      return Role.TANK
    if s.speed      + s.combat   > ASSASSIN_THRESHOLD:  return Role.ASSASSIN
    if s.power                   > BLASTER_THRESHOLD:   return Role.BLASTER
    if s.intelligence            > SUPPORT_THRESHOLD:   return Role.SUPPORT
    return Role.BRUISER
```

**Role behaviours in battle:**

| Role | Passive | Turn-order effect | Targeting |
|---|---|---|---|
| Tank | +10% max HP; absorbs hits before teammates | Normal | Targeted last by enemies |
| Assassin | +15% damage to single targets | Acts first (highest SPD bonus) | Hunts Support first, then lowest HP |
| Blaster | Hits all enemies at 40% power each | Normal | Targets highest-HP enemy |
| Support | Buffs highest-score teammate +10% each round | Normal | Targeted first by Assassins |
| Bruiser | None | Normal | Targets highest base score |

---

## 5. HP & Survivability

HP is derived from Durability. A hero is eliminated the moment `current_hp` hits zero — there is no negative HP state.

```python
# constants.py
HP_MULTIPLIER  = 10     # durability × 10 = max HP
TANK_HP_BONUS  = 1.10   # Tanks get +10% effective HP
```

```python
# engine.py
from .constants import HP_MULTIPLIER, TANK_HP_BONUS

def init_hero(hero: Hero) -> None:
    """
    Compute all derived fields and reset HP.
    Must be called on every hero before run_battle().
    """
    hero.base_score = calc_base_score(hero.stats)
    hero.role       = classify_role(hero.stats)
    hero.max_hp     = hero.stats.durability * HP_MULTIPLIER
    if hero.role == Role.TANK:
        hero.max_hp *= TANK_HP_BONUS    # e.g. DUR 100 → 1100 HP instead of 1000
    hero.current_hp           = hero.max_hp
    hero.is_alive             = True
    hero._support_buff_active = False
    hero._pre_buff_score      = hero.base_score
```

**Damage formula:**

Base damage is calculated from the attacker's offensive stats against the defender's durability. This is the raw number before matchup multipliers and variance.

```python
def calc_base_damage(attacker: Hero, defender: Hero) -> float:
    """
    Offence:  STR contributes 50%, POW 60%, CMB 40%
    Defence:  DUR reduces damage at 30%
    Floor:    always at least 1 damage per hit
    """
    offence = (
        attacker.stats.strength * 0.50 +
        attacker.stats.power    * 0.60 +
        attacker.stats.combat   * 0.40
    )
    defence = defender.stats.durability * 0.30
    return max(1.0, offence - defence)


def apply_damage(hero: Hero, damage: float) -> None:
    hero.current_hp = max(0.0, hero.current_hp - damage)
    if hero.current_hp == 0.0:
        hero.is_alive = False
```

---

## 6. Team Score (Multi-Hero)

When a player fields a roster of multiple heroes the combined score is not a plain sum. Two forces interact: synergy rewards coordinated rosters, size penalty reflects coordination cost.

```python
# constants.py
SYNERGY_BONUS: dict[int, float] = {
    1: 1.00,
    2: 1.08,    # +8%
    3: 1.14,    # +14%
    4: 1.18,    # +18%
    5: 1.22,    # +22%
}

SIZE_PENALTY: dict[int, float] = {
    1: 1.00,
    2: 0.97,    # −3%
    3: 0.94,    # −6%
    4: 0.91,    # −9%
    5: 0.88,    # −12%
}
```

```python
# engine.py
from collections import Counter
from .constants import SYNERGY_BONUS, SIZE_PENALTY

def get_synergy_multiplier(heroes: list[Hero]) -> float:
    """
    Full synergy bonus applies when the majority of alive heroes
    share a team affiliation (e.g. all Avengers).
    No shared affiliation → only half the bonus is granted.
    """
    alive = [h for h in heroes if h.is_alive]
    n     = len(alive)
    if n <= 1:
        return 1.0

    teams = [h.team for h in alive if h.team]
    if not teams:
        return 1.0

    most_common_count = Counter(teams).most_common(1)[0][1]
    majority_share    = most_common_count >= (n // 2 + 1)

    raw = SYNERGY_BONUS.get(n, SYNERGY_BONUS[5])
    return raw if majority_share else 1.0 + (raw - 1.0) * 0.5


def calc_team_score(heroes: list[Hero]) -> float:
    """
    Final formula:
        team_score = sum(base_scores) × synergy_mult × size_penalty
    """
    alive = [h for h in heroes if h.is_alive]
    n     = len(alive)
    if n == 0:
        return 0.0
    if n == 1:
        return alive[0].base_score

    base_sum = sum(h.base_score for h in alive)
    synergy  = get_synergy_multiplier(alive)
    penalty  = SIZE_PENALTY.get(n, SIZE_PENALTY[5])
    return base_sum * synergy * penalty
```

**Net effect of synergy vs penalty:**

A perfectly synergised 3-hero Avengers team scores `(sum) × 1.14 × 0.94 = (sum) × 1.071` — a 7% net gain over a solo hero at the same sum. A random trio with no shared affiliation scores `(sum) × 1.07 × 0.94 = (sum) × 1.005` — nearly neutral, making strong individual heroes the safer pick.

---

## 7. Matchup Matrix

Roles counter each other in a three-way cycle. When the attacker counters the defender's role, all damage dealt is multiplied. When countered, it is reduced.

```
Tank     beats  Assassin   (Tanks absorb fast attacks)
Assassin beats  Support    (Speed overwhelms intelligence)
Support  beats  Tank       (Tactics and buffs outpace brute force)

Blaster  — neutral against all roles
Bruiser  — neutral against all roles
```

```python
# constants.py
COUNTER_BONUS   = 1.12   # +12% damage when countering
COUNTER_PENALTY = 0.88   # −12% damage when being countered
```

```python
# engine.py
from .models import Role
from .constants import COUNTER_BONUS, COUNTER_PENALTY

_COUNTER_MAP: dict[Role, Role] = {
    Role.TANK:     Role.ASSASSIN,
    Role.ASSASSIN: Role.SUPPORT,
    Role.SUPPORT:  Role.TANK,
}

def get_matchup_multiplier(attacker: Hero, defender: Hero) -> float:
    """
    Returns a damage multiplier based on role counters.
    1.12 → attacker counters defender
    0.88 → attacker is countered by defender
    1.00 → neutral (Blaster, Bruiser, or same role)
    """
    if _COUNTER_MAP.get(attacker.role) == defender.role:
        return COUNTER_BONUS
    if _COUNTER_MAP.get(defender.role) == attacker.role:
        return COUNTER_PENALTY
    return 1.0
```

---

## 8. Budget Bonus

Unspent auction budget converts to a small team-score multiplier at draft close. Being frugal is mildly rewarded, but buying stronger heroes always wins.

```python
# constants.py
BUDGET_BONUS_DIVISOR = 1000
# 100 coins unspent → +10% bonus (maximum possible)
# 20  coins unspent → +2%  bonus (typical frugal player)
# 0   coins unspent → +0%  bonus
```

```python
# engine.py
from .constants import BUDGET_BONUS_DIVISOR

def calc_budget_bonus(remaining_budget: int) -> float:
    """Applied once to team_score at battle init."""
    return 1.0 + (remaining_budget / BUDGET_BONUS_DIVISOR)
```

Applied in the init phase:

```python
player.team_score = (
    calc_team_score(player.heroes) *
    calc_budget_bonus(player.remaining_budget)
)
```

---

## 9. Battle Modes

### 9.1 — 1v1 Duel (`BattleMode.DUEL`)

Two players, one hero each. The hero with higher `speed` attacks first in every round. Speed ties are broken by a coin flip at init — the advantage is fixed for the whole duel.

No team mechanics. No synergy. No Support buffs. The Blaster AoE still fires, but with only one target it is effectively a single-target attack.

### 9.2 — Team Battle (`BattleMode.TEAM`)

Two players, each with up to 5 heroes. Heroes fight as a collective.

Key mechanics that activate:
- Support buffs the strongest teammate at round start.
- Tank heroes must be killed before other teammates can be targeted.
- A player loses when all their heroes are eliminated.

### 9.3 — Free-For-All (`BattleMode.FFA`)

2–8 players, each with up to 5 heroes. All players fight simultaneously.

Turn order each round: every alive hero across all active players sorted by `speed` descending. Each hero attacks the strongest enemy (by `base_score`) unless their role overrides targeting. A player is eliminated when all their heroes are dead. Last player standing wins.

---

## 10. Round Loop

This loop runs identically for all three modes. The only difference is how `select_target` and `get_enemy_heroes` resolve — they use `owner` to exclude friendly heroes.

```python
# engine.py
import random
from .constants import MAX_ROUNDS

def run_battle(players: list[Player], mode: BattleMode) -> BattleResult:
    log: list[LogEntry] = []

    # ── Phase 1: Initialise ───────────────────────────────────────────────
    for player in players:
        for hero in player.heroes:
            init_hero(hero)
        player.team_score = (
            calc_team_score(player.heroes) *
            calc_budget_bonus(player.remaining_budget)
        )

    round_num = 0

    # ── Phase 2: Round loop ───────────────────────────────────────────────
    while not _is_battle_over(players) and round_num < MAX_ROUNDS:
        round_num += 1
        log.append(LogEntry(type="round_start", round=round_num))

        # Apply Support buffs at round start
        for player in _active_players(players):
            _apply_support_buffs(player.heroes, log, round_num)

        # Build turn order: all alive heroes sorted by speed, fastest first
        turn_order = _build_turn_order(players)

        for hero, owner in turn_order:
            if not hero.is_alive:
                continue

            if hero.role == Role.BLASTER:
                _resolve_blaster_aoe(hero, owner, players, log, round_num)
            else:
                target = select_target(hero, owner, players)
                if target is None:
                    continue
                _resolve_single_attack(hero, target, log, round_num)

        # Revert Support buffs at round end
        for player in _active_players(players):
            _revert_support_buffs(player.heroes)

        # Check for newly eliminated players
        for player in players:
            if not player.is_eliminated and not player.alive_heroes:
                player.is_eliminated = True
                log.append(LogEntry(
                    type="player_eliminated",
                    round=round_num,
                    data={"player_id": player.id},
                ))

    # ── Phase 3: Result ───────────────────────────────────────────────────
    return _build_result(players, log, round_num)
```

**Helper: active players**

```python
def _active_players(players: list[Player]) -> list[Player]:
    return [p for p in players if not p.is_eliminated]


def _is_battle_over(players: list[Player]) -> bool:
    return len(_active_players(players)) <= 1
```

**Helper: turn order**

```python
def _build_turn_order(players: list[Player]) -> list[tuple[Hero, Player]]:
    """
    Returns (hero, owner) pairs sorted by speed descending.
    Assassins get a tie-breaking bonus: their speed is treated as
    speed + 0.5 in the sort so they move first among equals.
    """
    pairs: list[tuple[Hero, Player]] = []
    for player in players:
        if not player.is_eliminated:
            for hero in player.heroes:
                if hero.is_alive:
                    pairs.append((hero, player))

    def sort_key(pair: tuple[Hero, Player]) -> float:
        hero = pair[0]
        bonus = 0.5 if hero.role == Role.ASSASSIN else 0.0
        return hero.stats.speed + bonus

    pairs.sort(key=sort_key, reverse=True)
    return pairs
```

---

## 11. Variance Engine (RNG)

Three stacking layers give each attack a different feel. They multiply together before being applied to the base damage.

```python
# constants.py
VARIANCE_MIN      = 0.85   # minimum roll
VARIANCE_MAX      = 1.15   # maximum roll  → ±15% swing
CRIT_MULTIPLIER   = 1.50   # critical hit deals 1.5× damage
CLUTCH_THRESHOLD  = 0.25   # HP below 25% of max triggers clutch
CLUTCH_MULTIPLIER = 1.10   # clutch hero deals +10% damage
```

```python
# engine.py
from .constants import (
    VARIANCE_MIN, VARIANCE_MAX,
    CRIT_MULTIPLIER, CLUTCH_THRESHOLD, CLUTCH_MULTIPLIER,
)

def roll_variance(attacker: Hero) -> tuple[float, bool, bool]:
    """
    Returns:
        multiplier  — combined variance float to apply to base damage
        is_crit     — whether this hit was a critical strike
        is_clutch   — whether the clutch bonus activated

    Layer 1 — Base variance:
        random float in [VARIANCE_MIN, VARIANCE_MAX]  →  ±15%

    Layer 2 — Critical strike:
        Chance = attacker.stats.speed / 1000
        SPD 50 → 5% crit chance
        SPD 92 → 9.2% crit chance
        A crit multiplies damage by 1.5×

    Layer 3 — Clutch factor:
        Activates when HP < 25% of max
        Hero fighting on the edge deals +10% damage
        Creates comeback potential for underdogs
    """
    base = VARIANCE_MIN + random.random() * (VARIANCE_MAX - VARIANCE_MIN)

    crit_chance = attacker.stats.speed / 1000
    is_crit     = random.random() < crit_chance
    crit_mult   = CRIT_MULTIPLIER if is_crit else 1.0

    is_clutch   = attacker.current_hp < attacker.max_hp * CLUTCH_THRESHOLD
    clutch_mult = CLUTCH_MULTIPLIER if is_clutch else 1.0

    return base * crit_mult * clutch_mult, is_crit, is_clutch


def resolve_damage(attacker: Hero, defender: Hero) -> tuple[float, bool, bool]:
    """
    Full damage pipeline:
        base_damage × matchup_multiplier × variance_multiplier
    """
    base              = calc_base_damage(attacker, defender)
    matchup           = get_matchup_multiplier(attacker, defender)
    variance, crit, clutch = roll_variance(attacker)
    return base * matchup * variance, crit, clutch
```

**Possible multiplier ranges:**

| Scenario | Multiplier range |
|---|---|
| Normal hit | 0.85× – 1.15× |
| Critical (no clutch) | 1.28× – 1.73× |
| Clutch (no crit) | 0.94× – 1.27× |
| Clutch + crit | 1.40× – 1.90× |
| Counter matchup + crit | 1.43× – 1.94× |
| Counter matchup + crit + clutch | 1.57× – 2.13× |

---

## 12. Targeting Logic

Each role has a preferred target. This creates emergent strategy — players who understand role interactions can build rosters that exploit the targeting chain.

```python
# engine.py

def get_enemy_heroes(attacker: Hero, players: list[Player], owner: Player) -> list[Hero]:
    """All alive heroes not owned by the same player as attacker."""
    enemies: list[Hero] = []
    for player in players:
        if player is not owner and not player.is_eliminated:
            enemies.extend(h for h in player.heroes if h.is_alive)
    return enemies


def select_target(attacker: Hero, owner: Player, players: list[Player]) -> Hero | None:
    """
    Targeting rules per role:

    All roles:
        Tanks must be killed before non-Tanks can be targeted.
        If alive Tanks exist in the enemy pool, they form the target pool.
        If no Tanks remain, all alive enemies are targetable.

    Assassin:
        Primary: enemy Support (if any in pool)
        Fallback: lowest current HP in pool

    Blaster:
        Primary target for logging: highest current HP in pool
        Actual attack: AoE against all enemies (handled separately)

    Support:
        Primary: lowest current HP in pool (finish off wounded enemies)

    Tank / Bruiser:
        Primary: highest base_score in pool (eliminate the biggest threat)
    """
    enemies = get_enemy_heroes(attacker, players, owner)
    if not enemies:
        return None

    tanks     = [h for h in enemies if h.role == Role.TANK]
    non_tanks = [h for h in enemies if h.role != Role.TANK]
    pool      = tanks if tanks else non_tanks

    if attacker.role == Role.ASSASSIN:
        supports = [h for h in pool if h.role == Role.SUPPORT]
        if supports:
            return min(supports, key=lambda h: h.current_hp)
        return min(pool, key=lambda h: h.current_hp)

    if attacker.role == Role.BLASTER:
        return max(pool, key=lambda h: h.current_hp)

    if attacker.role == Role.SUPPORT:
        return min(pool, key=lambda h: h.current_hp)

    # Tank and Bruiser
    return max(pool, key=lambda h: h.base_score)
```

**Blaster AoE:**

```python
# constants.py
BLASTER_AOE_SPLIT = 0.40   # each enemy takes 40% of full damage

# engine.py
def _resolve_blaster_aoe(
    hero: Hero,
    owner: Player,
    players: list[Player],
    log: list[LogEntry],
    round_num: int,
) -> None:
    """
    Blasters deal BLASTER_AOE_SPLIT × full damage to every alive enemy.
    Each enemy gets an independent variance roll.
    """
    all_enemies   = get_enemy_heroes(hero, players, owner)
    alive_enemies = [h for h in all_enemies if h.is_alive]

    for enemy in alive_enemies:
        raw, is_crit, is_clutch = resolve_damage(hero, enemy)
        dmg = raw * BLASTER_AOE_SPLIT
        apply_damage(enemy, dmg)
        log.append(LogEntry(
            type="attack", round=round_num,
            data={
                "attacker":  hero.name,
                "target":    enemy.name,
                "damage":    dmg,
                "target_hp": enemy.current_hp,
                "crit":      is_crit,
                "clutch":    is_clutch,
                "aoe":       True,
            },
        ))
        if not enemy.is_alive:
            log.append(LogEntry(
                type="elimination", round=round_num,
                data={"hero": enemy.name},
            ))
```

---

## 13. Win Condition & Output

```python
# constants.py
UPSET_THRESHOLD = 0.85   # winner scored < 85% of top score → upset flag

# engine.py
from .constants import UPSET_THRESHOLD

def _get_last_standing(players: list[Player]) -> Player | None:
    alive = _active_players(players)
    if alive:
        return alive[0]
    # Tiebreak: player with highest remaining HP across all heroes
    return max(players, key=lambda p: sum(h.current_hp for h in p.heroes))


def _find_mvp(log: list[LogEntry]) -> tuple[str, float]:
    """Hero who dealt the most total damage across all rounds."""
    damage_totals: dict[str, float] = {}
    for entry in log:
        if entry.type == "attack":
            name = entry.data["attacker"]
            damage_totals[name] = damage_totals.get(name, 0.0) + entry.data["damage"]
    if not damage_totals:
        return "N/A", 0.0
    mvp = max(damage_totals, key=lambda k: damage_totals[k])
    return mvp, damage_totals[mvp]


def _check_upset(players: list[Player], winner: Player) -> bool:
    """True if the winner had a team_score < 85% of the highest scored team."""
    scores    = [p.team_score for p in players]
    max_score = max(scores) if scores else 0
    if max_score == 0:
        return False
    return winner.team_score < max_score * UPSET_THRESHOLD


def _build_result(
    players: list[Player],
    log: list[LogEntry],
    rounds: int,
) -> BattleResult:
    winner         = _get_last_standing(players)
    mvp, mvp_dmg   = _find_mvp(log)
    is_upset       = _check_upset(players, winner) if winner else False

    summaries = []
    for p in players:
        player_dmg = sum(
            e.data["damage"]
            for e in log
            if e.type == "attack"
            and any(h.name == e.data["attacker"] for h in p.heroes)
        )
        summaries.append({
            "player_id":    p.id,
            "heroes_alive": len(p.alive_heroes),
            "total_heroes": len(p.heroes),
            "team_score":   round(p.team_score, 1),
            "eliminated":   p.is_eliminated,
            "total_damage": round(player_dmg, 1),
        })

    return BattleResult(
        winner=winner,
        mvp_hero=mvp,
        mvp_damage=round(mvp_dmg, 1),
        is_upset=is_upset,
        rounds_played=rounds,
        log=log,
        player_summaries=summaries,
    )
```

---

## 14. Battle Log Schema

Every event is appended as a `LogEntry(type, round, data)`. The `data` dict schema per type:

```python
# round_start
{"type": "round_start",        "round": int,  "data": {}}

# attack (single-target or AoE hit)
{"type": "attack",             "round": int,  "data": {
    "attacker":  str,     # hero name
    "target":    str,     # hero name
    "damage":    float,   # actual damage dealt (post-variance)
    "target_hp": float,   # defender HP after damage
    "crit":      bool,
    "clutch":    bool,
    "aoe":       bool,    # True for Blaster AoE hits
}}

# elimination (hero reaches 0 HP)
{"type": "elimination",        "round": int,  "data": {"hero": str}}

# player_eliminated (all heroes dead)
{"type": "player_eliminated",  "round": int,  "data": {"player_id": str}}

# support_buff (applied at round start)
{"type": "support_buff",       "round": int,  "data": {
    "supporter": str,
    "target":    str,
}}

# clutch (logged when hero enters clutch range)
{"type": "clutch",             "round": int,  "data": {"hero": str}}
```

**Rendering the log as narration:**

```python
def render_log(log: list[LogEntry]) -> str:
    lines = []
    for entry in log:
        t = entry.type
        d = entry.data
        r = entry.round

        if t == "round_start":
            lines.append(f"\n=== Round {r} ===")
        elif t == "attack":
            tags = ""
            if d["crit"]:   tags += " [CRIT]"
            if d["clutch"]: tags += " [CLUTCH]"
            if d["aoe"]:    tags += " [AOE]"
            lines.append(
                f"  {d['attacker']} → {d['target']}: "
                f"{d['damage']:.0f} dmg{tags} "
                f"({d['target']} at {d['target_hp']:.0f} HP)"
            )
        elif t == "elimination":
            lines.append(f"  *** {d['hero']} eliminated! ***")
        elif t == "player_eliminated":
            lines.append(f"  *** Player {d['player_id']} is out! ***")
        elif t == "support_buff":
            lines.append(f"  {d['supporter']} buffs {d['target']} (+10%)")
        elif t == "clutch":
            lines.append(f"  {d['hero']} activates CLUTCH!")

    return "\n".join(lines)
```

---

## 15. Constants Reference

Every tunable value collected in `constants.py`. Change these to balance the meta without touching any logic.

```python
# constants.py

# Stat weights
STAT_WEIGHTS: dict[str, float] = {
    "strength":     1.20,
    "speed":        1.00,
    "power":        1.30,
    "durability":   0.90,
    "combat":       1.10,
    "intelligence": 0.80,
}

# Tier thresholds (base score)
TIER_THRESHOLDS: dict[str, int] = {"S": 560, "A": 470, "B": 380}

# HP
HP_MULTIPLIER = 10
TANK_HP_BONUS = 1.10

# Synergy / size (keyed by number of alive heroes)
SYNERGY_BONUS: dict[int, float] = {1: 1.00, 2: 1.08, 3: 1.14, 4: 1.18, 5: 1.22}
SIZE_PENALTY:  dict[int, float] = {1: 1.00, 2: 0.97, 3: 0.94, 4: 0.91, 5: 0.88}

# Matchup
COUNTER_BONUS   = 1.12
COUNTER_PENALTY = 0.88

# Variance (RNG)
VARIANCE_MIN      = 0.85
VARIANCE_MAX      = 1.15
CRIT_MULTIPLIER   = 1.50
CLUTCH_THRESHOLD  = 0.25
CLUTCH_MULTIPLIER = 1.10

# Role classification thresholds
TANK_THRESHOLD     = 160   # DUR + STR
ASSASSIN_THRESHOLD = 160   # SPD + CMB
BLASTER_THRESHOLD  = 85    # POW
SUPPORT_THRESHOLD  = 80    # INT

# Role effects
SUPPORT_BUFF      = 1.10
BLASTER_AOE_SPLIT = 0.40
ASSASSIN_DAMAGE_BONUS = 1.15   # applied in resolve_damage when role == ASSASSIN

# Budget
BUDGET_BONUS_DIVISOR = 1000

# Battle
MAX_ROUNDS      = 20
UPSET_THRESHOLD = 0.85
```

---

## 16. Connecting to the Superhero API

The engine expects `Hero` objects with a `HeroStats` instance. Here is how to map the raw API response to that model.

```python
import json
import urllib.request
from battle_engine import Hero, HeroStats

API_BASE = "https://superheroapi.com/api/{YOUR_TOKEN}"

def fetch_hero(hero_id: int) -> dict:
    url = f"{API_BASE}/{hero_id}"
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())

def api_response_to_hero(data: dict) -> Hero | None:
    """
    Convert a raw Superhero API response to a Hero object.
    Returns None if any stat is missing or non-numeric ("null").
    """
    ps = data.get("powerstats", {})

    def safe_int(val) -> int | None:
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    stats_values = {
        "intelligence": safe_int(ps.get("intelligence")),
        "strength":     safe_int(ps.get("strength")),
        "speed":        safe_int(ps.get("speed")),
        "durability":   safe_int(ps.get("durability")),
        "power":        safe_int(ps.get("power")),
        "combat":       safe_int(ps.get("combat")),
    }

    if any(v is None for v in stats_values.values()):
        return None   # hero has incomplete stats — skip

    bio   = data.get("biography", {})
    team  = bio.get("team-member", "") or bio.get("publisher", "")

    return Hero(
        id=int(data["id"]),
        name=data["name"],
        team=team,
        stats=HeroStats(**stats_values),
    )


def load_all_heroes(token: str, hero_ids: list[int]) -> list[Hero]:
    """Batch-load heroes from the API, skipping any with null stats."""
    heroes = []
    for hid in hero_ids:
        data = fetch_hero(hid)
        hero = api_response_to_hero(data)
        if hero:
            heroes.append(hero)
    return heroes
```

**Hooking heroes into a battle:**

```python
import copy
from battle_engine import Player, BattleMode, run_battle

all_heroes = load_all_heroes(token, range(1, 303))
hero_map   = {h.name: h for h in all_heroes}

# After the auction draft, build Player objects with the won heroes
p1 = Player(
    id="alice",
    heroes=copy.deepcopy([
        hero_map["Thor"],
        hero_map["Iron Man"],
        hero_map["Black Widow"],
        hero_map["Spider-Man"],
        hero_map["Captain America"],
    ]),
    draft_budget=100,
    spent_budget=82,    # coins spent in the auction
)

p2 = Player(
    id="bob",
    heroes=copy.deepcopy([
        hero_map["Thanos"],
        hero_map["Hulk"],
        hero_map["Storm"],
        hero_map["Wolverine"],
        hero_map["Doctor Strange"],
    ]),
    draft_budget=100,
    spent_budget=91,
)

result = run_battle([p1, p2], BattleMode.TEAM)
print(render_log(result.log))

print(f"\nWinner: Player {result.winner.id}")
print(f"MVP:    {result.mvp_hero} ({result.mvp_damage:.0f} damage)")
print(f"Upset:  {result.is_upset}")
```

> **Important:** Always `copy.deepcopy()` heroes before passing them to `run_battle()`. The engine mutates `current_hp` and `is_alive` in place. Without a deep copy, re-running a battle on the same player would start with heroes already at 0 HP.

---

## 17. Full Pseudocode

High-level view of the entire pipeline in plain language.

```
FUNCTION run_battle(players, mode):

  ── PHASE 1: INITIALISE ─────────────────────────────────────────────────

  FOR each player:
    FOR each hero:
      hero.base_score = sum(stat × weight for each stat)
      hero.role       = classify_role(hero.stats)   # priority: Tank → Assassin → Blaster → Support → Bruiser
      hero.max_hp     = hero.stats.durability × 10
      IF hero.role == Tank: hero.max_hp × = 1.10
      hero.current_hp = hero.max_hp
      hero.is_alive   = True

    player.team_score = sum(base_scores)
                      × synergy_multiplier    # based on shared affiliation
                      × size_penalty          # grows with roster size
                      × budget_bonus          # remaining_budget / 1000 + 1

  log   = []
  round = 0


  ── PHASE 2: ROUND LOOP ─────────────────────────────────────────────────

  WHILE active_players > 1 AND round < MAX_ROUNDS:
    round += 1
    log.append(ROUND_START)

    FOR each active player:
      IF any alive hero.role == Support:
        find alive non-Support teammate with highest base_score
        teammate.base_score × = 1.10
        store original score for revert

    turn_order = all alive heroes across active players
    turn_order.sort(by=speed descending, Assassins get +0.5 tiebreak)

    FOR each (hero, owner) in turn_order:
      IF hero.is_alive == False: SKIP

      IF hero.role == Blaster:
        all_enemies = alive heroes not owned by owner
        FOR each enemy in all_enemies:
          damage = calc_base_damage(hero, enemy)
                 × get_matchup_multiplier(hero, enemy)
                 × roll_variance(hero)        # base ±15%, possible crit, possible clutch
                 × BLASTER_AOE_SPLIT          # 0.40
          apply_damage(enemy, damage)
          log.append(ATTACK, aoe=True)
          IF enemy.current_hp == 0: log.append(ELIMINATION)

      ELSE:
        pool = alive enemies not owned by owner
        IF any Tank in pool: pool = only the Tanks

        target = role-based selection:
          Assassin  → Support first, else lowest HP
          Support   → lowest HP
          Tank      → highest base_score
          Bruiser   → highest base_score

        IF hero.current_hp < max_hp × 0.25: log.append(CLUTCH)

        variance = random(0.85, 1.15)
                 × (1.50 if random() < speed/1000 else 1.0)   # crit
                 × (1.10 if hp < 25% max else 1.0)            # clutch

        damage = calc_base_damage(hero, target)
               × get_matchup_multiplier(hero, target)          # ±12% or 1.0
               × variance

        target.current_hp -= damage
        IF target.current_hp <= 0:
          target.is_alive = False
          log.append(ELIMINATION)

        log.append(ATTACK)

    FOR each active player:
      revert Support buff (restore pre-buff base_score)

    FOR each player:
      IF not eliminated AND all heroes dead:
        player.is_eliminated = True
        log.append(PLAYER_ELIMINATED)


  ── PHASE 3: RESULT ─────────────────────────────────────────────────────

  winner   = last non-eliminated player
           ?? player with highest total remaining HP

  mvp      = hero with most cumulative damage in log

  is_upset = winner.team_score < max(all team_scores) × 0.85

  RETURN BattleResult(winner, mvp, is_upset, rounds, log, summaries)
```

---

*End of specification.*
