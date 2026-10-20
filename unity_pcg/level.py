"""Small, versioned intermediate representation shared with Unity JsonUtility."""

from collections import deque
from dataclasses import dataclass
import hashlib
import json

TILES = "#.PKDH"


@dataclass
class Level:
    rows: list[str]

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != {"schema_version", "rows"}:
            raise ValueError("Level needs exactly schema_version and rows")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError("Unsupported level schema_version")
        level = cls(data["rows"])
        level.validate()
        return level

    def validate(self):
        if not isinstance(self.rows, list) or not 5 <= len(self.rows) <= 64:
            raise ValueError("Height must be 5..64")
        if not all(isinstance(row, str) for row in self.rows):
            raise ValueError("Rows must be strings")
        width = len(self.rows[0])
        if not 5 <= width <= 64 or any(len(row) != width for row in self.rows):
            raise ValueError("Width must be 5..64 and rows rectangular")
        if any(c not in TILES for row in self.rows for c in row):
            raise ValueError("Tiles allowed: # wall, . floor, P player, K key, D door, H hazard")
        if any(self.count(c) != 1 for c in "PKD"):
            raise ValueError("Exactly one P, K and D required")
        if any(c != "#" for c in self.rows[0] + self.rows[-1]):
            raise ValueError("Top/bottom boundary must be walls")
        if any(row[0] != "#" or row[-1] != "#" for row in self.rows):
            raise ValueError("Left/right boundary must be walls")

    @property
    def width(self):
        return len(self.rows[0])

    @property
    def height(self):
        return len(self.rows)

    def count(self, tile):
        return sum(row.count(tile) for row in self.rows)

    def position(self, tile):
        return next((x, y) for y, row in enumerate(self.rows) for x, c in enumerate(row) if c == tile)

    def to_dict(self):
        return {"schema_version": 1, "rows": self.rows[:]}

    def digest(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()

    def path(self, start, goal, has_key=False):
        """BFS in grid space; D is impassable before key pickup, H is lethal."""
        queue, previous = deque([start]), {start: None}
        while queue:
            p = queue.popleft()
            if p == goal:
                route = []
                while p is not None:
                    route.append({"x": p[0], "y": p[1]})
                    p = previous[p]
                return route[::-1]
            x, y = p
            for nx, ny in ((x + 1, y), (x, y + 1), (x - 1, y), (x, y - 1)):
                if not (0 <= nx < self.width and 0 <= ny < self.height):
                    continue
                tile = self.rows[ny][nx]
                if tile in "#H" or (tile == "D" and not has_key) or (nx, ny) in previous:
                    continue
                previous[nx, ny] = (x, y)
                queue.append((nx, ny))
        return []


def contract(data):
    allowed = {"min_path_length", "max_path_length", "hazard_count", "zone_hazards"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("Supported targets: " + ", ".join(sorted(allowed)))
    result = {"min_path_length": 0, "max_path_length": 8192, **data}
    for key, value in result.items():
        if key == "zone_hazards":
            if not isinstance(value, list) or len(value) != 3 or any(type(n) is not int or not 0 <= n <= 4096 for n in value):
                raise ValueError("zone_hazards must contain three nonnegative integer counts")
        elif type(value) is not int or not 0 <= value <= 8192:
            raise ValueError(key + " must be an integer in 0..8192")
    if result["min_path_length"] > result["max_path_length"]:
        raise ValueError("min_path_length > max_path_length")
    if "hazard_count" in result and "zone_hazards" in result and sum(result["zone_hazards"]) != result["hazard_count"]:
        raise ValueError("hazard_count conflicts with zone_hazards")
    return result


def evaluate(level, targets):
    level.validate()
    targets = contract(targets)
    pk = level.path(level.position("P"), level.position("K"))
    kd = level.path(level.position("K"), level.position("D"), has_key=True)
    unreachable = int(not pk) + int(not kd)
    length = len(pk) + len(kd) - 2 if not unreachable else None
    zones = [0, 0, 0]
    for row in level.rows:
        for x, tile in enumerate(row):
            if tile == "H":
                zones[min(2, (x - 1) * 3 // (level.width - 2))] += 1
    errors = []
    if not pk:
        errors.append("Player cannot reach key without crossing walls/hazards/locked door")
    if not kd:
        errors.append("Key cannot reach door without crossing walls/hazards")
    distance_error = 0 if length is None else max(0, targets["min_path_length"] - length, length - targets["max_path_length"])
    target_error = distance_error
    if distance_error:
        errors.append(f"Path length {length} outside requested bounds")
    if "hazard_count" in targets:
        target_error += abs(level.count("H") - targets["hazard_count"])
        if level.count("H") != targets["hazard_count"]:
            errors.append(f"Hazards: {level.count('H')}, expected {targets['hazard_count']}")
    if "zone_hazards" in targets:
        target_error += sum(abs(a - b) for a, b in zip(zones, targets["zone_hazards"]))
        if zones != targets["zone_hazards"]:
            errors.append(f"Left/middle/right hazard counts: {zones}, expected {targets['zone_hazards']}")
    return {"backend": "offline-bfs", "playable": not unreachable, "satisfied": not unreachable and target_error == 0,
            "score": [unreachable, target_error], "path_length": length,
            "player_key_length": len(pk) - 1 if pk else None, "key_door_length": len(kd) - 1 if kd else None,
            "hazard_count": level.count("H"), "zone_hazards": zones, "errors": errors,
            "route": pk + kd[1:] if not unreachable else []}
