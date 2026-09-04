from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.bot.blueprint import (
    CategoryState,
    ChannelState,
    GuildState,
    RoleState,
    build_plan,
    desired_category_permissions,
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

    assert blueprint.version == 4
    assert blueprint.server_name == "AXIS"
    assert [role.name for role in blueprint.roles] == [
        "AXIS BOT",
        "Manager",
        "Member",
        "Newcomer",
    ]
    assert blueprint.role_order == ("bot", "manager", "member", "newcomer", "everyone")
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
        "✅・signal-review",
        "💭・analysis-input",
        "📝・analysis-review",
        "🧭・mentor-control",
        "👤・member-control",
        "📋・results-review",
        "🛂・join-review",
        "🤫・在这交流",
        "🚨・system-alerts",
        "🧪・card-testing",
        "💹・moomoo-trading",
        "🟢・lab-signals",
        "🧬・mentor-status",
        "🗂️・lab-history",
    ]
    assert len(blueprint.categories) == 4
    assert blueprint.channel_count == 24
    assert blueprint.categories[-1].feature_flag == "FEATURE_LAB_ENABLED"
    assert [category.position for category in blueprint.categories] == [0, 1, 2, 3]
    assert blueprint.categories[0].channels[0].key == "welcome"


def test_empty_server_plan_creates_only_missing_axis_resources() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    plan = build_plan(blueprint, empty_guild(), GUILD_ID)

    creates = [action for action in plan.actions if action.status == "CREATE"]
    assert sum(action.resource_type == "role" for action in creates) == 3
    assert sum(action.resource_type == "category" for action in creates) == 4
    assert sum(action.resource_type == "channel" for action in creates) == 24
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


def test_welcome_first_plan_never_targets_unregistered_resources() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    welcome_spec = blueprint.categories[0].channels[0]
    guild = replace(
        empty_guild(),
        categories=(
            CategoryState(999, "Other Project", 0),
            CategoryState(401, "⬛・GENERAL", 5),
        ),
        channels=(
            ChannelState(998, "other-channel", "text", 999, 0, "Other", {}),
            ChannelState(501, "👋・welcome", "text", 401, 5, welcome_spec.topic, {}),
        ),
    )
    saved_ids = {
        "guild_id": GUILD_ID,
        "categories": {"start": 401},
        "channels": {"welcome": 501},
    }
    plan = build_plan(blueprint, guild, GUILD_ID, saved_ids)

    position_updates = [
        action for action in plan.actions if action.resource_type.endswith("_position")
    ]
    assert {(action.resource_type, action.key) for action in position_updates} == {
        ("category_position", "start"),
        ("channel_position", "welcome"),
    }
    assert all(action.current_id not in {998, 999} for action in position_updates)


def test_blueprint_encodes_member_upload_and_manager_moderation() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    channels = {
        channel.key: channel for category in blueprint.categories for channel in category.channels
    }

    member_wins = desired_channel_permissions(channels["member_wins"])
    lobby = desired_channel_permissions(channels["lobby"])
    manager_lounge = desired_channel_permissions(channels["manager_lounge"])
    card_testing = desired_channel_permissions(channels["card_testing"])
    system_alerts = desired_channel_permissions(channels["system_alerts"])
    assert member_wins["everyone"]["send_messages"] is True
    assert member_wins["everyone"]["attach_files"] is True
    assert member_wins["member"]["attach_files"] is True
    assert member_wins["manager"]["manage_messages"] is True
    assert member_wins["bot"]["pin_messages"] is True
    assert lobby["manager"]["manage_messages"] is True
    assert manager_lounge["manager"]["view_channel"] is True
    assert manager_lounge["manager"]["send_messages"] is True
    assert manager_lounge["manager"]["attach_files"] is True
    assert manager_lounge["member"]["view_channel"] is False
    assert card_testing["everyone"]["view_channel"] is False
    assert card_testing["member"]["view_channel"] is False
    assert card_testing["manager"]["view_channel"] is False
    assert card_testing["manager"]["send_messages"] is False
    assert card_testing["owner"]["view_channel"] is True
    assert card_testing["owner"]["send_messages"] is True
    assert card_testing["owner"]["use_application_commands"] is True
    assert card_testing["manager"]["use_application_commands"] is False
    assert card_testing["bot"]["send_messages"] is True
    assert system_alerts["manager"]["view_channel"] is False
    assert system_alerts["owner"]["view_channel"] is True
    assert system_alerts["bot"]["manage_messages"] is True
    assert system_alerts["bot"]["manage_channels"] is True
    assert system_alerts["bot"]["manage_roles"] is True


def test_blueprint_encodes_four_identity_visibility_matrix() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    categories = {category.key: category for category in blueprint.categories}
    channels = {
        channel.key: channel for category in blueprint.categories for channel in category.channels
    }

    general = desired_category_permissions(categories["start"])
    members = desired_category_permissions(categories["members"])
    manager = desired_category_permissions(categories["manager"])
    deferred_lab = desired_category_permissions(categories["lab"])
    assert {key: value["view_channel"] for key, value in general.items()} == {
        "everyone": True,
        "newcomer": True,
        "member": True,
        "manager": True,
        "bot": True,
    }
    assert {key: value["view_channel"] for key, value in members.items()} == {
        "everyone": False,
        "newcomer": False,
        "member": True,
        "manager": True,
        "bot": True,
    }
    assert {key: value["view_channel"] for key, value in manager.items()} == {
        "everyone": False,
        "newcomer": False,
        "member": False,
        "manager": True,
        "bot": True,
    }
    assert "owner" not in deferred_lab
    assert deferred_lab["manager"]["view_channel"] is False
    assert deferred_lab["newcomer"]["view_channel"] is False

    owner_only = desired_channel_permissions(channels["system_alerts"])
    assert {subject: values["view_channel"] for subject, values in owner_only.items()} == {
        "everyone": False,
        "newcomer": False,
        "member": False,
        "manager": False,
        "bot": True,
        "owner": True,
    }


def test_newcomer_permission_matrix_is_explicit_and_fail_closed() -> None:
    blueprint = load_blueprint(ROOT / "config" / "discord_blueprint.yaml")
    channels = {
        channel.key: desired_channel_permissions(channel)
        for category in blueprint.categories
        for channel in category.channels
    }
    allowed = {"welcome", "official_results", "member_wins"}
    for key, permissions in channels.items():
        newcomer = permissions["newcomer"]
        assert newcomer["view_channel"] is (key in allowed)
        assert newcomer["send_messages"] is False
        assert newcomer["read_message_history"] is (key in allowed)
        assert newcomer["attach_files"] is False


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
