from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".py", ".json", ".toml", ".yaml", ".yml"}
FORBIDDEN_OLD_BRAND = (
    "AXIS" + " DESK",
    "Axis" + "Desk",
    "axis" + "-desk-logo",
    "AXIS" + "_DESK_MVP_SPEC",
)


def project_text() -> str:
    parts: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if any(part in {".git", ".venv", ".pytest_cache", ".ruff_cache"} for part in path.parts):
            continue
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_old_brand_name_is_absent_from_project_text() -> None:
    text = project_text()

    assert all(value not in text for value in FORBIDDEN_OLD_BRAND)


def test_axis_brand_assets_and_blueprint_paths_are_stable() -> None:
    blueprint = yaml.safe_load(
        (ROOT / "config" / "discord_blueprint.yaml").read_text(encoding="utf-8")
    )

    assert blueprint["brand"]["server_name"] == "AXIS"
    assert blueprint["brand"]["logo_path"] == "assets/axis-logo.png"
    assert "brand_lockup_path" not in blueprint["brand"]
    assert (ROOT / blueprint["brand"]["logo_path"]).is_file()
    assert (
        (ROOT / "assets" / "axis-logo.png").read_bytes()
        == (ROOT / "assets" / "axis-brand-lockup.png").read_bytes()
    )
    assert not (ROOT / "assets" / "axis-icon.png").exists()
