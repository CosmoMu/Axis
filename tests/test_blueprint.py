from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.bot.blueprint import (
    CategoryState,
    GuildState,
    RoleState,
    build_plan,
    desired_channel_permissions,
    load_blueprint,
)

ROOT = Path(__file__).resolve().parents[1]
GUILD_ID = 1543309921066684567


def empty_guild() -> GuildState:
    return GuildState(
        id=GUILD_ID,
        name="AXIS",
        owner_id=100,
        bot_user_id=200,
        bot_role_id=201,
        bot_permissions=("manage_channels", "manage_roles", "view_channel"),
        roles=(
            RoleState(GUILD_ID, "@everyone", True, 0),
            RoleState(201, "AXIS BOT", True, 3),
        ),
        categories=(),
        channels=(),
    )


def test_blueprint_has_exact_mvp_shape() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")

    assert blueprint.server_name == "AXIS"
    assert [role.name for role in blueprint.roles] == ["AXIS BOT", "管理员", "会员"]
    assert blueprint.role_order == ("bot", "manager", "member", "everyone")
    assert len(blueprint.categories) == 4
    assert blueprint.channel_count == 15
    assert blueprint.categories[-1].feature_flag == "FEATURE_LAB_ENABLED"


def test_empty_server_plan_creates_only_missing_axis_resources() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    plan = build_plan(blueprint, empty_guild(), GUILD_ID)

    creates = [action for action in plan.actions if action.status == "CREATE"]
    assert sum(action.resource_type == "role" for action in creates) == 2
    assert sum(action.resource_type == "category" for action in creates) == 4
    assert sum(action.resource_type == "channel" for action in creates) == 15
    assert not plan.blockers


def test_wrong_guild_id_is_a_blocker() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    plan = build_plan(blueprint, empty_guild(), GUILD_ID + 1)

    assert any(action.resource_type == "guild" for action in plan.blockers)


def test_bot_managed_role_name_must_match_blueprint() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    guild = empty_guild()
    wrong_roles = tuple(
        replace(role, name="Other Bot") if role.id == guild.bot_role_id else role
        for role in guild.roles
    )
    plan = build_plan(blueprint, replace(guild, roles=wrong_roles), GUILD_ID)

    assert any(action.key == "bot" and action.resource_type == "role" for action in plan.blockers)


def test_existing_unrelated_resources_are_never_planned_for_mutation() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    guild = replace(
        empty_guild(),
        categories=(CategoryState(999, "Other Project", 0),),
    )
    plan = build_plan(blueprint, guild, GUILD_ID)

    assert all(action.name != "Other Project" for action in plan.actions)


def test_blueprint_encodes_member_upload_and_manager_moderation() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    channels = {
        channel.key: channel for category in blueprint.categories for channel in category.channels
    }

    member_wins = desired_channel_permissions(channels["member_wins"])
    lobby = desired_channel_permissions(channels["lobby"])
    assert member_wins["member"]["attach_files"] is True
    assert member_wins["manager"]["manage_messages"] is True
    assert lobby["manager"]["manage_messages"] is True


def test_saved_id_is_preferred_and_renames_block_duplicate_creation() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    guild = replace(
        empty_guild(),
        roles=empty_guild().roles + (RoleState(301, "曾经的管理员", False, 1),),
    )
    saved_ids = {"guild_id": GUILD_ID, "roles": {"manager": 301}}
    plan = build_plan(blueprint, guild, GUILD_ID, saved_ids)

    assert any(
        action.status == "BLOCK" and action.resource_type == "role" and action.key == "manager"
        for action in plan.actions
    )
    assert not any(
        action.status == "CREATE" and action.resource_type == "role" and action.key == "manager"
        for action in plan.actions
    )


def test_axis_role_above_bot_blocks_apply_before_any_mutation() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    guild = replace(
        empty_guild(),
        roles=empty_guild().roles + (RoleState(301, "管理员", False, 4),),
    )
    plan = build_plan(blueprint, guild, GUILD_ID)

    assert any(action.resource_type == "role_hierarchy" for action in plan.blockers)
