"""Allowlisted operations. No generated C#, shell, reflection, or arbitrary asset paths."""

from .level import Level, TILES


def schemas(level):
    integer_x = {"type": "integer", "minimum": 1, "maximum": level.width - 2}
    integer_y = {"type": "integer", "minimum": 1, "maximum": level.height - 2}
    tile = {"type": "string", "enum": list(TILES)}
    definitions = [
        ("set_tile", "Set one interior tile. Moving P/K/D clears its old position to floor.", {"x": integer_x, "y": integer_y, "tile": tile}),
        ("fill_rect", "Fill an inclusive rectangle with wall/floor/hazard; preserve P/K/D.",
         {"x1": integer_x, "y1": integer_y, "x2": integer_x, "y2": integer_y, "tile": {"type": "string", "enum": list("#.H")}}),
        ("carve_corridor", "Carve a Manhattan corridor horizontally then vertically; preserve P/K/D.",
         {"x1": integer_x, "y1": integer_y, "x2": integer_x, "y2": integer_y}),
        ("finish", "Ask to stop. The harness stops only when executable targets and selected backend pass.", {})]
    return [{"type": "function", "function": {"name": name, "description": desc,
             "parameters": {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}}}
            for name, desc, props in definitions]


def apply(level, actions):
    if not isinstance(actions, list) or not 1 <= len(actions) <= 8:
        raise ValueError("Use 1..8 tool calls per step")
    grid = [list(row) for row in level.rows]
    allowed = {item["function"]["name"]: item["function"]["parameters"]["properties"] for item in schemas(level)}
    finish = False
    for action in actions:
        if not isinstance(action, dict) or set(action) != {"name", "arguments"} or not isinstance(action["name"], str):
            raise ValueError("Tool call requires name and arguments")
        name, args = action["name"], action["arguments"]
        if name not in allowed or not isinstance(args, dict) or set(args) != set(allowed[name]):
            raise ValueError("Unknown tool or incorrect arguments")
        for key, spec in allowed[name].items():
            val = args[key]
            if spec["type"] == "integer":
                if type(val) is not int or not spec["minimum"] <= val <= spec["maximum"]:
                    raise ValueError(f"{key} outside interior grid or not an integer")
            elif val not in spec["enum"]:
                raise ValueError("Invalid tile")
        if name == "finish":
            finish = True
            continue
        if name == "set_tile":
            x, y, tile = args["x"], args["y"], args["tile"]
            if tile in "PKD":
                for row in grid:
                    for i, old in enumerate(row):
                        if old == tile:
                            row[i] = "."
            grid[y][x] = tile
        elif name == "fill_rect":
            if args["x1"] > args["x2"] or args["y1"] > args["y2"]:
                raise ValueError("Rectangle bounds must be ordered")
            for y in range(args["y1"], args["y2"] + 1):
                for x in range(args["x1"], args["x2"] + 1):
                    if grid[y][x] not in "PKD":
                        grid[y][x] = args["tile"]
        elif name == "carve_corridor":
            x1, y1, x2, y2 = (args[k] for k in ("x1", "y1", "x2", "y2"))
            points = [(x, y1) for x in range(min(x1, x2), max(x1, x2) + 1)]
            points += [(x2, y) for y in range(min(y1, y2), max(y1, y2) + 1)]
            for x, y in points:
                if grid[y][x] not in "PKD":
                    grid[y][x] = "."
    candidate = Level(["".join(row) for row in grid])
    candidate.validate()  # Validate whole transaction; discard all edits on any error.
    return candidate, finish
