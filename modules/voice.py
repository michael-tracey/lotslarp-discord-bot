import discord
import logging
import os
import asyncio
import io
import itertools
import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pytz
from datetime import datetime, timedelta
from google.cloud.firestore_v1 import FieldFilter

logger = logging.getLogger(__name__)

class Voice:
    def __init__(self, firestore_client):
        self.db = firestore_client
        self.active_sessions_ref = self.db.collection('active_voice_sessions')
        self.logs_ref = self.db.collection('voice_logs')
        self.status_logs_ref = self.db.collection('voice_status_logs')
        self.name = "voice-report"
        self.admin_role_name = os.environ.get("LOTSLARP_BOT_ADMIN_USER", "@storytellers").strip("@")
        
        # Load Timezone
        tz_name = os.environ.get("LOTSLARP_BOT_TIMEZONE", "America/New_York")
        try:
            self.timezone = pytz.timezone(tz_name)
            logger.info(f"Voice module using timezone: {tz_name}")
        except Exception as e:
            logger.error(f"Invalid timezone '{tz_name}', defaulting to UTC. Error: {e}")
            self.timezone = pytz.UTC

        try:
            channel_id_str = os.environ.get("LOTSLARP_BOT_VOICE_REPORT_CHANNEL_ID", "0")
            self.report_channel_id = int(channel_id_str.strip().strip('"').strip("'"))
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid LOTSLARP_BOT_VOICE_REPORT_CHANNEL_ID: {e}")
            self.report_channel_id = 0

    def _to_local(self, dt):
        """Converts UTC datetime to local timezone."""
        if not dt: return None
        # Firestore datetimes are usually offset-aware UTC
        if dt.tzinfo:
            return dt.astimezone(self.timezone)
        # If naive, assume UTC and convert
        return pytz.UTC.localize(dt).astimezone(self.timezone)

    async def on_voice_channel_status_update(self, channel, before, after):
        """
        Listener for voice channel status (text status) changes.
        """
        if before.status == after.status:
            return

        try:
            # Fetch audit log to find who changed it
            user_name = "Unknown"
            user_id = None
            
            # Allow a brief moment for audit log to populate
            await asyncio.sleep(1)
            
            async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.voice_channel_status_update):
                if entry.target.id == channel.id:
                    user_name = entry.user.display_name
                    user_id = entry.user.id
                    break
            
            log_entry = {
                'channel_id': channel.id,
                'channel_name': channel.name,
                'guild_id': channel.guild.id,
                'status_text': after.status,
                'user_name': user_name,
                'user_id': user_id,
                'timestamp': datetime.utcnow()
            }
            
            await asyncio.to_thread(self.status_logs_ref.add, log_entry)
            logger.info(f"Voice Status: {channel.name} -> '{after.status}' by {user_name}")

        except Exception as e:
            logger.error(f"Error handling voice status update: {e}", exc_info=True)

    async def on_voice_state_update(self, member, before, after):
        """
        Listener for voice state changes.
        """
        # User joined a channel
        if after.channel and (not before.channel or before.channel.id != after.channel.id):
            logger.debug(f"Detected join/move: {member.display_name} -> {after.channel.name}")
            await self._handle_join(member, after.channel)

        # User left a channel
        if before.channel and (not after.channel or before.channel.id != after.channel.id):
            logger.debug(f"Detected leave/move: {member.display_name} <- {before.channel.name}")
            await self._handle_leave(member, before.channel)

    async def _handle_join(self, member, channel):
        """Logs a user joining a voice channel."""
        try:
            # Check if session already exists (sanity check)
            doc_id = f"{member.id}_{channel.id}"
            
            data = {
                'user_id': member.id,
                'user_name': member.display_name,
                'channel_id': channel.id,
                'channel_name': channel.name,
                'guild_id': channel.guild.id,
                'joined_at': datetime.utcnow()
            }
            # Use set with merge to handle potential race conditions or restarts where user was already "in"
            await asyncio.to_thread(self.active_sessions_ref.document(doc_id).set, data, merge=True)
            logger.info(f"Voice Join: {member.display_name} -> {channel.name}")
        except Exception as e:
            logger.error(f"Error handling voice join: {e}", exc_info=True)

    async def _handle_leave(self, member, channel):
        """Logs a user leaving a voice channel and finalizes the session log."""
        try:
            doc_id = f"{member.id}_{channel.id}"
            doc_ref = self.active_sessions_ref.document(doc_id)
            doc = await asyncio.to_thread(doc_ref.get)
            
            if doc.exists:
                data = doc.to_dict()
                joined_at = data.get('joined_at')
                # Ensure joined_at is datetime
                if joined_at:
                    # Fix for AttributeError: 'DatetimeWithNanoseconds' object has no attribute '_nanosecond'
                    # We explicitly convert the Firestore timestamp object to a standard python datetime
                    if hasattr(joined_at, 'timestamp'):
                        joined_at = datetime.fromtimestamp(joined_at.timestamp(), tz=joined_at.tzinfo)

                    # Firestore returns datetime with timezone info usually
                    now = datetime.utcnow()
                    # Make naive for calculation if needed, or ensure both aware. 
                    # datetime.utcnow() is naive. Firestore datetimes are usually tz-aware UTC.
                    if joined_at.tzinfo:
                        joined_at = joined_at.replace(tzinfo=None)
                    
                    duration = (now - joined_at).total_seconds()
                    
                    log_entry = {
                        'user_id': member.id,
                        'user_name': member.display_name,
                        'channel_id': channel.id,
                        'channel_name': channel.name,
                        'guild_id': channel.guild.id,
                        'joined_at': joined_at,
                        'left_at': now,
                        'duration_seconds': duration
                    }
                    
                    # Add to logs collection
                    await asyncio.to_thread(self.logs_ref.add, log_entry)
                    # Remove from active sessions
                    await asyncio.to_thread(doc_ref.delete)
                    logger.info(f"Voice Leave: {member.display_name} <- {channel.name} (Duration: {duration:.2f}s)")
                else:
                    logger.warning(f"Voice Leave: Found session for {member.display_name} but 'joined_at' was missing.")
                    await asyncio.to_thread(doc_ref.delete)
            else:
                # Session not found (maybe bot restarted or missed the join). 
                # We log a "leave without join" if needed, or just ignore.
                logger.warning(f"Voice Leave: No active session found for {member.display_name} in {channel.name}")

        except Exception as e:
            logger.error(f"Error handling voice leave: {e}", exc_info=True)

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Generates a voice activity report.
        Usage: /voice-report <days>
        """
        # Check Permissions
        has_permission = False
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.name == self.admin_role_name:
                    has_permission = True
                    break
        
        if not has_permission:
            await message.channel.send("🚫 You do not have permission to run this command.")
            return

        parts = message.content.split()
        days = 7 # Default
        if len(parts) == 2 and parts[1].isdigit():
            days = int(parts[1])
        
        await message.channel.send(f"Generating voice report for the last {days} days...", delete_after=10)
        
        # Now returns text AND optional files
        report_text, timeline_file, network_file = await self.generate_report(days)
        
        target_channel = None
        if self.report_channel_id:
            target_channel = client.get_channel(self.report_channel_id)
            if not target_channel:
                logger.warning(f"Configured LOTSLARP_BOT_VOICE_REPORT_CHANNEL_ID {self.report_channel_id} not found.")
        
        if not target_channel:
            target_channel = message.channel
            if self.report_channel_id:
                await message.channel.send(f"⚠️ Configured report channel not found. Sending report here instead.")

        # Chunking
        chunks = [report_text[i:i+1900] for i in range(0, len(report_text), 1900)]
        for chunk in chunks:
            await target_channel.send(chunk)
        
        # Send Files
        files_to_send = []
        if timeline_file:
            files_to_send.append(timeline_file)
        if network_file:
            files_to_send.append(network_file)

        if files_to_send:
            await target_channel.send(files=files_to_send)
        
        # Notify if redirected
        if target_channel.id != message.channel.id:
            await message.channel.send(f"✅ Voice report sent to {target_channel.mention}.")
        else:
            await message.add_reaction("✅")

    async def generate_report(self, days):
        start_date = datetime.utcnow() - timedelta(days=days)
        
        try:
            # Query logs & active sessions
            query_logs = self.logs_ref.where(filter=FieldFilter('joined_at', '>=', start_date)).order_by('channel_name').order_by('joined_at')
            docs_logs = await asyncio.to_thread(lambda: list(query_logs.stream()))
            
            query_active = self.active_sessions_ref.where(filter=FieldFilter('joined_at', '>=', start_date))
            docs_active = await asyncio.to_thread(lambda: list(query_active.stream()))

            # Query status logs
            query_status = self.status_logs_ref.where(filter=FieldFilter('timestamp', '>=', start_date)).order_by('channel_name').order_by('timestamp')
            docs_status = await asyncio.to_thread(lambda: list(query_status.stream()))

            if not docs_logs and not docs_active and not docs_status:
                return f"**Voice Activity Report (Last {days} Days)**\nNo voice activity recorded.", None

            # Normalize Data
            all_sessions = []
            
            def process_doc(doc, is_active=False):
                data = doc.to_dict()
                # Normalize timestamps
                joined_at = data.get('joined_at')
                if joined_at and joined_at.tzinfo:
                    joined_at = joined_at.replace(tzinfo=None)
                
                left_at = data.get('left_at')
                if is_active or not left_at:
                    left_at = datetime.utcnow()
                elif left_at.tzinfo:
                    left_at = left_at.replace(tzinfo=None)
                
                duration = (left_at - joined_at).total_seconds()
                
                return {
                    'user_name': data.get('user_name', 'Unknown'),
                    'user_id': data.get('user_id'),
                    'channel_name': data.get('channel_name', 'Unknown'),
                    'joined_at': joined_at,
                    'left_at': left_at,
                    'duration': duration,
                    'is_active': is_active
                }

            for d in docs_logs: all_sessions.append(process_doc(d, False))
            for d in docs_active: all_sessions.append(process_doc(d, True))

            # Group Sessions by Channel
            channels = {}
            for s in all_sessions:
                c = s['channel_name']
                if c not in channels: channels[c] = {'sessions': [], 'status_changes': []}
                channels[c]['sessions'].append(s)

            # Group Status Logs by Channel
            for d in docs_status:
                data = d.to_dict()
                c = data.get('channel_name', 'Unknown')
                ts = data.get('timestamp')
                if ts and ts.tzinfo: ts = ts.replace(tzinfo=None)
                
                if c not in channels: channels[c] = {'sessions': [], 'status_changes': []}
                
                channels[c]['status_changes'].append({
                    'status': data.get('status_text'),
                    'user': data.get('user_name', 'Unknown'),
                    'timestamp': ts
                })

            # Build Report
            report_lines = [f"**🎤 Voice Activity Report (Last {days} Days)**"]
            pair_overlaps = {} # (UserA, UserB) -> seconds
            
            for c_name, data in channels.items():
                sessions = data['sessions']
                status_changes = data['status_changes']
                
                sessions.sort(key=lambda x: x['joined_at'])
                status_changes.sort(key=lambda x: x['timestamp'])
                
                # Total Channel Duration (Sum of all user durations)
                total_seconds = sum(s['duration'] for s in sessions)
                hours, remainder = divmod(total_seconds, 3600)
                mins = int(remainder // 60)
                
                report_lines.append(f"\n**🔊 {c_name}** (Total User Time: {int(hours)}h {mins}m)")

                if not sessions and status_changes:
                    # Show status changes even if no one was in calls (e.g. text updates)
                    for sc in status_changes:
                        ts_local = self._to_local(sc['timestamp'])
                        ts_str = ts_local.strftime('%m/%d %I:%M %p')
                        report_lines.append(f"• 📝 Status set to **\"{sc['status']}\"** by {sc['user']} at {ts_str}")
                    continue

                # Group into "Calls"
                calls = []
                if not sessions: continue
                
                # Initialize first call
                current_call = {
                    'start': sessions[0]['joined_at'],
                    'end': sessions[0]['left_at'],
                    'participants': [sessions[0]]
                }
                
                for s in sessions[1:]:
                    if s['joined_at'] < (current_call['end'] + timedelta(minutes=15)):
                        current_call['end'] = max(current_call['end'], s['left_at'])
                        current_call['participants'].append(s)
                    else:
                        calls.append(current_call)
                        current_call = {
                            'start': s['joined_at'],
                            'end': s['left_at'],
                            'participants': [s]
                        }
                calls.append(current_call)

                # Track which status updates we've already displayed
                displayed_status_indices = set()

                # Format Calls
                for call in calls:
                    c_start = call['start']
                    c_end = call['end']
                    
                    # Social Matrix Calculation for this call
                    parts = call['participants']
                    for i in range(len(parts)):
                        for j in range(i + 1, len(parts)):
                            p1, p2 = parts[i], parts[j]
                            # Calculate overlap
                            overlap_start = max(p1['joined_at'], p2['joined_at'])
                            overlap_end = min(p1['left_at'], p2['left_at'])
                            if overlap_end > overlap_start:
                                duration = (overlap_end - overlap_start).total_seconds()
                                # Key sorted by name to avoid duplicates
                                key = tuple(sorted((p1['user_name'], p2['user_name'])))
                                pair_overlaps[key] = pair_overlaps.get(key, 0) + duration

                    # Topic Promotion
                    # Find status change closest to start (within 30 mins before or during)
                    call_title = f"Call"
                    promoted_topic = None
                    
                    for sc in status_changes:
                        # Check if status change happened between start-30m and end
                        if (c_start - timedelta(minutes=30)) <= sc['timestamp'] <= c_end:
                            # If it's before or early in the call, it's a good candidate for a title
                            if sc['timestamp'] < (c_start + timedelta(minutes=30)):
                                promoted_topic = sc['status']
                    
                    if promoted_topic:
                        call_title = f"Call: \"{promoted_topic}\""

                    # 1. Print any status updates that happened BEFORE this call (and weren't printed yet)
                    for i, sc in enumerate(status_changes):
                        if i not in displayed_status_indices and sc['timestamp'] < c_start:
                            ts_local = self._to_local(sc['timestamp'])
                            ts_str = ts_local.strftime('%m/%d %I:%M %p')
                            report_lines.append(f"• 📝 \"{sc['status']}\" set by {sc['user']} at {ts_str}")
                            displayed_status_indices.add(i)

                    c_duration = (c_end - c_start).total_seconds()
                    c_h, c_r = divmod(c_duration, 3600)
                    c_m = int(c_r // 60)
                    
                    # Localize for display
                    c_start_local = self._to_local(c_start)
                    c_end_local = self._to_local(c_end)

                    date_str = c_start_local.strftime('%m/%d')
                    start_str = c_start_local.strftime('%I:%M %p')
                    end_str = c_end_local.strftime('%I:%M %p')
                    
                    if c_start_local.date() != c_end_local.date():
                        end_str = c_end_local.strftime('%m/%d %I:%M %p')

                    active_tag = " (Ongoing)" if any(p['is_active'] for p in call['participants']) else ""
                    
                    report_lines.append(f"\n**📞 {call_title} on {date_str} at {start_str} - {end_str}** (~{int(c_h)}h {c_m}m){active_tag}")
                    
                    # Participants
                    for p in call['participants']:
                        p_start_local = self._to_local(p['joined_at'])
                        p_end_local = self._to_local(p['left_at'])
                        
                        p_start_str = p_start_local.strftime('%I:%M %p')
                        p_end_str = p_end_local.strftime('%I:%M %p')
                        
                        notes = []
                        if p['is_active']: notes.append("Active")
                        
                        join_diff = (p['joined_at'] - c_start).total_seconds()
                        if join_diff > 300: notes.append(f"Joined +{int(join_diff//60)}m")
                            
                        if not p['is_active']:
                            leave_diff = (c_end - p['left_at']).total_seconds()
                            if leave_diff > 300: notes.append(f"Left -{int(leave_diff//60)}m")
                        
                        note_str = f" _({', '.join(notes)})_" if notes else ""
                        report_lines.append(f"• `{p_start_str} - {p_end_str}` **{p['user_name']}**{note_str}")

                    # 2. Print status updates that happened DURING this call
                    relevant_statuses = []
                    for i, sc in enumerate(status_changes):
                        if i not in displayed_status_indices and c_start <= sc['timestamp'] <= c_end:
                            relevant_statuses.append(sc)
                            displayed_status_indices.add(i)
                    
                    if relevant_statuses:
                        report_lines.append("  *Status Updates:*")
                        for sc in relevant_statuses:
                            ts_local = self._to_local(sc['timestamp'])
                            ts_str = ts_local.strftime('%I:%M %p')
                            report_lines.append(f"  • 📝 \"{sc['status']}\" set by {sc['user']} at {ts_str}")

                # 3. Print any remaining status updates that happened AFTER the last call
                for i, sc in enumerate(status_changes):
                    if i not in displayed_status_indices:
                        ts_local = self._to_local(sc['timestamp'])
                        ts_str = ts_local.strftime('%m/%d %I:%M %p')
                        report_lines.append(f"• 📝 \"{sc['status']}\" set by {sc['user']} at {ts_str}")
                        displayed_status_indices.add(i)

            # Social Matrix Output
            if pair_overlaps:
                report_lines.append("\n**🔗 Top Interactions**")
                sorted_pairs = sorted(pair_overlaps.items(), key=lambda item: item[1], reverse=True)[:5]
                for (u1, u2), dur in sorted_pairs:
                    h, r = divmod(dur, 3600)
                    m = int(r // 60)
                    report_lines.append(f"• **{u1} & {u2}**: {int(h)}h {m}m")

            # Visual Timeline Generation
            timeline_file = await self._generate_timeline_image(all_sessions, start_date)
            
            # Network Graph Generation
            network_file = await self._generate_network_image(all_sessions, start_date)

            return "\n".join(report_lines), timeline_file, network_file

        except Exception as e:
            logger.error(f"Error generating voice report: {e}", exc_info=True)
            return f"Error generating report: {e}", None, None

    async def _generate_timeline_image(self, sessions, start_date):
        """Generates a Gantt-chart style timeline using matplotlib."""
        if not sessions: return None
        
        try:
            # Use Agg backend for headless environments
            import matplotlib
            matplotlib.use('Agg')
            
            # Setup Plot
            fig, ax = plt.subplots(figsize=(14, 8)) # Wider for legend
            
            # Calculate total duration per user for sorting
            user_durations = {}
            for s in sessions:
                u = s['user_name']
                user_durations[u] = user_durations.get(u, 0) + s['duration']
            
            # Sort users by duration descending (most active at top)
            # Note: In barh, y=0 is at bottom, so if we want top user at top, 
            # we assign them the highest index or reverse axis. 
            # Let's sort ascending by duration, so most active is at bottom (highest index), 
            # then we'll flip logic if needed. 
            # Wait, usually y=0 is bottom. So user at index 0 is at bottom.
            # We want most active at TOP. So most active should have highest index.
            users = sorted(user_durations.keys(), key=lambda u: user_durations[u])
            
            user_map = {name: i for i, name in enumerate(users)}
            
            channels = sorted(list(set(s['channel_name'] for s in sessions)))
            cmap = plt.get_cmap('tab10')
            channel_colors = {c: cmap(i % 10) for i, c in enumerate(channels)}
            
            # Plot Bars
            for s in sessions:
                y = user_map[s['user_name']]
                start_local = self._to_local(s['joined_at'])
                width = timedelta(seconds=s['duration'])
                ax.barh(y, width, left=start_local, height=0.4, color=channel_colors[s['channel_name']], edgecolor='black', linewidth=0.5)

            # --- Background Shading for Days ---
            # Get range of days from plot limits or input start_date
            # Since auto-formatting might not set limits yet, let's use the known data range
            if sessions:
                min_date = min(self._to_local(s['joined_at']) for s in sessions)
                max_date = max(self._to_local(s['left_at']) for s in sessions)
                
                # Align to start of day
                current_day = min_date.replace(hour=0, minute=0, second=0, microsecond=0)
                end_day = max_date.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                
                day_count = 0
                while current_day < end_day:
                    if day_count % 2 != 0: # Odd days
                        next_day = current_day + timedelta(days=1)
                        # Shade this day
                        ax.axvspan(current_day, next_day, facecolor='grey', alpha=0.1, zorder=0)
                    current_day += timedelta(days=1)
                    day_count += 1
            # -----------------------------------

            # Formatting
            ax.set_yticks(range(len(users)))
            ax.set_yticklabels(users)
            
            tz_label = self.timezone.zone
            ax.set_xlabel(f"Time ({tz_label})")
            # Ensure the axis labels use the bot's configured timezone
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %I:%M %p', tz=self.timezone))
            fig.autofmt_xdate()
            
            # Legend outside
            handles = [plt.Rectangle((0,0),1,1, color=channel_colors[c]) for c in channels]
            # Main Channel Legend
            legend1 = ax.legend(handles, channels, loc='upper left', bbox_to_anchor=(1.02, 1), title="Channels")
            ax.add_artist(legend1) # Add it manually so we can add another text/legend

            # --- Top Users Statistics ---
            # Sort users by duration descending for the stats box
            sorted_stats = sorted(user_durations.items(), key=lambda item: item[1], reverse=True)[:25]
            
            # Simple centering using padding might vary by font, but we can just use a clean header
            stats_text_lines = ["Top Voice Users"] 
            # Add a separator line
            stats_text_lines.append("-" * 20)
            
            for i, (u_name, u_dur) in enumerate(sorted_stats, 1):
                h, r = divmod(u_dur, 3600)
                m = int(r // 60)
                stats_text_lines.append(f"{i}. {u_name}: {int(h)}h {m}m")
            
            stats_text = "\n".join(stats_text_lines)
            
            # Place text box below the legend
            # Adjusted vertical position to 0.75 to start higher up, accommodating up to 25 users
            props = dict(boxstyle='round', facecolor='white', alpha=0.5)
            ax.text(1.02, 0.75, stats_text, transform=ax.transAxes, fontsize=9,
                    verticalalignment='top', bbox=props)
            # ----------------------------
            
            # Date Range for Title
            start_str = start_date.strftime("%b %d")
            end_str = datetime.utcnow().strftime("%b %d")
            if sessions:
                 min_d = min(self._to_local(s['joined_at']) for s in sessions)
                 max_d = max(self._to_local(s['left_at']) for s in sessions)
                 start_str = min_d.strftime("%b %d")
                 end_str = max_d.strftime("%b %d")

            plt.title(f"Voice Activity Timeline ({start_str} -> {end_str}) [{tz_label}]")
            
            # Save to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight') # bbox_inches='tight' helps include the external legend
            buf.seek(0)
            plt.close(fig)
            
            return discord.File(buf, filename="voice_timeline.png")
            
        except Exception as e:
            logger.error(f"Error generating timeline image: {e}", exc_info=True)
            return None

    async def _generate_network_image(self, sessions, start_date):
        """Generates a circular network graph of user interactions."""
        if not sessions: return None

        try:
            import matplotlib
            matplotlib.use('Agg')

            # 1. Calculate Overlaps (Reuse logic logic conceptually)
            pair_overlaps = {} # (UserA, UserB) -> seconds
            
            # Group by channel for overlap calculation
            channels = {}
            for s in sessions:
                c = s['channel_name']
                if c not in channels: channels[c] = []
                channels[c].append(s)

            for c_name, c_sessions in channels.items():
                # Sort by start time to optimize
                c_sessions.sort(key=lambda x: x['joined_at'])
                
                # Check every pair (O(N^2) per channel, but N is small per channel)
                for i in range(len(c_sessions)):
                    for j in range(i + 1, len(c_sessions)):
                        p1 = c_sessions[i]
                        p2 = c_sessions[j]
                        
                        # Calculate overlap
                        overlap_start = max(p1['joined_at'], p2['joined_at'])
                        overlap_end = min(p1['left_at'], p2['left_at'])
                        
                        if overlap_end > overlap_start:
                            duration = (overlap_end - overlap_start).total_seconds()
                            # Key sorted by name
                            key = tuple(sorted((p1['user_name'], p2['user_name'])))
                            pair_overlaps[key] = pair_overlaps.get(key, 0) + duration

            if not pair_overlaps:
                return None

            # 2. Setup Nodes (Users)
            users = sorted(list(set([u for pair in pair_overlaps.keys() for u in pair])))
            N = len(users)
            if N < 2: return None

            # Calculate individual user totals for sizing
            user_totals = {}
            for s in sessions:
                u = s['user_name']
                if u in users: # Only count users in the network
                    user_totals[u] = user_totals.get(u, 0) + s['duration']
            
            # Normalize sizes: Min 1000, Max 3000
            if user_totals:
                max_total = max(user_totals.values())
                min_total = min(user_totals.values())
                
                # Helper for sizing
                def get_size(duration):
                    if max_total == min_total: return 1200
                    # Linear interpolation
                    return 1000 + ((duration - min_total) / (max_total - min_total)) * 2000
                
                sizes = [get_size(user_totals.get(u, 0)) for u in users]
            else:
                sizes = [1000] * N

            # 3. Create Circular Layout
            fig, ax = plt.subplots(figsize=(10, 10))
            
            # Remove axes
            ax.axis('off')
            ax.set_aspect('equal')
            ax.set_xlim(-1.4, 1.4) # Slightly wider for labels
            ax.set_ylim(-1.4, 1.4)

            # Coordinates on unit circle
            angles = np.linspace(0, 2*np.pi, N, endpoint=False)
            # Rotate so first user is at top (pi/2)
            angles += np.pi / 2
            
            x_coords = np.cos(angles)
            y_coords = np.sin(angles)
            
            user_coords = {u: (x, y) for u, x, y in zip(users, x_coords, y_coords)}

            # 4. Draw Edges
            max_duration = max(pair_overlaps.values()) if pair_overlaps else 1
            
            # Store edge data for sorting
            edge_data = [] # (duration, x1, y1, x2, y2)

            for (u1, u2), duration in pair_overlaps.items():
                x1, y1 = user_coords[u1]
                x2, y2 = user_coords[u2]
                
                # Normalize width and alpha
                # Width: 1 to 10
                width = 1 + (duration / max_duration) * 8
                # Alpha: 0.3 to 1.0
                alpha = 0.3 + (duration / max_duration) * 0.7
                
                ax.plot([x1, x2], [y1, y2], color='skyblue', linewidth=width, alpha=alpha, zorder=1)
                
                edge_data.append({'duration': duration, 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2})

            # Label Top 10 Edges
            edge_data.sort(key=lambda x: x['duration'], reverse=True)
            for edge in edge_data[:10]:
                dur = edge['duration']
                x1, y1, x2, y2 = edge['x1'], edge['y1'], edge['x2'], edge['y2']
                
                # Midpoint
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                
                h, r = divmod(dur, 3600)
                m = int(r // 60)
                time_str = f"{int(h)}h {m}m"
                
                # Add text with a small background box to make it readable over lines
                ax.text(mx, my, time_str, fontsize=8, color='darkblue', ha='center', va='center',
                        bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1), zorder=2)

            # 5. Draw Nodes
            ax.scatter(x_coords, y_coords, s=sizes, color='navy', zorder=3)

            # 6. Labels
            for u, (x, y) in user_coords.items():
                # Format time string
                total_sec = user_totals.get(u, 0)
                h, r = divmod(total_sec, 3600)
                m = int(r // 60)
                time_str = f"{int(h)}h\n{m}m"

                # 1. Label Inside Node (Time)
                # Centered exactly on the node coordinates
                # White text for visibility on dark blue node
                # Adjust font size based on node size? 
                # Node size 's' is area in points^2. Radius ~ sqrt(s).
                # For now fixed size 8 should fit in most 300+ sized nodes.
                ax.text(x, y, time_str, fontsize=7, color='white', ha='center', va='center', fontweight='bold', zorder=4)

                # 2. Label Outside Node (Username)
                # Offset label slightly outward based on y position to avoid overlap with node
                offset_factor = 1.15
                label_x = x * offset_factor
                label_y = y * offset_factor
                
                # Determine alignment based on quadrant
                ha = 'center'
                va = 'center'
                if x > 0.1: ha = 'left'
                elif x < -0.1: ha = 'right'
                
                if y > 0.1: va = 'bottom'
                elif y < -0.1: va = 'top'

                ax.text(label_x, label_y, u, fontsize=9, ha=ha, va=va, fontweight='bold', zorder=3)

            # Date Range for Title
            start_str = start_date.strftime("%b %d")
            end_str = datetime.utcnow().strftime("%b %d")
            if sessions:
                 # Recalculate range from data for accuracy
                 # Note: _to_local might be needed if we want local dates, but strftime usually ok if consistent
                 # reusing self._to_local requires self access which is available
                 min_d = min(self._to_local(s['joined_at']) for s in sessions)
                 max_d = max(self._to_local(s['left_at']) for s in sessions)
                 start_str = min_d.strftime("%b %d")
                 end_str = max_d.strftime("%b %d")

            plt.title(f"Voice Interaction Network ({start_str} -> {end_str})", fontsize=14, pad=20)
            
            # Save
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            plt.close(fig)
            
            return discord.File(buf, filename="voice_network.png")

        except Exception as e:
            logger.error(f"Error generating network image: {e}", exc_info=True)
            return None

    async def cleanup_old_logs(self):
        """Cleans up logs older than 90 days."""
        cutoff = datetime.utcnow() - timedelta(days=90)
        logger.info(f"Cleaning voice logs older than {cutoff}...")
        
        query_logs = self.logs_ref.where(filter=FieldFilter('joined_at', '<', cutoff))
        query_status = self.status_logs_ref.where(filter=FieldFilter('timestamp', '<', cutoff))
        
        for q in [query_logs, query_status]:
            batch_size = 100
            while True:
                docs = await asyncio.to_thread(lambda: list(q.limit(batch_size).stream()))
                if not docs: break
                batch = self.db.batch()
                for doc in docs: batch.delete(doc.reference)
                await asyncio.to_thread(batch.commit)
