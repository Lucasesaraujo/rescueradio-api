from datetime import datetime, timezone


DEFAULT_BASE = {
    "id": "base-central",
    "name": "Base Central",
    "city": "Recife",
    "uf": "PE",
    "latitude": -8.0476,
    "longitude": -34.877,
    "coverage_cities": ["Recife", "Olinda", "Paulista", "Jaboatao dos Guararapes", "Camaragibe"],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize_skills(skills: list[str]) -> str:
    return ",".join(skill.strip() for skill in skills if skill.strip())


def parse_skills(skills: str) -> list[str]:
    return [skill for skill in skills.split(",") if skill]


def normalize_coverage_cities(cities: list[str]) -> list[str]:
    seen = set()
    normalized = []
    for city in cities:
        value = str(city).strip()
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    return normalized


def invalid_coordinate(latitude: float | None, longitude: float | None) -> bool:
    if latitude is None or longitude is None:
        return True
    if abs(float(latitude)) < 0.0001 and abs(float(longitude)) < 0.0001:
        return True
    return not (-90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180)


def derive_display_name(full_name: str) -> str:
    parts = [part for part in full_name.strip().split() if part]
    if len(parts) <= 1:
        return full_name.strip()
    return f"{parts[0]} {parts[-1]}"


def derive_callsign_base(full_name: str) -> str:
    initials = "".join(part[0].lower() for part in full_name.strip().split() if part)
    return initials or "op"


def row_to_dict(row) -> dict:
    data = dict(row)
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data
