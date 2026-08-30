from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


class BlueprintError(RuntimeError):
    """Raised when the Discord blueprint is invalid."""


@dataclass(frozen=True, slots=True)
class RoleSpec:
    key: str
    name: str
    managed_by_discord: bool = False
    color_hex: str | None = None
    hoist: bool = False
    mentionable: bool = False


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    key: str
    name: str
    type: str
    topic: str
    permissions: dict[str, bool]


@dataclass(frozen=True, slots=True)
class CategorySpec:
    key: str
    name: str
    position: int
    default_visibility: str | None
    feature_flag: str | None
    channels: tuple[ChannelSpec, ...]


@dataclass(frozen=True, slots=True)
class Blueprint:
    version: int
    server_name: str
    roles: tuple[RoleSpec, ...]
    role_order: tuple[str, ...]
    categories: tuple[CategorySpec, ...]

    @property
    def role_by_key(self) -> dict[str, RoleSpec]:
        return {role.key: role for role in self.roles}

    @property
    def channel_count(self) -> int:
        return sum(len(category.channels) for category in self.categories)


@dataclass(frozen=True, slots=True)
class RoleState:
    id: int
    name: str
    managed: bool
    position: int
    permissions: tuple[str, ...] = ()


def _role_is_below(role: RoleState, reference: RoleState) -> bool:
    """Match Discord's hierarchy ordering when numeric positions are tied."""
    return role.position < reference.position or (
        role.position == reference.position and role.id > reference.id
    )


@dataclass(frozen=True, slots=True)
class CategoryState:
    id: int
    name: str
    position: int
    overwrites: dict[str, dict[str, bool | None]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChannelState:
    id: int
    name: str
    type: str
    category_id: int | None
    position: int
    topic: str | None
    overwrites: dict[str, dict[str, bool | None]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GuildState:
    id: int
    name: str
    owner_id: int
    bot_user_id: int
    bot_role_id: int | None
    bot_permissions: tuple[str, ...]
    roles: tuple[RoleState, ...]
    categories: tuple[CategoryState, ...]
    channels: tuple[ChannelState, ...]


@dataclass(frozen=True, slots=True)
class PlanAction:
    status: str
    resource_type: str
    key: str
    name: str
    detail: str
    current_id: int | None = None


@dataclass(frozen=True, slots=True)
class BootstrapPlan:
    guild_id: int
    guild_name: str
    actions: tuple[PlanAction, ...]
    warnings: tuple[str, ...] = ()

    @property
    def blockers(self) -> tuple[PlanAction, ...]:
        return tuple(action for action in self.actions if action.status == "BLOCK")

    @property
    def changes(self) -> tuple[PlanAction, ...]:
        return tuple(action for action in self.actions if action.status in {"CREATE", "UPDATE"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "guild_name": self.guild_name,
            "summary": {
                status: sum(action.status == status for action in self.actions)
                for status in ("REUSE", "CREATE", "UPDATE", "BLOCK")
            },
            "warnings": list(self.warnings),
            "actions": [asdict(action) for action in self.actions],
        }


def _expect_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BlueprintError(f"{context} 必须是 YAML mapping。")
    return value


def _expect_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise BlueprintError(f"{context} 必须是 YAML list。")
    return value


def _unique(values: list[str], context: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise BlueprintError(f"{context} 有重复值：{', '.join(duplicates)}")


def load_blueprint(path: Path) -> Blueprint:
    raw = _expect_mapping(yaml.safe_load(path.read_text(encoding="utf-8")), "blueprint")
    brand = _expect_mapping(raw.get("brand"), "brand")

    roles: list[RoleSpec] = []
    for index, item in enumerate(_expect_list(raw.get("roles"), "roles")):
        role = _expect_mapping(item, f"roles[{index}]")
        roles.append(
            RoleSpec(
                key=str(role["key"]),
                name=str(role["name"]),
                managed_by_discord=bool(role.get("managed_by_discord", False)),
                color_hex=role.get("color_hex"),
                hoist=bool(role.get("hoist", False)),
                mentionable=bool(role.get("mentionable", False)),
            )
        )

    categories: list[CategorySpec] = []
    channel_keys: list[str] = []
    for category_index, item in enumerate(_expect_list(raw.get("categories"), "categories")):
        category = _expect_mapping(item, f"categories[{category_index}]")
        channels: list[ChannelSpec] = []
        for channel_index, raw_channel in enumerate(
            _expect_list(category.get("channels"), f"categories[{category_index}].channels")
        ):
            channel = _expect_mapping(
                raw_channel,
                f"categories[{category_index}].channels[{channel_index}]",
            )
            channel_type = str(channel["type"])
            if channel_type != "text":
                raise BlueprintError(
                    f"频道 {channel['name']} 类型是 {channel_type}；MVP Bootstrap 仅支持 text。"
                )
            permission_values = {
                str(key): bool(value)
                for key, value in channel.items()
                if key.endswith(("_view", "_send", "_attach", "_manage_messages"))
            }
            channel_spec = ChannelSpec(
                key=str(channel["key"]),
                name=str(channel["name"]),
                type=channel_type,
                topic=str(channel.get("topic", "")),
                permissions=permission_values,
            )
            channels.append(channel_spec)
            channel_keys.append(channel_spec.key)
        categories.append(
            CategorySpec(
                key=str(category["key"]),
                name=str(category["name"]),
                position=int(category["position"]),
                default_visibility=category.get("default_visibility"),
                feature_flag=category.get("feature_flag"),
                channels=tuple(channels),
            )
        )

    role_order = tuple(str(value) for value in _expect_list(raw.get("role_order"), "role_order"))
    _unique([role.key for role in roles], "Role key")
    _unique([role.name for role in roles], "Role name")
    _unique([category.key for category in categories], "Category key")
    _unique([category.name for category in categories], "Category name")
    _unique(channel_keys, "Channel key")

    role_keys = {role.key for role in roles}
    if set(role_order) != role_keys | {"everyone"}:
        raise BlueprintError("role_order 必须包含每个 Role key 和 everyone，且不能包含其他值。")
    managed_roles = [role for role in roles if role.managed_by_discord]
    if len(managed_roles) != 1 or managed_roles[0].key != "bot":
        raise BlueprintError("必须且只能有一个 key=bot 的 Discord managed Role。")

    return Blueprint(
        version=int(raw["version"]),
        server_name=str(brand["server_name"]),
        roles=tuple(roles),
        role_order=role_order,
        categories=tuple(categories),
    )


def desired_category_permissions(category: CategorySpec) -> dict[str, dict[str, bool]]:
    if category.default_visibility == "member":
        visibility = {"everyone": False, "member": True, "manager": True, "bot": True}
    elif category.default_visibility == "manager":
        visibility = {"everyone": False, "member": False, "manager": True, "bot": True}
    elif category.default_visibility == "owner_only":
        visibility = {"everyone": False, "member": False, "manager": False, "bot": True}
    else:
        visibility = {"everyone": True, "member": True, "manager": True, "bot": True}
    return {key: {"view_channel": value} for key, value in visibility.items()}


def desired_channel_permissions(channel: ChannelSpec) -> dict[str, dict[str, bool]]:
    result: dict[str, dict[str, bool]] = {}
    everyone_view = channel.permissions.get("everyone_view", False)
    everyone_send = channel.permissions.get("everyone_send", False)
    defaults = {
        "everyone": (everyone_view, everyone_send),
        "member": (
            channel.permissions.get("member_view", everyone_view),
            channel.permissions.get("member_send", everyone_send),
        ),
        "manager": (
            channel.permissions.get("manager_view", everyone_view),
            channel.permissions.get("manager_send", False),
        ),
        "bot": (True, channel.permissions.get("bot_send", True)),
    }
    for subject, (can_view, can_send) in defaults.items():
        values: dict[str, bool] = {
            "view_channel": can_view,
            "send_messages": can_send,
            "read_message_history": can_view,
        }
        attach_key = f"{subject}_attach"
        values["attach_files"] = channel.permissions.get(attach_key, subject == "bot" and can_send)
        manage_messages_key = f"{subject}_manage_messages"
        if manage_messages_key in channel.permissions:
            values["manage_messages"] = channel.permissions[manage_messages_key]
        if subject == "bot":
            values["embed_links"] = can_send
            values["manage_messages"] = can_send
        result[subject] = values
    return result


def _compare_permissions(
    current: dict[str, dict[str, bool | None]],
    desired: dict[str, dict[str, bool]],
    subject_ids: dict[str, int | None],
) -> list[str]:
    differences: list[str] = []
    for subject, expected in desired.items():
        subject_id = subject_ids.get(subject)
        if subject_id is None:
            differences.append(f"{subject}: Role 尚未创建，权限将在创建后应用")
            continue
        actual = current.get(str(subject_id), {})
        changed = [
            f"{name}={actual.get(name)!r}→{value!r}"
            for name, value in expected.items()
            if actual.get(name) is not value
        ]
        if changed:
            differences.append(f"{subject}: " + ", ".join(changed))
    return differences


def _saved_id(saved_ids: dict[str, Any], section: str, key: str) -> int | None:
    raw = saved_ids.get(section, {}).get(key)
    return raw if isinstance(raw, int) and raw > 0 else None


def build_plan(
    blueprint: Blueprint,
    state: GuildState,
    expected_guild_id: int,
    saved_ids: dict[str, Any] | None = None,
    *,
    allow_axis_renames: bool = False,
) -> BootstrapPlan:
    actions: list[PlanAction] = []
    warnings: list[str] = []
    saved_ids = saved_ids or {}
    if state.name != blueprint.server_name:
        warnings.append(
            f"Guild 当前名称为 {state.name!r}，品牌目标为 {blueprint.server_name!r}；"
            "Bootstrap 不会自动改名，请由 Owner 手动确认。"
        )
    saved_guild_id = saved_ids.get("guild_id")
    if saved_guild_id is not None and saved_guild_id != state.id:
        actions.append(
            PlanAction(
                "BLOCK",
                "guild",
                "saved_guild",
                state.name,
                f"discord_ids.json 属于 Guild {saved_guild_id}，当前连接的是 {state.id}。",
                state.id,
            )
        )
    if state.id != expected_guild_id:
        actions.append(
            PlanAction(
                status="BLOCK",
                resource_type="guild",
                key="guild",
                name=state.name,
                current_id=state.id,
                detail=f"连接到 {state.id}，但目标是 {expected_guild_id}。",
            )
        )

    roles_by_id = {role.id: role for role in state.roles}
    role_ids: dict[str, int | None] = {"everyone": state.id, "bot": state.bot_role_id}
    bot_spec = blueprint.role_by_key["bot"]
    bot_role = roles_by_id.get(state.bot_role_id) if state.bot_role_id else None
    saved_bot_id = _saved_id(saved_ids, "roles", "bot")
    if saved_bot_id and saved_bot_id in roles_by_id and saved_bot_id != state.bot_role_id:
        actions.append(
            PlanAction(
                "BLOCK",
                "role",
                "bot",
                bot_spec.name,
                "discord_ids.json 中的 Bot Role ID 不属于当前登录 Bot。",
                saved_bot_id,
            )
        )
    if bot_role is None:
        actions.append(
            PlanAction("BLOCK", "role", "bot", bot_spec.name, "未找到 Discord 管理的 Bot Role。")
        )
    elif not bot_role.managed:
        actions.append(
            PlanAction(
                "BLOCK",
                "role",
                "bot",
                bot_spec.name,
                "Bot Role 不是 Discord managed Role。",
                bot_role.id,
            )
        )
    elif bot_role.name != bot_spec.name:
        actions.append(
            PlanAction(
                "BLOCK",
                "role",
                "bot",
                bot_spec.name,
                f"Bot managed Role 当前名称为 {bot_role.name!r}；必须先在 Discord 应用端改名。",
                bot_role.id,
            )
        )
    else:
        actions.append(
            PlanAction(
                "REUSE",
                "role",
                "bot",
                bot_spec.name,
                "复用 managed Bot Role。",
                bot_role.id,
            )
        )

    for role_spec in blueprint.roles:
        if role_spec.key == "bot":
            continue
        saved_role_id = _saved_id(saved_ids, "roles", role_spec.key)
        saved_role = roles_by_id.get(saved_role_id) if saved_role_id else None
        matches = (
            [saved_role]
            if saved_role
            else [role for role in state.roles if role.name == role_spec.name]
        )
        if len(matches) > 1:
            actions.append(
                PlanAction(
                    "BLOCK",
                    "role",
                    role_spec.key,
                    role_spec.name,
                    "同名 Role 超过一个，无法安全匹配。",
                )
            )
            role_ids[role_spec.key] = None
        elif not matches:
            actions.append(
                PlanAction(
                    "CREATE",
                    "role",
                    role_spec.key,
                    role_spec.name,
                    "保存的 ID 不存在且无完全同名资源；将创建缺失的 AXIS Role。",
                )
            )
            role_ids[role_spec.key] = None
        elif saved_role and saved_role.name != role_spec.name:
            if saved_role.managed:
                actions.append(
                    PlanAction(
                        "BLOCK",
                        "role",
                        role_spec.key,
                        role_spec.name,
                        "已登记 Role 是 managed Role，不能作为人工 Role 复用。",
                        saved_role.id,
                    )
                )
                role_ids[role_spec.key] = None
            elif allow_axis_renames:
                role_ids[role_spec.key] = saved_role.id
                actions.append(
                    PlanAction(
                        "UPDATE",
                        "role_name",
                        role_spec.key,
                        role_spec.name,
                        f"重命名已登记 AXIS Role：{saved_role.name!r} → {role_spec.name!r}。",
                        saved_role.id,
                    )
                )
                forbidden = sorted({"administrator", "manage_roles"} & set(saved_role.permissions))
                if forbidden:
                    actions.append(
                        PlanAction(
                            "UPDATE",
                            "role_permissions",
                            role_spec.key,
                            role_spec.name,
                            "移除不允许的服务器级权限：" + ", ".join(forbidden),
                            saved_role.id,
                        )
                    )
            else:
                actions.append(
                    PlanAction(
                        "BLOCK",
                        "role",
                        role_spec.key,
                        role_spec.name,
                        f"保存的 Role ID 当前名称为 {saved_role.name!r}；"
                        "需要显式启用 AXIS 重命名。",
                        saved_role.id,
                    )
                )
                role_ids[role_spec.key] = None
        elif matches[0].managed:
            actions.append(
                PlanAction(
                    "BLOCK",
                    "role",
                    role_spec.key,
                    role_spec.name,
                    "同名 Role 是 managed Role，不能作为人工 Role 复用。",
                    matches[0].id,
                )
            )
            role_ids[role_spec.key] = None
        else:
            role = matches[0]
            role_ids[role_spec.key] = role.id
            forbidden = sorted({"administrator", "manage_roles"} & set(role.permissions))
            if forbidden:
                actions.append(
                    PlanAction(
                        "UPDATE",
                        "role_permissions",
                        role_spec.key,
                        role_spec.name,
                        "移除不允许的服务器级权限：" + ", ".join(forbidden),
                        role.id,
                    )
                )
            else:
                actions.append(
                    PlanAction(
                        "REUSE",
                        "role",
                        role_spec.key,
                        role_spec.name,
                        "复用保存 ID 或完全同名 Role。",
                        role.id,
                    )
                )

    bot_permissions = set(state.bot_permissions)
    required_bot_permissions = {"manage_channels", "manage_roles"}
    missing_bot_permissions = required_bot_permissions - bot_permissions
    if not {"view_channel", "read_messages"} & bot_permissions:
        missing_bot_permissions.add("view_channel")
    missing_bot_permissions = sorted(missing_bot_permissions)
    if missing_bot_permissions:
        actions.append(
            PlanAction(
                "BLOCK",
                "bot_permissions",
                "bot",
                bot_spec.name,
                "Bot 缺少 Bootstrap 权限：" + ", ".join(missing_bot_permissions),
                state.bot_user_id,
            )
        )

    manager_role = roles_by_id.get(role_ids.get("manager") or 0)
    member_role = roles_by_id.get(role_ids.get("member") or 0)
    if bot_role is not None:
        for role_key, role in (("manager", manager_role), ("member", member_role)):
            if role is not None and not _role_is_below(role, bot_role):
                actions.append(
                    PlanAction(
                        "BLOCK",
                        "role_hierarchy",
                        role_key,
                        role.name,
                        "Role 不在 Bot managed Role 下方，Bot 无法安全管理。",
                        role.id,
                    )
                )
    if (
        manager_role is not None
        and member_role is not None
        and _role_is_below(manager_role, member_role)
    ):
        actions.append(
            PlanAction(
                "UPDATE",
                "role_hierarchy",
                "manager_member_order",
                "Manager → Member",
                "仅调整 AXIS Role，使 Manager 位于 Member 上方。",
            )
        )

    category_ids: dict[str, int | None] = {}
    categories_by_id = {category.id: category for category in state.categories}
    channels_by_id = {channel.id: channel for channel in state.channels}
    for category_spec in blueprint.categories:
        category: CategoryState | None = None
        saved_category_id = _saved_id(saved_ids, "categories", category_spec.key)
        saved_category = categories_by_id.get(saved_category_id) if saved_category_id else None
        matches = (
            [saved_category]
            if saved_category
            else [category for category in state.categories if category.name == category_spec.name]
        )
        if len(matches) > 1:
            category_ids[category_spec.key] = None
            actions.append(
                PlanAction(
                    "BLOCK",
                    "category",
                    category_spec.key,
                    category_spec.name,
                    "同名 Category 超过一个，无法安全匹配。",
                )
            )
        elif not matches:
            category_ids[category_spec.key] = None
            actions.append(
                PlanAction(
                    "CREATE",
                    "category",
                    category_spec.key,
                    category_spec.name,
                    "保存的 ID 不存在且无完全同名资源；将按蓝图创建缺失的 Category。",
                )
            )
        elif saved_category and saved_category.name != category_spec.name:
            if allow_axis_renames:
                category = saved_category
                category_ids[category_spec.key] = saved_category.id
                actions.append(
                    PlanAction(
                        "UPDATE",
                        "category_name",
                        category_spec.key,
                        category_spec.name,
                        f"重命名已登记 AXIS Category：{saved_category.name!r} → "
                        f"{category_spec.name!r}。",
                        saved_category.id,
                    )
                )
            else:
                category_ids[category_spec.key] = None
                actions.append(
                    PlanAction(
                        "BLOCK",
                        "category",
                        category_spec.key,
                        category_spec.name,
                        f"保存的 Category ID 当前名称为 {saved_category.name!r}；"
                        "需要显式启用 AXIS 重命名。",
                        saved_category.id,
                    )
                )
        else:
            category = matches[0]
            category_ids[category_spec.key] = category.id
            actions.append(
                PlanAction(
                    "REUSE",
                    "category",
                    category_spec.key,
                    category_spec.name,
                    "复用完全同名 Category；不移动非 AXIS Category。",
                    category.id,
                )
            )
        if category is not None:
            differences = _compare_permissions(
                category.overwrites,
                desired_category_permissions(category_spec),
                role_ids,
            )
            if differences:
                actions.append(
                    PlanAction(
                        "UPDATE",
                        "category_permissions",
                        category_spec.key,
                        category_spec.name,
                        "; ".join(differences),
                        category.id,
                    )
                )

        category_id = category_ids[category_spec.key]
        for channel_spec in category_spec.channels:
            saved_channel_id = _saved_id(saved_ids, "channels", channel_spec.key)
            saved_channel = channels_by_id.get(saved_channel_id) if saved_channel_id else None
            matches = (
                [saved_channel]
                if saved_channel
                else [
                    channel
                    for channel in state.channels
                    if channel.category_id == category_id and channel.name == channel_spec.name
                ]
                if category_id is not None
                else []
            )
            if len(matches) > 1:
                actions.append(
                    PlanAction(
                        "BLOCK",
                        "channel",
                        channel_spec.key,
                        channel_spec.name,
                        "目标 Category 内同名 Channel 超过一个，无法安全匹配。",
                    )
                )
                continue
            if not matches:
                actions.append(
                    PlanAction(
                        "CREATE",
                        "channel",
                        channel_spec.key,
                        channel_spec.name,
                        "保存的 ID 不存在且目标 Category 内无完全同名频道；将创建缺失频道。",
                    )
                )
                continue
            channel = matches[0]
            if saved_channel and saved_channel.name != channel_spec.name:
                if allow_axis_renames:
                    actions.append(
                        PlanAction(
                            "UPDATE",
                            "channel_name",
                            channel_spec.key,
                            channel_spec.name,
                            f"重命名已登记 AXIS Channel：{saved_channel.name!r} → "
                            f"{channel_spec.name!r}。",
                            saved_channel.id,
                        )
                    )
                else:
                    actions.append(
                        PlanAction(
                            "BLOCK",
                            "channel",
                            channel_spec.key,
                            channel_spec.name,
                            "保存的 Channel ID 当前名称为 "
                            f"{saved_channel.name!r}；需要显式启用 AXIS 重命名。",
                            saved_channel.id,
                        )
                    )
                    continue
            if channel.type != channel_spec.type:
                actions.append(
                    PlanAction(
                        "BLOCK",
                        "channel",
                        channel_spec.key,
                        channel_spec.name,
                        f"同名资源类型为 {channel.type}，蓝图要求 {channel_spec.type}。",
                        channel.id,
                    )
                )
                continue
            if saved_channel and saved_channel.category_id != category_id:
                actions.append(
                    PlanAction(
                        "BLOCK",
                        "channel",
                        channel_spec.key,
                        channel_spec.name,
                        "保存的 Channel 不在目标 Category；拒绝自动移动，请人工确认。",
                        saved_channel.id,
                    )
                )
                continue
            if channel.name == channel_spec.name:
                actions.append(
                    PlanAction(
                        "REUSE",
                        "channel",
                        channel_spec.key,
                        channel_spec.name,
                        "复用目标 Category 内完全同名文字频道。",
                        channel.id,
                    )
                )
            if (channel.topic or "") != channel_spec.topic:
                actions.append(
                    PlanAction(
                        "UPDATE",
                        "channel_topic",
                        channel_spec.key,
                        channel_spec.name,
                        "频道主题与蓝图不同。",
                        channel.id,
                    )
                )
            differences = _compare_permissions(
                channel.overwrites,
                desired_channel_permissions(channel_spec),
                role_ids,
            )
            if differences:
                actions.append(
                    PlanAction(
                        "UPDATE",
                        "channel_permissions",
                        channel_spec.key,
                        channel_spec.name,
                        "; ".join(differences),
                        channel.id,
                    )
                )

    if blueprint.channel_count != 20:
        warnings.append(f"当前蓝图有 {blueprint.channel_count} 个频道；AXIS 当前规格预期 20 个。")
    if len(blueprint.categories) != 4:
        warnings.append(f"当前蓝图有 {len(blueprint.categories)} 个 Category；MVP 规格预期 4 个。")
    warnings.append("dry-run 不创建长期控制面板；面板将在数据库阶段用 Message ID 保证幂等。")
    warnings.append("AXIS LAB 结构包含在蓝图中，但 FEATURE_LAB_ENABLED 保持 false。")
    return BootstrapPlan(state.id, state.name, tuple(actions), tuple(warnings))


def write_report(path: Path, state: GuildState, plan: BootstrapPlan) -> None:
    payload = {
        "mode": "READ_ONLY_DRY_RUN",
        "guild_inventory": asdict(state),
        "plan": plan.to_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
