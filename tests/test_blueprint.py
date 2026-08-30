from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.bot.blueprint import (
    CategoryState,
    ChannelState,
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

    assert blueprint.version == 2
    assert blueprint.server_name == "AXIS"
    assert [role.name for role in blueprint.roles] == ["AXIS BOT", "Manager", "Member"]
    assert blueprint.role_order == ("bot", "manager", "member", "everyone")
    assert [category.name for category in blueprint.categories] == [
        "⬛・GENERAL",
        "🟢・MEMBERS",
        "⚙️・MANAGER",
        "🧪・AXIS LAB",
    ]
    assert [channel.name for category in blueprint.categories for channel in category.channels] == [
        "👋・welcome",
        "💳・subscriptions",
        "📊・results",
        "💬・lobby",
        "🏆・member-wins",
        "⚡・short-term",
        "〽️・swing",
        "♾️・leaps",
        "🛋️・member-lounge",
        "📥・signal-input",
        "✅・card-review",
        "💭・analysis-input",
        "📝・analysis-review",
        "🧭・mentor-control",
        "👤・member-control",
        "🤫・quiet-profits",
        "🟢・lab-signals",
        "🧬・mentor-status",
        "🗂️・lab-history",
    ]
    assert len(blueprint.categories) == 4
    assert blueprint.channel_count == 19
    assert blueprint.categories[-1].feature_flag == "FEATURE_LAB_ENABLED"


def test_empty_server_plan_creates_only_missing_axis_resources() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    plan = build_plan(blueprint, empty_guild(), GUILD_ID)

    creates = [action for action in plan.actions if action.status == "CREATE"]
    assert sum(action.resource_type == "role" for action in creates) == 2
    assert sum(action.resource_type == "category" for action in creates) == 4
    assert sum(action.resource_type == "channel" for action in creates) == 19
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
    manager_lounge = desired_channel_permissions(channels["manager_lounge"])
    assert member_wins["member"]["attach_files"] is True
    assert member_wins["manager"]["manage_messages"] is True
    assert lobby["manager"]["manage_messages"] is True
    assert manager_lounge["manager"]["view_channel"] is True
    assert manager_lounge["manager"]["send_messages"] is True
    assert manager_lounge["manager"]["attach_files"] is True
    assert manager_lounge["member"]["view_channel"] is False


def test_saved_axis_role_rename_requires_explicit_opt_in() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    guild = replace(
        empty_guild(),
        roles=empty_guild().roles + (RoleState(301, "曾经的管理员", False, 1),),
    )
    saved_ids = {"guild_id": GUILD_ID, "roles": {"manager": 301}}
    blocked = build_plan(blueprint, guild, GUILD_ID, saved_ids)
    allowed = build_plan(
        blueprint,
        guild,
        GUILD_ID,
        saved_ids,
        allow_axis_renames=True,
    )

    assert any(
        action.status == "BLOCK" and action.resource_type == "role" and action.key == "manager"
        for action in blocked.actions
    )
    assert not any(
        action.status == "CREATE" and action.resource_type == "role" and action.key == "manager"
        for action in blocked.actions
    )
    assert any(
        action.status == "UPDATE"
        and action.resource_type == "role_name"
        and action.key == "manager"
        for action in allowed.actions
    )
    assert not any(action.key == "manager" for action in allowed.blockers)


def test_saved_axis_category_and_channel_renames_require_explicit_opt_in() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    guild = replace(
        empty_guild(),
        categories=(CategoryState(401, "Old Start", 0),),
        channels=(
            ChannelState(
                501,
                "old-welcome",
                "text",
                401,
                0,
                "AXIS 欢迎与使用说明。",
                {},
            ),
        ),
    )
    saved_ids = {
        "guild_id": GUILD_ID,
        "categories": {"start": 401},
        "channels": {"welcome": 501},
    }

    blocked = build_plan(blueprint, guild, GUILD_ID, saved_ids)
    allowed = build_plan(
        blueprint,
        guild,
        GUILD_ID,
        saved_ids,
        allow_axis_renames=True,
    )

    assert any(action.key == "start" for action in blocked.blockers)
    assert any(action.key == "welcome" for action in blocked.blockers)
    assert any(
        action.status == "UPDATE" and action.resource_type == "category_name"
        for action in allowed.actions
    )
    assert any(
        action.status == "UPDATE" and action.resource_type == "channel_name"
        for action in allowed.actions
    )
    assert not any(action.key in {"start", "welcome"} for action in allowed.blockers)


def test_axis_role_above_bot_blocks_apply_before_any_mutation() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    guild = replace(
        empty_guild(),
        roles=empty_guild().roles + (RoleState(301, "Manager", False, 4),),
    )
    plan = build_plan(blueprint, guild, GUILD_ID)

    assert any(action.resource_type == "role_hierarchy" for action in plan.blockers)


def test_equal_role_positions_use_discord_id_tiebreaker() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    guild = replace(
        empty_guild(),
        roles=(
            RoleState(GUILD_ID, "@everyone", True, 0),
            RoleState(201, "AXIS BOT", True, 1),
            RoleState(301, "Manager", False, 1),
            RoleState(302, "Member", False, 1),
        ),
    )
    plan = build_plan(blueprint, guild, GUILD_ID)

    assert not any(action.resource_type == "role_hierarchy" for action in plan.blockers)
    assert not any(
        action.status == "UPDATE" and action.resource_type == "role_hierarchy"
        for action in plan.actions
    )


def test_discord_read_messages_alias_satisfies_view_channel_requirement() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    guild = replace(
        empty_guild(),
        bot_permissions=("manage_channels", "manage_roles", "read_messages"),
    )
    plan = build_plan(blueprint, guild, GUILD_ID)

    assert not any(action.resource_type == "bot_permissions" for action in plan.blockers)


def test_server_brand_case_mismatch_is_reported_without_planning_a_write() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    plan = build_plan(blueprint, replace(empty_guild(), name="Axis"), GUILD_ID)

    assert any("品牌目标" in warning for warning in plan.warnings)
    assert not any(action.resource_type == "guild_branding" for action in plan.changes)
