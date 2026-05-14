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
import asyncio
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

    async def delete(self) -> None:
        pass  # no-op; slash command interactions can't be deleted like messages


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


# ── Lore paginator ───────────────────────────────────────────────────────────

class LoreListView(discord.ui.View):
    """Paginated embed browser for the lore database."""
    PER_PAGE = 10

    def __init__(self, entries: list):
        super().__init__(timeout=120)
        self.entries = entries
        self.page = 0
        self.total_pages = max(1, (len(entries) + self.PER_PAGE - 1) // self.PER_PAGE)
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_btn.disabled = (self.page == 0)
        self.next_btn.disabled = (self.page >= self.total_pages - 1)

    def build_embed(self) -> discord.Embed:
        start = self.page * self.PER_PAGE
        page_entries = self.entries[start : start + self.PER_PAGE]
        embed = discord.Embed(
            title=f"📚 Lore Database — {len(self.entries)} entries",
            color=discord.Color.dark_purple(),
        )
        embed.set_footer(text=f"Page {self.page + 1} of {self.total_pages}  ·  Use /lore view <title> to read a full entry")
        for entry in page_entries:
            preview = entry['content']
            if len(preview) > 120:
                preview = preview[:120] + "..."
            kw_str = ", ".join(entry['keywords'][:6]) if entry['keywords'] else "none"
            embed.add_field(
                name=entry['title'],
                value=f"{preview}\n*Keywords: {kw_str}*",
                inline=False,
            )
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


# ── Offboard helpers ─────────────────────────────────────────────────────────

async def _member_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice]:
    """Autocomplete for discord members across all guilds the bot is in."""
    logger.info(f"[autocomplete] _member_autocomplete called, current={repr(current)}")
    try:
        seen = set()
        choices = []
        current_lower = current.lower()
        for guild in interaction.client.guilds:
            members = list(guild.members)
            logger.info(f"[autocomplete] guild={guild.name!r} cache_size={len(members)}")
            for member in members:
                if member.bot or member.id in seen:
                    continue
                seen.add(member.id)
                display = member.display_name or member.name
                username = member.name
                if current_lower and current_lower not in display.lower() and current_lower not in username.lower():
                    continue
                label = f"{display} ({username})"[:100]
                if not label.strip():
                    continue
                choices.append(app_commands.Choice(name=label, value=str(member.id)))
                if len(choices) >= 25:
                    return choices
        logger.info(f"[autocomplete] returning {len(choices)} choices")
        return choices
    except Exception as e:
        logger.error(f"[autocomplete] error: {e}", exc_info=True)
        return []


async def _find_user_channels(client: discord.Client, user_id: int) -> dict:
    """Returns {guild: [channel, ...]} for private text channels the user can read, across all guilds."""
    found = {}
    for guild in client.guilds:
        member = guild.get_member(user_id)
        if not member:
            continue
        me = guild.me
        everyone = guild.default_role
        channels = []
        for channel in guild.text_channels:
            try:
                member_perms = channel.permissions_for(member)
                bot_perms = channel.permissions_for(me)
                everyone_perms = channel.permissions_for(everyone)
                if member_perms.read_messages and bot_perms.read_messages and not everyone_perms.read_messages:
                    channels.append(channel)
            except Exception:
                continue
        if channels:
            found[guild] = channels
    return found


async def _get_archived_channel_ids(firestore_client, channel_ids: list) -> set:
    """Returns the subset of channel_ids that have an archived_channels Firestore record."""
    if not firestore_client or not channel_ids:
        return set()
    archived = set()
    try:
        for ch_id in channel_ids:
            cid = str(ch_id)
            doc = await asyncio.to_thread(
                lambda cid=cid: firestore_client.collection('archived_channels').document(cid).get()
            )
            if doc.exists:
                archived.add(ch_id)
    except Exception as e:
        logger.warning(f"Could not check archived_channels collection: {e}")
    return archived


def _build_offboard_header(user: discord.Member, channels_by_guild: dict, archived_ids: set) -> discord.Embed:
    """Summary embed posted once at the top of an offboard session."""
    total = sum(len(chs) for chs in channels_by_guild.values())
    already_count = sum(
        1 for chs in channels_by_guild.values() for ch in chs if ch.id in archived_ids
    )
    embed = discord.Embed(
        title=f"🚪 Offboard: {user.display_name} ({user.name})",
        color=discord.Color.orange(),
    )
    if total == 0:
        embed.description = f"No private channels found for {user.mention}."
    else:
        embed.description = (
            f"Found **{total}** private channel(s) for {user.mention} "
            f"across **{len(channels_by_guild)}** server(s)"
            + (f" — {already_count} already archived." if already_count else ".")
        )
        embed.set_footer(text="Archive sends the PDF to that channel. Remove exits the player from the channel.")
    return embed


class _OffboardMsg:
    """Message shim for ArchiveChannel.run() — routes all archive output to the target channel itself."""

    class _Proxy:
        def __init__(self, ch):
            self._ch = ch
            self.id = ch.id
            self.name = getattr(ch, 'name', '')
            self.mention = f"<#{ch.id}>"
            self.guild = getattr(ch, 'guild', None)

        async def send(self, content=None, **kwargs):
            return await self._ch.send(content, **kwargs)

        def permissions_for(self, member):
            return self._ch.permissions_for(member)

    def __init__(self, target: discord.TextChannel, author):
        self.guild = target.guild
        self.author = author
        self.content = ""
        # No channel_mentions → archive_channel.run() uses message.channel as the target,
        # so all status updates and the final PDF land in the target channel itself.
        self.channel_mentions = []
        self.channel = self._Proxy(target)

    async def add_reaction(self, emoji: str) -> None:
        pass


class ChannelOffboardView(discord.ui.View):
    """One Archive + one Remove button for a single channel in the offboard workflow.
    Each channel gets its own message; clicking a button edits that message in place."""

    def __init__(self, channel: discord.TextChannel, user: discord.Member, archive_handler, client: discord.Client):
        super().__init__(timeout=None)
        self.channel = channel
        self.user = user
        self.archive_handler = archive_handler
        self.client = client

    @discord.ui.button(label="Archive", style=discord.ButtonStyle.primary)
    async def archive(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_admin(interaction):
            await interaction.response.send_message("🚫 Admin only.", ephemeral=True)
            return
        await interaction.response.edit_message(
            content=f"{self.channel.mention} **({self.channel.guild.name})** — 📦 Archive queued",
            view=None,
        )
        self.stop()
        msg = _OffboardMsg(self.channel, interaction.user)
        await self.archive_handler.run(self.client, msg)

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_admin(interaction):
            await interaction.response.send_message("🚫 Admin only.", ephemeral=True)
            return
        member = self.channel.guild.get_member(self.user.id)
        if not member:
            await interaction.response.edit_message(
                content=f"{self.channel.mention} **({self.channel.guild.name})** — ❌ User not in server",
                view=None,
            )
            self.stop()
            return
        try:
            await self.channel.set_permissions(member, overwrite=None)
            await self.channel.send(
                f"(( {self.user.display_name} has been removed from this channel. ))"
            )
            await interaction.response.edit_message(
                content=f"{self.channel.mention} **({self.channel.guild.name})** — ✅ Removed",
                view=None,
            )
        except discord.Forbidden:
            await interaction.response.edit_message(
                content=f"{self.channel.mention} **({self.channel.guild.name})** — ❌ Missing permissions",
                view=None,
            )
        except Exception as e:
            logger.error(f"Offboard remove failed for {self.channel.name}: {e}")
            await interaction.response.edit_message(
                content=f"{self.channel.mention} **({self.channel.guild.name})** — ❌ Failed: {e}",
                view=None,
            )
        self.stop()


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
        result = await huh_instance.run(client, ctx)
        if result is None:
            await interaction.followup.send("No match found — check your DMs for suggestions.", ephemeral=True)
        elif isinstance(result, list):
            for chunk in result:
                await interaction.followup.send(chunk)
        else:
            await interaction.followup.send(result)

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

    @lore_grp.command(name="search", description="Search lore entries by title (admin only)")
    @app_commands.describe(query="Partial title to search for (e.g. 'cam' finds 'Camarilla')")
    async def lore_search(interaction: discord.Interaction, query: str):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        if not lore_manager:
            await interaction.response.send_message("❌ Lore database unavailable.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        matches = await lore_manager.search_entries(query)
        if not matches:
            await interaction.followup.send(
                f"No lore entries found matching **{query}**.\n"
                f"Use `/lore list` to browse all entries."
            )
            return
        embed = discord.Embed(
            title=f"🔍 Lore Search: \"{query}\"",
            description=f"{len(matches)} result{'s' if len(matches) != 1 else ''} found",
            color=discord.Color.dark_purple(),
        )
        for entry in matches[:10]:
            preview = entry['content']
            if len(preview) > 200:
                preview = preview[:200] + "..."
            kw_str = ", ".join(entry['keywords']) if entry['keywords'] else "none"
            embed.add_field(
                name=entry['title'],
                value=f"{preview}\n*Keywords: {kw_str}*",
                inline=False,
            )
        if len(matches) > 10:
            embed.set_footer(text=f"Showing first 10 of {len(matches)} matches — refine your search to narrow results.")
        await interaction.followup.send(embed=embed)

    @lore_grp.command(name="list", description="Browse all lore entries (admin only)")
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
        view = LoreListView(entries)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @lore_grp.command(name="view", description="View a lore entry in full (admin only)")
    @app_commands.describe(title="Title of the entry to view")
    @app_commands.autocomplete(title=_title_autocomplete)
    async def lore_view(interaction: discord.Interaction, title: str):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        if not lore_manager:
            await interaction.response.send_message("❌ Lore database unavailable.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        entry = await lore_manager.get_entry(title)
        if not entry:
            await interaction.followup.send(
                f"❌ No entry found with title **{title}**.\n"
                f"Use `/lore list` to browse all entries or `/lore search` to find by partial title."
            )
            return
        embed = discord.Embed(
            title=entry['title'],
            description=entry['content'],
            color=discord.Color.dark_purple(),
        )
        kw_str = ", ".join(entry['keywords']) if entry['keywords'] else "none"
        embed.add_field(name="Keywords", value=kw_str, inline=False)
        await interaction.followup.send(embed=embed)

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

    @ls_grp.command(name="waiting-for-st", description="List channels waiting for a Storyteller response (admin only)")
    async def ls_waiting_for_st(interaction: discord.Interaction):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()
        ctx = InteractionContext(interaction, content="/lotslarp waiting-for-st")
        await lotslarp_instance.waiting_for_st_handler.run(client, ctx)

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

    @ls_grp.command(name="offboard", description="Archive a player's private channels (admin only)")
    @app_commands.describe(member="Player name to offboard (type to search across all servers)")
    @app_commands.autocomplete(member=_member_autocomplete)
    async def ls_offboard(interaction: discord.Interaction, member: str):
        if not _is_admin(interaction):
            await _deny(interaction)
            return
        await interaction.response.defer()

        # Resolve user ID → Member object from any guild
        try:
            user_id = int(member)
        except ValueError:
            await interaction.followup.send("❌ Invalid selection — please choose from the autocomplete list.", ephemeral=True)
            return

        resolved: discord.Member | None = None
        for guild in client.guilds:
            m = guild.get_member(user_id)
            if m:
                resolved = m
                break
        if not resolved:
            await interaction.followup.send("❌ Member not found in any server.", ephemeral=True)
            return

        found = await _find_user_channels(client, user_id)
        all_ids = [ch.id for chs in found.values() for ch in chs]
        archived_ids = await _get_archived_channel_ids(firestore_client, all_ids)

        # Header summary
        header = _build_offboard_header(resolved, found, archived_ids)
        await interaction.followup.send(embed=header)

        if not found:
            return

        # One message per active channel (with buttons); collect archived ones for a single trailing message
        already_archived_lines = []
        for guild, channels in found.items():
            for ch in channels:
                if ch.id in archived_ids:
                    already_archived_lines.append(f"• {ch.mention} **({guild.name})**")
                else:
                    view = ChannelOffboardView(
                        channel=ch,
                        user=resolved,
                        archive_handler=lotslarp_instance.archive_handler,
                        client=client,
                    )
                    await interaction.followup.send(
                        content=f"{ch.mention} **({guild.name})**",
                        view=view,
                    )

        if already_archived_lines:
            await interaction.followup.send(
                content="✅ **Already archived:**\n" + "\n".join(already_archived_lines)
            )

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
