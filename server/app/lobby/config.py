import os

SMALL_CAPACITIES = (2, 4, 8)
LARGE_CAPACITIES = (16, 32, 64, 128, 256, 512)
ALL_CAPACITIES = SMALL_CAPACITIES + LARGE_CAPACITIES


def small_room_pool_size() -> int:
    return int(os.environ.get("SMALL_ROOM_POOL", "20"))


def target_pool_size(capacity: int) -> int:
    return small_room_pool_size() if capacity in SMALL_CAPACITIES else 1
