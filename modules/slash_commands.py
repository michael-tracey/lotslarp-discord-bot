"""
Slash command registration for the LOTSLARP Discord bot.

All commands use discord.app_commands. Administrative commands check for the
configured admin role before proceeding.

The InteractionContext shim lets existing module handlers (which expect a
discord.Message) work with slash command interactions without modification:
defer the interaction first, then construct InteractionContext, then call the
handler's run() method — all channel.send() calls route to followup.send().
"""
import os
import discord
from discord import app_commands
import logging
from modules.archive_cleanup import cleanup_old_archives
from modules.utils import get_admin_roles

logger = logging.getLogger(__name__)


# ── Interaction compatibility shim ────────────────────────────────────────────

class _ChannelProxy:
    """Routes channel.send() calls to interaction.followup.send().

    Interaction must be deferred before any send() call.
    """

    def __init__(self, interaction: discord.Interaction):
        self._itx = interaction
        ch = interaction.channel
        self.id = interaction.channel_id
        self.name = getattr(ch, 'name', '')
        self.mention = f"<#{interaction.channel_id}>"
        self.guild = interaction.guild

    def permissions_for(self, member: discord.Member) -> discord.Permissions:
        ch = self._itx.channel
        return ch.permissions_for(member) if ch else discord.Permissions.none()

    async def send(self, content=None, **kwargs) -> discord.WebhookMessage:
        return await self._itx.followup.send(content or "​", **kwargs)


class InteractionContext:
    """Adapts a deferred discord.Interaction to look like discord.Message.

    Construct AFTER calling await interaction.response.defer().
    Set channel_mentions to pass real TextChannel objects to handlers that
    inspect message.channel_mentions (e.g. archive, summarize).
    Set content to pass argument strings to handlers that parse message.content.
    """

    def __init__(
        self,
        interaction: discord.Interaction,
        content: str = "",
        channel_mentions: list = None,
    ):
        self._itx = interaction
        self.author = interaction.user
        self.guild = interaction.guild
        self.content = content
        self.channel_mentions = channel_mentions or []
        self.channel = _ChannelProxy(interaction)

    async def add_reaction(self, emoji: str) -> None:
        pass  # no-op; interactions don't support reactions


# ── Permission helper ─────────────────────────────────────────────────────────

def _is_admin(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    admin_roles = get_admin_roles()
    return any(r.name in admin_roles for r in interaction.user.roles)


async def _deny(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        "🚫 You do not have permission to run this command.", ephemeral=True
    )


# ── Registration ──────────────────────────────────────────────────────────────

def register_slash_commands(
    tree: app_commands.CommandTree,
    client: discord.Client,
    lotslarp_instance,
    huh_instance,
    lore_manager,
    firestore_client,
) -> None:
    """Registers all application commands onto the provided CommandTree."""

    # ── /huh ─────────────────────────────────────────────────────────────────

    @tree.command(name="huh", description="Look up a rules or lore entry")
    @app_commands.describe(question="What would you like to know?")
    async def huh_cmd(interaction: discord.Interaction, question: str):
        if not huh_instance:
            await interaction.response.send_message("❌ Lookup module unavailable.", ephemeral=True)
            return
        await interaction.response.defer()
        ctx = InteractionContext(interaction, content=f"/huh {question}")
        await huh_instance.run(client, ctx)

    # ── /lore ─────────────────────────────────────────────────────────────────

    lore_grp = app_commands.Group(name="lore", description="Manage the game lore database")

    async def _title_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice]:
        if not lore_manager:
            return []
        try:
            titles = await lore_manager.get_titles()
            return [
                app_commands.Choice(name=t, value=t)
                for t in titles
                if current.lower() in t.lower()
            ][:25]
        except Exception:
            return []

    @lore_grp.command(name="search", description="Search lore entries by keyword (admin only)")
    @app_commands.describe(query="Keyword or phrase to look up")
    async def lore_search(interaction: discord.Interaction, query: str):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        if not lore_manager:
            await interaction.response.send_message("❌ Lore database unavailable.", ephemeral=True)
            return
        await interaction.response.defer()
        result = await lore_manager.get_relevant_lore(query)
        if result:
            for chunk in [result[i:i + 1990] for i in range(0, len(result), 1990)]:
                await interaction.followup.send(chunk)
        else:
            await interaction.followup.send("No lore entries matched that query.")

    @lore_grp.command(name="list", description="List all lore entries (admin only)")
    async def lore_list(interaction: discord.Interaction):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        if not lore_manager:
            await interaction.response.send_message("❌ Lore database unavailable.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        entries = await lore_manager.list_entries()
        if not entries:
            await interaction.followup.send("No lore entries found.")
            return
        lines = [
            f"**{e['title']}** — keywords: {', '.join(e['keywords']) or '(none)'}"
            for e in entries
        ]
        header = f"**Lore Database ({len(entries)} entries)**\n"
        text = header + "\n".join(lines)
        for chunk in [text[i:i + 1990] for i in range(0, len(text), 1990)]:
            await interaction.followup.send(chunk)

    @lore_grp.command(name="add", description="Add a new lore entry (admin only)")
    @app_commands.describe(
        title="Entry title (e.g. 'Camarilla')",
        content="Full description of this lore entry",
        keywords="Comma-separated trigger keywords (e.g. 'camarilla, sect, ivory tower')",
    )
    async def lore_add(
        interaction: discord.Interaction, title: str, content: str, keywords: str
    ):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        if not lore_manager:
            await interaction.response.send_message("❌ Lore database unavailable.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        ok = await lore_manager.add_entry(title, content, kw_list)
        if ok:
            await interaction.followup.send(
                f"✅ Added **{title}** with {len(kw_list)} keyword(s): {', '.join(kw_list) or '(none)'}."
            )
        else:
            await interaction.followup.send("❌ Failed to add entry. Check logs.")

    @lore_grp.command(name="edit", description="Edit an existing lore entry (admin only)")
    @app_commands.describe(
        title="Title of the entry to edit",
        content="New content for this entry",
        keywords="New comma-separated keywords (leave blank to keep existing)",
    )
    @app_commands.autocomplete(title=_title_autocomplete)
    async def lore_edit(
        interaction: discord.Interaction, title: str, content: str, keywords: str = ""
    ):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        if not lore_manager:
            await interaction.response.send_message("❌ Lore database unavailable.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords.strip() else None
        ok = await lore_manager.update_entry(title, content, kw_list)
        if ok:
            kw_note = f" Keywords unchanged." if kw_list is None else f" Keywords: {', '.join(kw_list) or '(none)'}."
            await interaction.followup.send(f"✅ Updated **{title}**.{kw_note}")
        else:
            await interaction.followup.send(
                f"❌ No entry found with title **{title}**. Use `/lore list` to see all titles."
            )

    @lore_grp.command(name="remove", description="Remove a lore entry (admin only)")
    @app_commands.describe(title="Title of the entry to remove")
    @app_commands.autocomplete(title=_title_autocomplete)
    async def lore_remove(interaction: discord.Interaction, title: str):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        if not lore_manager:
            await interaction.response.send_message("❌ Lore database unavailable.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ok = await lore_manager.remove_entry(title)
        if ok:
            await interaction.followup.send(f"✅ Removed lore entry **{title}**.")
        else:
            await interaction.followup.send(
                f"❌ No entry found with title **{title}**. Use `/lore list` to see all titles."
            )

    tree.add_command(lore_grp)

    # ── /lotslarp ─────────────────────────────────────────────────────────────

    ls_grp = app_commands.Group(name="lotslarp", description="LOTSLARP bot administration")

    @ls_grp.command(name="status", description="Show bot health status (admin only)")
    async def ls_status(interaction: discord.Interaction):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        ctx = InteractionContext(interaction, content="/lotslarp status")
        await lotslarp_instance.status_handler.run(client, ctx)

    @ls_grp.command(name="instructions", description="Show detailed bot instructions (admin only)")
    async def ls_instructions(interaction: discord.Interaction):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        ctx = InteractionContext(interaction, content="/lotslarp instructions")
        await lotslarp_instance.instructions_handler.run(client, ctx)

    @ls_grp.command(name="archive", description="Export a channel to PDF and make it read-only (admin only)")
    @app_commands.describe(channel="Channel to archive (defaults to current channel)")
    async def ls_archive(
        interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        target = channel or interaction.channel
        await interaction.response.defer()
        ctx = InteractionContext(
            interaction,
            channel_mentions=[target] if channel else [],
        )
        await lotslarp_instance.archive_handler.run(client, ctx)

    @ls_grp.command(name="unarchive", description="Restore an archived channel (admin only)")
    @app_commands.describe(channel="Channel to unarchive (defaults to current channel)")
    async def ls_unarchive(
        interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        target = channel or interaction.channel
        await interaction.response.defer()
        ctx = InteractionContext(
            interaction,
            channel_mentions=[target] if channel else [],
        )
        await lotslarp_instance.unarchive_handler.run(client, ctx)

    @ls_grp.command(name="summarize", description="Generate an AI summary for a channel (admin only)")
    @app_commands.describe(channel="Channel to summarize")
    async def ls_summarize(interaction: discord.Interaction, channel: discord.TextChannel):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        ctx = InteractionContext(
            interaction,
            content=f"/summarize <#{channel.id}>",
            channel_mentions=[channel],
        )
        result = await lotslarp_instance.summarize_handler.run(client, ctx)
        if result:
            await interaction.followup.send(result)

    @ls_grp.command(name="stale", description="Find channels that need summaries (admin only)")
    @app_commands.describe(
        limit="Max channels to report (omit for all)",
        auto_send="Automatically send reminder messages without prompting",
    )
    async def ls_stale(
        interaction: discord.Interaction,
        limit: int = None,
        auto_send: bool = False,
    ):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        parts = [str(limit) if limit is not None else "all"]
        if auto_send:
            parts.append("run")
        ctx = InteractionContext(interaction, content="/stale-channels " + " ".join(parts))
        await lotslarp_instance.stale_handler.run(client, ctx)

    @ls_grp.command(name="purge-archives", description="Manually run the archive deletion job (admin only)")
    async def ls_purge(interaction: discord.Interaction):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        ctx = InteractionContext(interaction)
        await ctx.channel.send("⚙️ Manually triggering archive cleanup task...")
        await cleanup_old_archives(client, firestore_client)
        await ctx.channel.send("✅ Archive cleanup task finished.")

    # ── /lotslarp report ──────────────────────────────────────────────────────

    report_grp = app_commands.Group(name="report", description="Generate reports")

    @report_grp.command(name="voice", description="Voice activity report (admin only)")
    @app_commands.describe(days="Number of days to look back (default: 7)")
    async def rpt_voice(interaction: discord.Interaction, days: int = 7):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        if not lotslarp_instance.voice_handler:
            await interaction.response.send_message(
                "❌ Voice module unavailable (database not connected).", ephemeral=True
            )
            return
        await interaction.response.defer()
        ctx = InteractionContext(interaction, content=f"/voice-report {days}")
        await lotslarp_instance.voice_handler.run(client, ctx)

    @report_grp.command(name="digest", description="Generate a message digest (admin only)")
    @app_commands.describe(period="Time period for the digest")
    @app_commands.choices(period=[
        app_commands.Choice(name="Now — send all cached messages immediately", value="now"),
        app_commands.Choice(name="Last 24 hours", value="day"),
        app_commands.Choice(name="Last 7 days", value="week"),
        app_commands.Choice(name="Last 30 days", value="month"),
    ])
    async def rpt_digest(interaction: discord.Interaction, period: str = "month"):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        if period == "now":
            ctx = InteractionContext(interaction, content="/digest-now")
            await lotslarp_instance.digest_handler.run(client, ctx)
        else:
            ctx = InteractionContext(interaction, content=f"/digest {period}")
            await lotslarp_instance.digest_range_handler.run(client, ctx)

    @report_grp.command(name="month", description="Monthly game cycle summary (admin only)")
    async def rpt_month(interaction: discord.Interaction):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        ctx = InteractionContext(interaction, content="/summarize-month")
        await lotslarp_instance.monthly_handler.run(client, ctx)

    ls_grp.add_command(report_grp)

    # ── /lotslarp group ───────────────────────────────────────────────────────

    group_grp = app_commands.Group(name="group", description="Manage channel groups")

    @group_grp.command(name="list", description="List all channel groups (admin only)")
    async def grp_list(interaction: discord.Interaction):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        ctx = InteractionContext(interaction, content="/lotslarp group list")
        await lotslarp_instance.group_handler.run(client, ctx)

    @group_grp.command(name="add", description="Add a channel to a group (admin only)")
    @app_commands.describe(name="Group name", channel="Channel to add to the group")
    async def grp_add(
        interaction: discord.Interaction, name: str, channel: discord.TextChannel
    ):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        ctx = InteractionContext(
            interaction,
            content=f"/lotslarp group {name} add <#{channel.id}>",
            channel_mentions=[channel],
        )
        await lotslarp_instance.group_handler.run(client, ctx)

    @group_grp.command(name="remove", description="Remove a channel from a group (admin only)")
    @app_commands.describe(name="Group name", channel="Channel to remove from the group")
    async def grp_remove(
        interaction: discord.Interaction, name: str, channel: discord.TextChannel
    ):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        ctx = InteractionContext(
            interaction,
            content=f"/lotslarp group {name} remove <#{channel.id}>",
            channel_mentions=[channel],
        )
        await lotslarp_instance.group_handler.run(client, ctx)

    @group_grp.command(name="rename", description="Rename a channel group (admin only)")
    @app_commands.describe(name="Current group name", new_name="New name for the group")
    async def grp_rename(interaction: discord.Interaction, name: str, new_name: str):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        ctx = InteractionContext(
            interaction,
            content=f"/lotslarp group {name} rename {new_name}",
        )
        await lotslarp_instance.group_handler.run(client, ctx)

    @group_grp.command(name="summarize", description="AI summary of all channels in a group (admin only)")
    @app_commands.describe(name="Group name to summarize")
    async def grp_summarize(interaction: discord.Interaction, name: str):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        ctx = InteractionContext(
            interaction,
            content=f"/lotslarp group {name} summarize",
        )
        await lotslarp_instance.group_handler.run(client, ctx)

    ls_grp.add_command(group_grp)

    tree.add_command(ls_grp)
    logger.info("All slash commands registered to tree.")
