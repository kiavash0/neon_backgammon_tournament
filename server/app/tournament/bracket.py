"""Single-elimination bracket helpers (SPEC §5.2): CSPRNG random seeding on
room fill, and deterministic pairing across rounds via each match's
bracket_slot.
"""

import random


def seed_players(player_ids: list[str], rng: random.Random | None = None) -> list[str]:
    """CSPRNG shuffle of the frozen roster (SPEC §5.2: "random seeding
    (CSPRNG shuffle)"). `rng` is injectable for deterministic tests;
    defaults to random.SystemRandom(), which is CSPRNG-backed (os.urandom)."""
    rng = rng or random.SystemRandom()
    seeded = list(player_ids)
    rng.shuffle(seeded)
    return seeded


def pair_round(ordered_ids: list[str]) -> list[tuple[str, str]]:
    """Pair adjacent entries: (0,1), (2,3), ... — used both for round 1
    (seeded roster) and later rounds (winners in bracket_slot order)."""
    if len(ordered_ids) % 2 != 0:
        raise ValueError("cannot pair an odd number of players")
    return [(ordered_ids[i], ordered_ids[i + 1]) for i in range(0, len(ordered_ids), 2)]
