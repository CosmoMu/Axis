from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import discord

from app.bot.blueprint import (
    Blueprint,
    BootstrapPlan,
    CategoryState,
    ChannelState,
    GuildState,
    RoleState,
    build_plan,
    desired_category_permissions,
    desired_channel_permissions,
    load_blueprint,
    write_report,
)
from app.config import ConfigurationError, Settings

CONTROLLED_PERMISSION_NAMES = (
    "view_channel",
    "send_messages",
    "read_message_history",
    "attach_files",
    "embed_links",
    "manage_messages",
)


def _overwrite_values(overwrite: discord.PermissionOverwrite) -> dict[str, bool | None]:
    return {name: getattr(overwrite, name) for name in CONTROLLED_PERMISSION_NAMES}


def _serialize_overwrites(
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite],
) -> dict[str, dict[str, bool | None]]:
    return {
        str(target.id): _overwrite_values(overwrite) for target, overwrite in overwrites.items()
    }


def _find_bot_managed_role(guild: discord.Guild) -> discord.Role | None:
    member = guild.me
    if member is None:
        return None
    for role in member.roles:
        tags = role.tags
        if role.managed and tags is not None and tags.bot_id == member.id:
            return role
    return None


def snapshot_guild(guild: discord.Guild) -> GuildState:
    member = guild.me
    if member is None:
        raise ConfigurationError("无法读取 Bot 在目标 Guild 中的 Member。")
    bot_role = _find_bot_managed_role(guild)
    permission_names = tuple(sorted(name for name, allowed in member.guild_permissions if allowed))
    roles = tuple(
        RoleState(
            id=role.id,
            name=role.name,
            managed=role.managed,
            position=role.position,
            permissions=tuple(sorted(name for name, allowed in role.permissions if allowed)),
        )
        for role in sorted(guild.roles, key=lambda item: item.position, reverse=True)
    )
    categories = tuple(
        CategoryState(
            id=category.id,
            name=category.name,
            position=category.position,
            overwrites=_serialize_overwrites(category.overwrites),
        )
        for category in sorted(guild.categories, key=lambda item: item.position)
    )
    channels = tuple(
        ChannelState(
            id=channel.id,
            name=channel.name,
            type="text" if isinstance(channel, discord.TextChannel) else str(channel.type),
            category_id=channel.category_id,
            position=channel.position,
            topic=channel.topic if isinstance(channel, discord.TextChannel) else None,
            overwrites=_serialize_overwrites(channel.overwrites),
        )
        for channel in sorted(guild.channels, key=lambda item: (item.position, item.id))
        if not isinstance(channel, discord.CategoryChannel)
    )
    return GuildState(
        id=guild.id,
        name=guild.name,
        owner_id=guild.owner_id,
        bot_user_id=member.id,
        bot_role_id=bot_role.id if bot_role else None,
        bot_permissions=permission_names,
        roles=roles,
        categories=categories,
        channels=channels,
    )


class InventoryClient(discord.Client):
    def __init__(self, expected_guild_id: int) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents)
        self.expected_guild_id = expected_guild_id
        self.guild_result: asyncio.Future[discord.Guild] | None = None

    async def on_ready(self) -> None:
        if self.guild_result is None or self.guild_result.done():
            return
        guild = self.get_guild(self.expected_guild_id)
        if guild is None:
            available_ids = ", ".join(str(item.id) for item in self.guilds) or "无"
            self.guild_result.set_exception(
                ConfigurationError(
                    f"Bot 不在目标 Guild {self.expected_guild_id} 中；"
                    f"当前可见 Guild ID：{available_ids}。"
                )
            )
        else:
            self.guild_result.set_result(guild)


async def connect_target_guild(
    token: str,
    guild_id: int,
) -> tuple[InventoryClient, discord.Guild, asyncio.Task[None]]:
    client = InventoryClient(guild_id)
    loop = asyncio.get_running_loop()
    client.guild_result = loop.create_future()
    try:
        await client.login(token)
    except Exception:
        await client.close()
        raise
    gateway_task = asyncio.create_task(client.connect(reconnect=False))
    try:
        guild = await asyncio.wait_for(client.guild_result, timeout=45)
        return client, guild, gateway_task
    except Exception:
        await client.close()
        await asyncio.gather(gateway_task, return_exceptions=True)
        raise


def _print_inventory(state: GuildState) -> None:
    print("\n=== 只读服务器盘点 ===")
    print(f"Guild: {state.name} ({state.id})")
    print(f"Owner ID: {state.owner_id}")
    print(f"Bot User ID: {state.bot_user_id}")
    print("Roles:")
    for role in state.roles:
        suffix = " [managed]" if role.managed else ""
        print(f"  - {role.name} ({role.id}) position={role.position}{suffix}")
    print("Categories / Channels:")
    channels_by_category: dict[int | None, list[ChannelState]] = {}
    for channel in state.channels:
        channels_by_category.setdefault(channel.category_id, []).append(channel)
    for category in state.categories:
        print(f"  - {category.name} ({category.id}) position={category.position}")
        for channel in channels_by_category.get(category.id, []):
            print(f"      - {channel.name} ({channel.id}) type={channel.type}")
    for channel in channels_by_category.get(None, []):
        print(f"  - [无 Category] {channel.name} ({channel.id}) type={channel.type}")


def _print_plan(plan: BootstrapPlan) -> None:
    print("\n=== Discord Bootstrap dry-run ===")
    print(f"已确认目标 Guild ID: {plan.guild_id}")
    summary = plan.to_dict()["summary"]
    print("计划汇总: " + ", ".join(f"{key}={value}" for key, value in summary.items()))
    for action in plan.actions:
        identifier = f" id={action.current_id}" if action.current_id else ""
        print(
            f"[{action.status}] {action.resource_type} {action.name}{identifier}: {action.detail}"
        )
    for warning in plan.warnings:
        print(f"[INFO] {warning}")


def _role_matches(guild: discord.Guild, name: str) -> list[discord.Role]:
    return [role for role in guild.roles if role.name == name]


def _category_matches(guild: discord.Guild, name: str) -> list[discord.CategoryChannel]:
    return [category for category in guild.categories if category.name == name]


def _payload_id(saved_ids: dict[str, Any], section: str, key: str) -> int | None:
    value = saved_ids.get(section, {}).get(key)
    return value if isinstance(value, int) and value > 0 else None


def _load_saved_ids(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("config/discord_ids.json 无法安全读取。") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError("config/discord_ids.json 顶层必须是 JSON object。")
    return payload


async def _create_or_reuse_roles(
    guild: discord.Guild,
    blueprint: Blueprint,
    saved_ids: dict[str, Any],
) -> dict[str, discord.Role]:
    bot_role = _find_bot_managed_role(guild)
    if bot_role is None or bot_role.name != blueprint.role_by_key["bot"].name:
        raise ConfigurationError("Bot managed Role 未通过 dry-run 校验，拒绝写入。")
    saved_bot_id = _payload_id(saved_ids, "roles", "bot")
    if saved_bot_id and guild.get_role(saved_bot_id) is not None and saved_bot_id != bot_role.id:
        raise ConfigurationError("保存的 Bot Role ID 不属于当前登录 Bot，拒绝写入。")
    result = {"everyone": guild.default_role, "bot": bot_role}
    for spec in blueprint.roles:
        if spec.key == "bot":
            continue
        saved_role_id = _payload_id(saved_ids, "roles", spec.key)
        saved_role = guild.get_role(saved_role_id) if saved_role_id else None
        matches = [saved_role] if saved_role else _role_matches(guild, spec.name)
        if len(matches) > 1:
            raise ConfigurationError(f"Role {spec.name} 有多个同名资源，拒绝写入。")
        if matches:
            role = matches[0]
            if role.name != spec.name:
                raise ConfigurationError(f"保存的 Role {spec.key} 已改名，拒绝自动改名或另建。")
            if role.managed:
                raise ConfigurationError(f"Role {spec.name} 是 managed Role，拒绝复用。")
            permissions = role.permissions
            changed = False
            for forbidden in ("administrator", "manage_roles"):
                if getattr(permissions, forbidden):
                    setattr(permissions, forbidden, False)
                    changed = True
            if changed:
                role = await role.edit(
                    permissions=permissions,
                    reason="AXIS Bootstrap：移除管理员 Role 的高风险权限",
                )
        else:
            role = await guild.create_role(
                name=spec.name,
                permissions=discord.Permissions.none(),
                colour=discord.Colour(int((spec.color_hex or "#000000").lstrip("#"), 16)),
                hoist=spec.hoist,
                mentionable=spec.mentionable,
                reason="AXIS Bootstrap：创建缺失 Role",
            )
        result[spec.key] = role

    bot_position = result["bot"].position
    manager = result["manager"]
    member = result["member"]
    if manager.position >= bot_position or member.position >= bot_position:
        raise ConfigurationError(
            "管理员或会员 Role 高于 Bot Role，Bot 无法安全调整；请 Owner 手动处理。"
        )
    if manager.position <= member.position:
        await manager.edit(position=max(member.position + 1, 1), reason="AXIS Role 顺序")
    return result


async def _create_or_reuse_categories(
    guild: discord.Guild,
    blueprint: Blueprint,
    roles: dict[str, discord.Role],
    saved_ids: dict[str, Any],
) -> dict[str, discord.CategoryChannel]:
    result: dict[str, discord.CategoryChannel] = {}
    for spec in blueprint.categories:
        saved_category_id = _payload_id(saved_ids, "categories", spec.key)
        saved_category = guild.get_channel(saved_category_id) if saved_category_id else None
        if saved_category is not None and not isinstance(saved_category, discord.CategoryChannel):
            raise ConfigurationError(f"保存的 Category {spec.key} ID 指向其他资源类型。")
        matches = [saved_category] if saved_category else _category_matches(guild, spec.name)
        if len(matches) > 1:
            raise ConfigurationError(f"Category {spec.name} 有多个同名资源，拒绝写入。")
        if matches:
            category = matches[0]
            if category.name != spec.name:
                raise ConfigurationError(f"保存的 Category {spec.key} 已改名，拒绝自动改名或另建。")
        else:
            overwrites = {
                roles[subject]: discord.PermissionOverwrite(**values)
                for subject, values in desired_category_permissions(spec).items()
            }
            category = await guild.create_category(
                spec.name,
                overwrites=overwrites,
                reason="AXIS Bootstrap：创建缺失 Category",
            )
        for subject, values in desired_category_permissions(spec).items():
            await _merge_permissions(category, roles[subject], values)
        result[spec.key] = category
    return result


async def _create_or_reuse_channels(
    guild: discord.Guild,
    blueprint: Blueprint,
    roles: dict[str, discord.Role],
    categories: dict[str, discord.CategoryChannel],
    saved_ids: dict[str, Any],
) -> dict[str, discord.TextChannel]:
    result: dict[str, discord.TextChannel] = {}
    for category_spec in blueprint.categories:
        category = categories[category_spec.key]
        for spec in category_spec.channels:
            saved_channel_id = _payload_id(saved_ids, "channels", spec.key)
            saved_channel = guild.get_channel(saved_channel_id) if saved_channel_id else None
            matches = (
                [saved_channel]
                if saved_channel
                else [channel for channel in category.channels if channel.name == spec.name]
            )
            if len(matches) > 1:
                raise ConfigurationError(f"频道 {spec.name} 有多个同名资源，拒绝写入。")
            if matches:
                channel = matches[0]
                if not isinstance(channel, discord.TextChannel):
                    raise ConfigurationError(f"频道 {spec.name} 同名但类型不是 text，拒绝写入。")
                if channel.name != spec.name:
                    raise ConfigurationError(
                        f"保存的 Channel {spec.key} 已改名，拒绝自动改名或另建。"
                    )
                if channel.category_id != category.id:
                    raise ConfigurationError(
                        f"保存的 Channel {spec.key} 不在目标 Category，拒绝自动移动。"
                    )
                if (channel.topic or "") != spec.topic:
                    await channel.edit(topic=spec.topic, reason="AXIS Bootstrap：同步频道主题")
            else:
                overwrites = {
                    roles[subject]: discord.PermissionOverwrite(**values)
                    for subject, values in desired_channel_permissions(spec).items()
                }
                channel = await guild.create_text_channel(
                    spec.name,
                    category=category,
                    topic=spec.topic,
                    overwrites=overwrites,
                    reason="AXIS Bootstrap：创建缺失频道",
                )
            result[spec.key] = channel
    return result


async def _merge_permissions(
    target: discord.abc.GuildChannel,
    role: discord.Role,
    values: dict[str, bool],
) -> None:
    overwrite = target.overwrites_for(role)
    changed = False
    for name, desired in values.items():
        if getattr(overwrite, name) is not desired:
            setattr(overwrite, name, desired)
            changed = True
    if changed:
        await target.set_permissions(
            role,
            overwrite=overwrite,
            reason="AXIS Bootstrap：同步蓝图权限",
        )


async def _apply_permissions(
    blueprint: Blueprint,
    roles: dict[str, discord.Role],
    channels: dict[str, discord.TextChannel],
) -> None:
    for category_spec in blueprint.categories:
        for channel_spec in category_spec.channels:
            channel = channels[channel_spec.key]
            for subject, values in desired_channel_permissions(channel_spec).items():
                await _merge_permissions(channel, roles[subject], values)


def _write_ids(
    path: Path,
    guild: discord.Guild,
    roles: dict[str, discord.Role],
    categories: dict[str, discord.CategoryChannel],
    channels: dict[str, discord.TextChannel],
) -> None:
    payload: dict[str, Any] = {
        "guild_id": guild.id,
        "roles": {key: role.id for key, role in roles.items() if key != "everyone"},
        "categories": {key: category.id for key, category in categories.items()},
        "channels": {key: channel.id for key, channel in channels.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def apply_blueprint(
    guild: discord.Guild,
    blueprint: Blueprint,
    settings: Settings,
    saved_ids: dict[str, Any],
) -> None:
    roles = await _create_or_reuse_roles(guild, blueprint, saved_ids)
    categories = await _create_or_reuse_categories(guild, blueprint, roles, saved_ids)
    channels = await _create_or_reuse_channels(
        guild,
        blueprint,
        roles,
        categories,
        saved_ids,
    )
    await _apply_permissions(blueprint, roles, channels)
    _write_ids(settings.ids_path, guild, roles, categories, channels)


async def run_bootstrap(
    settings: Settings,
    *,
    apply: bool,
    confirmed_guild_id: int | None,
) -> int:
    token = settings.require_token()
    blueprint = load_blueprint(settings.blueprint_path)
    saved_ids = _load_saved_ids(settings.ids_path)
    client, guild, gateway_task = await connect_target_guild(
        token,
        settings.discord_guild_id,
    )
    try:
        state = snapshot_guild(guild)
        if settings.discord_application_id and state.bot_user_id != settings.discord_application_id:
            raise ConfigurationError("DISCORD_APPLICATION_ID 与当前登录 Bot 不一致。")
        if settings.discord_owner_user_id and state.owner_id != settings.discord_owner_user_id:
            raise ConfigurationError("DISCORD_OWNER_USER_ID 与目标 Guild Owner 不一致。")

        plan = build_plan(blueprint, state, settings.discord_guild_id, saved_ids)
        _print_inventory(state)
        _print_plan(plan)
        if not apply:
            write_report(settings.report_path, state, plan)
            print(f"\n只读报告已写入：{settings.report_path}")
            print("服务器修改：0")
            return 1 if plan.blockers else 0

        settings.assert_apply_gate(confirmed_guild_id)
        if plan.blockers:
            raise ConfigurationError("dry-run 存在 BLOCK 项，拒绝写入。")
        await apply_blueprint(guild, blueprint, settings, saved_ids)
        print("\nAXIS 缺失资源与权限已应用。未删除、改名或移动非项目资源。")
        return 0
    finally:
        await client.close()
        await asyncio.gather(gateway_task, return_exceptions=True)
