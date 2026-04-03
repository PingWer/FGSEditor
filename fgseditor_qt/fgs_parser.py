import os
from .fgs_math import parse_p_row


def _parse_scale_from_lines(lines):
    fgs_data = {
        "sY": {"x": [], "y": []},
        "sCb": {"x": [], "y": []},
        "sCr": {"x": [], "y": []},
    }
    for line in lines:
        tokens = line.strip().split()
        if not tokens:
            continue
        prefix = tokens[0]
        if prefix in fgs_data:
            num_points = int(tokens[1])
            for i in range(num_points):
                value = int(tokens[2 + (i * 2)])
                strength = int(tokens[3 + (i * 2)])
                fgs_data[prefix]["x"].append(value)
                fgs_data[prefix]["y"].append(strength)
    return fgs_data


def parse_fgs_scale(fgs_text):
    return _parse_scale_from_lines(fgs_text.strip().split("\n"))


def _extract_p_params(raw_lines: list[str]) -> dict | None:
    """Scan raw_lines for a 'p' row and return parsed p_params dict, or None."""
    for raw_line in raw_lines:
        tokens = raw_line.strip().split()
        if tokens and tokens[0] == "p":
            return parse_p_row(tokens[1:])
    return None


def parse_fgs_events(content):
    lines = content.splitlines(keepends=True)
    events = []
    header_lines = []
    current_event = None

    for line in lines:
        stripped = line.strip()
        tokens = stripped.split()

        if tokens and tokens[0] == "E":
            if current_event is not None:
                current_event["scale_data"] = _parse_scale_from_lines(
                    [line_text.strip() for line_text in current_event["raw_lines"]]
                )
                current_event["p_params"] = _extract_p_params(current_event["raw_lines"])
                events.append(current_event)

            start_t = int(tokens[1])
            end_t = int(tokens[2])
            current_event = {
                "start_time": start_t,
                "end_time": end_t,
                "e_line": line,
                "extra_params": tokens[3:],
                "raw_lines": [],
                "scale_data": None,
                "p_params": None,
            }
        elif current_event is not None:
            current_event["raw_lines"].append(line)
        else:
            header_lines.append(line)

    if current_event is not None:
        current_event["scale_data"] = _parse_scale_from_lines(
            [line_text.strip() for line_text in current_event["raw_lines"]]
        )
        current_event["p_params"] = _extract_p_params(current_event["raw_lines"])
        events.append(current_event)

    return header_lines, events


def is_dynamic(events):
    return len(events) > 1


def avg_sy_strength(event):
    ys = event["scale_data"]["sY"]["y"]
    if not ys:
        return 0
    return sum(ys) / len(ys)


def parse_fgs_file(filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File {filepath} does not exist.")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    _, events = parse_fgs_events(content)
    if not events:
        raise ValueError("No events found in the FGS file.")
    return events[0]["scale_data"]
