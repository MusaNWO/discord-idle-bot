import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
from dotenv import load_dotenv
from database import TimeTracker
import datetime
import asyncio
from zoneinfo import ZoneInfo

# Pakistan timezone
PKT = ZoneInfo("Asia/Karachi")

# Load environment variables
load_dotenv()

# Bot configuration
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID', 0))

# Schedule configuration
EXPECTED_CHECKIN_TIME = os.getenv('EXPECTED_CHECKIN_TIME', '09:00')
EXPECTED_CHECKOUT_TIME = os.getenv('EXPECTED_CHECKOUT_TIME', '18:00')

# Initialize bot with required intents
intents = discord.Intents.default()
intents.presences = True  # To track idle status
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)
tracker = TimeTracker()

# Store break timers and idle timers
break_timers = {}
idle_timers = {}
mobile_warnings_sent = {}  # Track mobile warnings to avoid spam
offline_warnings_sent = {}  # Track offline warnings to avoid spam

# Idle warning time (in seconds)
IDLE_WARNING_TIME = 300  # 5 minutes
WARNING_COOLDOWN = 1800  # 30 minutes cooldown between warnings

# Status mapping
TRACKED_STATUSES = {
    discord.Status.online: 'online',
    discord.Status.idle: 'idle',
    discord.Status.dnd: 'online',  # Treat DND as online/active
    discord.Status.offline: 'offline',
}

@bot.event
async def on_ready():
    """Called when bot is ready"""
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} server(s)')
    
    # Initialize database
    await tracker.initialize()
    print('Database initialized!')
    
    # Sync slash commands
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            # Clear existing commands first
            bot.tree.clear_commands(guild=guild)
            print("Cleared old commands...")
            # Copy and sync new commands
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"✅ Commands synced to guild {GUILD_ID}")
        else:
            await bot.tree.sync()
            print("✅ Commands synced globally")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")
    
    # Start background tasks (only if not already running)
    if not check_breaks.is_running():
        check_breaks.start()
    if not check_missing_checkins.is_running():
        check_missing_checkins.start()
    if not check_missing_checkouts.is_running():
        check_missing_checkouts.start()
    # Email report tasks removed for now
    # if not send_weekly_report.is_running():
    #     send_weekly_report.start()
    # if not send_monthly_report.is_running():
    #     send_monthly_report.start()
    
    print("🤖 Bot is ready!")

@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    """Track when a user goes idle/online during their shift"""
    if after.bot:
        return
    
    if GUILD_ID and after.guild.id != GUILD_ID:
        return
    
    # Only track if status changed or platform changed
    if before.status == after.status and before.mobile_status == after.mobile_status and before.desktop_status == after.desktop_status:
        return
    
    # Check if user has an active shift
    shift = await tracker.get_active_shift(after.id)
    if not shift or shift['on_break']:
        return  # Not checked in or on break
    
    # Handle offline status
    if after.status == discord.Status.offline:
        await send_offline_warning(after)
        await tracker.update_status(after.id, 'offline')
        return
    
    # Check if user is online only from mobile
    if after.mobile_status in [discord.Status.online, discord.Status.idle, discord.Status.dnd]:
        if after.desktop_status == discord.Status.offline and after.web_status == discord.Status.offline:
            await send_mobile_warning(after)
    
    # Update status
    new_status = TRACKED_STATUSES.get(after.status)
    if new_status:
        await tracker.update_status(after.id, new_status)
        
        # Handle idle warnings
        if new_status == 'idle':
            # User went idle, start warning timer
            await start_idle_warning(after)
        elif new_status == 'online':
            # User came back online, cancel any idle warning
            await cancel_idle_warning(after.id)

async def start_idle_warning(member: discord.Member):
    """Start idle warning timer for a user"""
    user_id = member.id
    
    # Cancel existing timer if any
    if user_id in idle_timers:
        idle_timers[user_id].cancel()
    
    async def send_idle_warning():
        await asyncio.sleep(IDLE_WARNING_TIME)
        
        # Check if user is still idle and checked in
        shift = await tracker.get_active_shift(user_id)
        if shift and shift['status'] == 'idle' and not shift['on_break']:
            try:
                # Try to send DM
                embed = discord.Embed(
                    title="⚠️ Idle Warning",
                    description=f"Hey {member.display_name}! You've been idle for {IDLE_WARNING_TIME // 60} minute(s).",
                    color=discord.Color.orange(),
                    timestamp=datetime.datetime.now(PKT)
                )
                embed.add_field(
                    name="Please return to work",
                    value="If you're still working, please move your mouse or interact with Discord to show you're active.",
                    inline=False
                )
                embed.set_footer(text="Automated idle reminder")
                
                await member.send(embed=embed)
                print(f"Sent idle warning to {member.display_name}")
                
                # Notify server owner
                await notify_server_owner(member.guild, f"🟡 {member.display_name} has been idle for 5+ minutes")
                
            except discord.Forbidden:
                print(f"Cannot send DM to {member.display_name} (DMs disabled)")
            except Exception as e:
                print(f"Error sending idle warning: {e}")
        
        # Remove timer from dict
        if user_id in idle_timers:
            del idle_timers[user_id]
    
    # Create and store the task
    task = asyncio.create_task(send_idle_warning())
    idle_timers[user_id] = task

async def cancel_idle_warning(user_id: int):
    """Cancel idle warning timer for a user"""
    if user_id in idle_timers:
        idle_timers[user_id].cancel()
        del idle_timers[user_id]
        print(f"Cancelled idle warning for user {user_id}")

async def send_offline_warning(member: discord.Member):
    """Send warning when user goes offline during shift"""
    # Check if we recently sent a warning (anti-spam)
    now = datetime.datetime.now(PKT)
    if member.id in offline_warnings_sent:
        last_warning = offline_warnings_sent[member.id]
        if (now - last_warning).total_seconds() < WARNING_COOLDOWN:
            return  # Don't spam warnings
    
    try:
        embed = discord.Embed(
            title="🔴 Offline Alert",
            description=f"Hey {member.display_name}! You've gone offline during your shift.",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(PKT)
        )
        embed.add_field(
            name="⚠️ Important",
            value="You're still checked in but showing as offline. Please come back online or use `/checkout` if you're done working.",
            inline=False
        )
        embed.set_footer(text="Automated offline alert")
        
        await member.send(embed=embed)
        offline_warnings_sent[member.id] = now
        print(f"Sent offline warning to {member.display_name}")
        
        # Notify server owner
        await notify_server_owner(member.guild, f"🔴 {member.display_name} went offline during shift")
        
    except discord.Forbidden:
        print(f"Cannot send DM to {member.display_name} (DMs disabled)")
    except Exception as e:
        print(f"Error sending offline warning: {e}")

async def send_mobile_warning(member: discord.Member):
    """Send warning when user is online only from mobile"""
    # Check if we recently sent a warning (anti-spam)
    now = datetime.datetime.now(PKT)
    if member.id in mobile_warnings_sent:
        last_warning = mobile_warnings_sent[member.id]
        if (now - last_warning).total_seconds() < WARNING_COOLDOWN:
            return  # Don't spam warnings
    
    try:
        embed = discord.Embed(
            title="📱 Mobile Alert",
            description=f"Hey {member.display_name}! You're currently online from your phone.",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(PKT)
        )
        embed.add_field(
            name="💻 Please Switch to Desktop",
            value="For better productivity, please log in from your laptop/computer instead of your phone.",
            inline=False
        )
        embed.set_footer(text="Automated mobile detection")
        
        await member.send(embed=embed)
        mobile_warnings_sent[member.id] = now
        print(f"Sent mobile warning to {member.display_name}")
        
        # Notify server owner
        await notify_server_owner(member.guild, f"📱 {member.display_name} is working from mobile only")
        
    except discord.Forbidden:
        print(f"Cannot send DM to {member.display_name} (DMs disabled)")
    except Exception as e:
        print(f"Error sending mobile warning: {e}")

async def notify_server_owner(guild: discord.Guild, message: str):
    """Send notification to server owner about warnings"""
    try:
        if guild.owner:
            embed = discord.Embed(
                title="🔔 Employee Alert",
                description=message,
                color=discord.Color.blue(),
                timestamp=datetime.datetime.now(PKT)
            )
            embed.set_footer(text="Automated notification from Idle Bot")
            
            await guild.owner.send(embed=embed)
            print(f"Notified server owner about: {message}")
    except Exception as e:
        print(f"Error notifying server owner: {e}")

@bot.tree.command(name="checkin", description="Check in to start your work shift")
async def checkin(interaction: discord.Interaction):
    """Check in command"""
    # Defer response to prevent timeout
    await interaction.response.defer()
    
    user = interaction.user
    
    try:
        success = await tracker.check_in(user.id, str(user))
        
        if success:
            embed = discord.Embed(
                title="✅ Checked In",
                description=f"**{user.display_name}** has checked in!",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now(PKT)
            )
            embed.add_field(name="Time", value=f"<t:{int(datetime.datetime.now(PKT).timestamp())}:F>")
            embed.set_footer(text="Your shift has started. Use /checkout when done.")
            await interaction.followup.send(embed=embed)
        else:
            embed = discord.Embed(
                title="⚠️ Already Checked In",
                description="You're already checked in! Use `/checkout` to end your shift first.",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"Error in checkin command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="An error occurred while checking in. Please try again.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="checkout", description="Check out to end your work shift")
async def checkout(interaction: discord.Interaction):
    """Check out command"""
    # Defer response to prevent timeout
    await interaction.response.defer()
    
    user = interaction.user
    
    try:
        result = await tracker.check_out(user.id)
        
        if result:
            total_hours = result['total_minutes'] / 60
            active_hours = result['active_minutes'] / 60
            idle_hours = result.get('idle_minutes', 0) / 60
            offline_hours = result.get('offline_minutes', 0) / 60
            break_hours = result['break_minutes'] / 60
            
            embed = discord.Embed(
                title="✅ Checked Out",
                description=f"**{user.display_name}** has checked out!",
                color=discord.Color.blue(),
                timestamp=datetime.datetime.now(PKT)
            )
            embed.add_field(
                name="📅 Shift Duration",
                value=f"{total_hours:.2f} hours",
                inline=True
            )
            embed.add_field(
                name="💼 Active Time",
                value=f"{active_hours:.2f} hours",
                inline=True
            )
            embed.add_field(
                name="🟡 Idle Time",
                value=f"{idle_hours:.2f} hours",
                inline=True
            )
            embed.add_field(
                name="🔴 Offline Time",
                value=f"{offline_hours:.2f} hours",
                inline=True
            )
            embed.add_field(
                name="☕ Break Time",
                value=f"{break_hours:.2f} hours",
                inline=True
            )
            embed.add_field(
                name="Check In",
                value=f"<t:{int(result['check_in'].timestamp())}:t>",
                inline=True
            )
            embed.add_field(
                name="Check Out",
                value=f"<t:{int(result['check_out'].timestamp())}:t>",
                inline=True
            )
            
            # Cancel any active break timer
            if user.id in break_timers:
                break_timers[user.id].cancel()
                del break_timers[user.id]
            
            # Cancel any active idle warning
            await cancel_idle_warning(user.id)
            
            # Clear warning trackers
            if user.id in mobile_warnings_sent:
                del mobile_warnings_sent[user.id]
            if user.id in offline_warnings_sent:
                del offline_warnings_sent[user.id]
            
            await interaction.followup.send(embed=embed)
        else:
            embed = discord.Embed(
                title="⚠️ Not Checked In",
                description="You're not checked in! Use `/checkin` to start your shift first.",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"Error in checkout command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="An error occurred while checking out. Please try again.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="break", description="Start your 40-minute break")
async def take_break(interaction: discord.Interaction):
    """Start break command"""
    # Defer response to prevent timeout
    await interaction.response.defer()
    
    user = interaction.user
    
    try:
        break_end = await tracker.start_break(user.id)
        
        if break_end:
            embed = discord.Embed(
                title="☕ Break Started",
                description=f"**{user.display_name}** is now on break!",
                color=discord.Color.gold(),
                timestamp=datetime.datetime.now(PKT)
            )
            embed.add_field(
                name="⏰ Break Duration",
                value="40 minutes",
                inline=True
            )
            embed.add_field(
                name="⏳ Break Ends At",
                value=f"<t:{int(break_end.timestamp())}:t>",
                inline=True
            )
            embed.set_footer(text="Your break will end automatically in 40 minutes")
            
            # Cancel any idle warning (user is on break now)
            await cancel_idle_warning(user.id)
            
            await interaction.followup.send(embed=embed)
            
            # Schedule break end
            async def end_break_task():
                await asyncio.sleep(40 * 60)  # 40 minutes
                duration = await tracker.end_break(user.id, str(user))
                if duration:
                    try:
                        # Notify user that break ended
                        end_embed = discord.Embed(
                            title="✅ Break Ended",
                            description=f"**{user.display_name}**, your break is over!",
                            color=discord.Color.green()
                        )
                        end_embed.add_field(name="Break Duration", value=f"{duration} minutes")
                        await interaction.channel.send(content=user.mention, embed=end_embed)
                    except:
                        pass
                
                if user.id in break_timers:
                    del break_timers[user.id]
            
            # Store and start the task
            task = asyncio.create_task(end_break_task())
            break_timers[user.id] = task
            
        else:
            # Check if already on break
            shift = await tracker.get_active_shift(user.id)
            if shift and shift['on_break']:
                embed = discord.Embed(
                    title="⚠️ Already on Break",
                    description="You're already on break!",
                    color=discord.Color.orange()
                )
            else:
                embed = discord.Embed(
                    title="⚠️ Not Checked In",
                    description="You must check in first before taking a break!",
                    color=discord.Color.orange()
                )
            await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"Error in break command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="An error occurred while starting your break. Please try again.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="mystats", description="View your work statistics day by day")
@app_commands.describe(days="Number of days to look back (default: 7)")
async def mystats(interaction: discord.Interaction, days: int = 7):
    """View personal statistics"""
    # Defer response to prevent timeout
    await interaction.response.defer()
    
    user = interaction.user
    
    try:
        # Get overall stats
        stats = await tracker.get_user_stats(user.id, days)
        # Get day-by-day breakdown
        daily_stats = await tracker.get_daily_stats(user.id, days)
        
        embed = discord.Embed(
            title=f"📊 Work Statistics - {user.display_name}",
            description=f"Last {days} days - Day by Day Breakdown",
            color=discord.Color.purple(),
            timestamp=datetime.datetime.now(PKT)
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        # Summary at top
        productivity = (stats['active_hours'] / stats['total_hours'] * 100) if stats['total_hours'] > 0 else 0
        embed.add_field(
            name="📈 Summary",
            value=f"**Total:** {stats['total_hours']:.1f}h | **Active:** {stats['active_hours']:.1f}h | **Idle:** {stats['idle_hours']:.1f}h | **Offline:** {stats['offline_hours']:.1f}h | **Breaks:** {stats['break_hours']:.1f}h\n**Productivity:** {productivity:.1f}%",
            inline=False
        )
        
        # Day-by-day breakdown
        if daily_stats:
            for day_data in daily_stats:
                date_obj = datetime.datetime.strptime(day_data['date'], '%Y-%m-%d')
                day_name = date_obj.strftime('%A, %b %d')  # e.g., "Monday, Oct 14"
                
                total_h = day_data['total_hours']
                active_h = day_data['active_hours']
                idle_h = day_data.get('idle_hours', 0)
                offline_h = day_data.get('offline_hours', 0)
                break_h = day_data['break_hours']
                shifts = day_data['shifts']
                
                value = f"⏱️ **{total_h:.2f}h** total\n"
                value += f"💼 {active_h:.2f}h active | 🟡 {idle_h:.2f}h idle | 🔴 {offline_h:.2f}h offline\n"
                value += f"☕ {break_h:.2f}h break | 📊 {shifts} shift(s)"
                
                embed.add_field(
                    name=f"📅 {day_name}",
                    value=value,
                    inline=False
                )
        else:
            embed.add_field(
                name="No Data",
                value="No shifts recorded in this period",
                inline=False
            )
        
        # Check current shift status
        current_shift = await tracker.get_active_shift(user.id)
        if current_shift:
            duration = current_shift['duration']
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            
            status_text = "☕ On Break" if current_shift['on_break'] else f"🟢 Active ({current_shift['status']})"
            
            embed.add_field(
                name="🔄 Current Shift (Ongoing)",
                value=f"{status_text} - {hours}h {minutes}m",
                inline=False
            )
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print(f"Error in mystats command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="An error occurred while fetching your statistics.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="whoisin", description="See who is currently checked in")
async def whoisin(interaction: discord.Interaction):
    """See all active shifts"""
    # Defer response to prevent timeout
    await interaction.response.defer()
    
    try:
        shifts = await tracker.get_all_active_shifts()
        
        if not shifts:
            embed = discord.Embed(
                title="👥 No One Checked In",
                description="No employees are currently checked in.",
                color=discord.Color.light_gray()
            )
            await interaction.followup.send(embed=embed)
            return
        
        embed = discord.Embed(
            title="👥 Currently Checked In",
            description=f"{len(shifts)} employee(s) are working",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(PKT)
        )
        
        for shift in shifts:
            duration = shift['duration']
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            
            if shift['on_break']:
                status = "☕ On Break"
                if shift['break_start']:
                    break_duration = datetime.datetime.utcnow() - shift['break_start']
                    break_mins = int(break_duration.total_seconds() // 60)
                    remaining = 40 - break_mins
                    status += f" ({remaining} min left)"
            else:
                status_emoji = "🟢" if shift['status'] == 'online' else "🟡"
                status = f"{status_emoji} {shift['status'].title()}"
            
            embed.add_field(
                name=f"{shift['username']}",
                value=f"{status}\nShift: {hours}h {minutes}m",
                inline=True
            )
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print(f"Error in whoisin command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="An error occurred while fetching active shifts.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="stats", description="View day-by-day statistics for any employee")
@app_commands.describe(
    user="The employee to check",
    days="Number of days to look back (default: 7)"
)
async def stats(interaction: discord.Interaction, user: discord.Member, days: int = 7):
    """View statistics for another user (for managers)"""
    # Defer response to prevent timeout
    await interaction.response.defer()
    
    try:
        # Get overall stats
        overall_stats = await tracker.get_user_stats(user.id, days)
        # Get day-by-day breakdown
        daily_stats = await tracker.get_daily_stats(user.id, days)
        
        embed = discord.Embed(
            title=f"📊 Work Statistics - {user.display_name}",
            description=f"Last {days} days - Day by Day Breakdown",
            color=discord.Color.purple(),
            timestamp=datetime.datetime.now(PKT)
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        # Summary at top
        productivity = (overall_stats['active_hours'] / overall_stats['total_hours'] * 100) if overall_stats['total_hours'] > 0 else 0
        embed.add_field(
            name="📈 Summary",
            value=f"**Total:** {overall_stats['total_hours']:.1f}h | **Active:** {overall_stats['active_hours']:.1f}h | **Idle:** {overall_stats['idle_hours']:.1f}h | **Offline:** {overall_stats['offline_hours']:.1f}h | **Breaks:** {overall_stats['break_hours']:.1f}h\n**Productivity:** {productivity:.1f}%",
            inline=False
        )
        
        # Day-by-day breakdown
        if daily_stats:
            for day_data in daily_stats:
                date_obj = datetime.datetime.strptime(day_data['date'], '%Y-%m-%d')
                day_name = date_obj.strftime('%A, %b %d')  # e.g., "Monday, Oct 14"
                
                total_h = day_data['total_hours']
                active_h = day_data['active_hours']
                idle_h = day_data.get('idle_hours', 0)
                offline_h = day_data.get('offline_hours', 0)
                break_h = day_data['break_hours']
                shifts = day_data['shifts']
                
                value = f"⏱️ **{total_h:.2f}h** total\n"
                value += f"💼 {active_h:.2f}h active | 🟡 {idle_h:.2f}h idle | 🔴 {offline_h:.2f}h offline\n"
                value += f"☕ {break_h:.2f}h break | 📊 {shifts} shift(s)"
                
                embed.add_field(
                    name=f"📅 {day_name}",
                    value=value,
                    inline=False
                )
        else:
            embed.add_field(
                name="No Data",
                value="No shifts recorded in this period",
                inline=False
            )
        
        # Current shift if any
        current_shift = await tracker.get_active_shift(user.id)
        if current_shift:
            duration = current_shift['duration']
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            
            status_text = "☕ On Break" if current_shift['on_break'] else f"🟢 Active"
            
            embed.add_field(
                name="🔄 Current Shift (Ongoing)",
                value=f"{status_text} - {hours}h {minutes}m",
                inline=False
            )
        
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print(f"Error in stats command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="An error occurred while fetching statistics.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="summary", description="Get today's summary for all employees")
async def daily_summary(interaction: discord.Interaction):
    """Get daily summary of all employees"""
    await interaction.response.defer()
    
    try:
        today = datetime.datetime.now(PKT).date()
        shifts = await tracker.get_all_active_shifts()
        
        # Get today's completed shifts - use weekly report data for today only
        today = datetime.datetime.now(PKT).date()
        data = await tracker.get_weekly_report_data(today, today)
        completed_shifts = data.get('employees', [])
        
        embed = discord.Embed(
            title=f"📊 Daily Summary - {today.strftime('%B %d, %Y')}",
            description=f"**Active Shifts:** {len(shifts)} | **Completed Today:** {len(completed_shifts)}",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(PKT)
        )
        
        # Show active employees
        if shifts:
            active_list = []
            for shift in shifts[:10]:  # Limit to 10
                hours = int(shift['duration'].total_seconds() // 3600)
                minutes = int((shift['duration'].total_seconds() % 3600) // 60)
                status_emoji = "🟢" if shift['status'] == 'online' else "🟡" if shift['status'] == 'idle' else "🔴"
                active_list.append(f"{status_emoji} {shift['username']} - {hours}h {minutes}m")
            embed.add_field(
                name="🟢 Currently Working",
                value="\n".join(active_list) if active_list else "None",
                inline=False
            )
        
        # Show top performers today
        if completed_shifts:
            top_performers = sorted(completed_shifts, key=lambda x: x['active_hours'], reverse=True)[:5]
            top_list = []
            for emp in top_performers:
                top_list.append(f"💼 {emp['username']} - {emp['active_hours']:.1f}h active")
            embed.add_field(
                name="⭐ Top Performers Today",
                value="\n".join(top_list),
                inline=False
            )
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print(f"Error in summary command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="An error occurred while generating summary.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="leaderboard", description="View productivity leaderboard")
@app_commands.describe(days="Number of days to look back (default: 7)")
async def leaderboard(interaction: discord.Interaction, days: int = 7):
    """View productivity leaderboard"""
    await interaction.response.defer()
    
    try:
        end_date = datetime.datetime.now(PKT).date()
        start_date = end_date - datetime.timedelta(days=days-1)
        
        data = await tracker.get_weekly_report_data(start_date, end_date)
        
        if not data['employees']:
            embed = discord.Embed(
                title="📊 Leaderboard",
                description="No data available for this period.",
                color=discord.Color.gray()
            )
            await interaction.followup.send(embed=embed)
            return
        
        # Sort by productivity score
        sorted_employees = sorted(data['employees'], key=lambda x: x['productivity_score'], reverse=True)
        
        embed = discord.Embed(
            title=f"🏆 Productivity Leaderboard",
            description=f"Last {days} days ({start_date} to {end_date})",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(PKT)
        )
        
        # Top 10
        leaderboard_text = ""
        medals = ["🥇", "🥈", "🥉"]
        for i, emp in enumerate(sorted_employees[:10]):
            medal = medals[i] if i < 3 else f"{i+1}."
            score_emoji = "🟢" if emp['productivity_score'] >= 80 else "🟡" if emp['productivity_score'] >= 60 else "🔴"
            leaderboard_text += f"{medal} {emp['username']} - {score_emoji} {emp['productivity_score']:.1f}% ({emp['active_hours']:.1f}h active)\n"
        
        embed.add_field(
            name="Top Performers",
            value=leaderboard_text,
            inline=False
        )
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print(f"Error in leaderboard command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="An error occurred while generating leaderboard.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="productivity", description="View your productivity score")
@app_commands.describe(days="Number of days to calculate (default: 7)")
async def productivity(interaction: discord.Interaction, days: int = 7):
    """View personal productivity score"""
    await interaction.response.defer()
    
    user = interaction.user
    
    try:
        stats = await tracker.get_user_stats(user.id, days)
        
        if stats['total_hours'] == 0:
            embed = discord.Embed(
                title="📊 Productivity Score",
                description="No work data available for this period.",
                color=discord.Color.gray()
            )
            await interaction.followup.send(embed=embed)
            return
        
        productivity_score = (stats['active_hours'] / stats['total_hours'] * 100) if stats['total_hours'] > 0 else 0
        
        # Determine grade
        if productivity_score >= 90:
            grade = "🌟 Excellent"
            color = discord.Color.green()
        elif productivity_score >= 80:
            grade = "✅ Great"
            color = discord.Color.green()
        elif productivity_score >= 70:
            grade = "👍 Good"
            color = discord.Color.blue()
        elif productivity_score >= 60:
            grade = "⚠️ Fair"
            color = discord.Color.orange()
        else:
            grade = "❌ Needs Improvement"
            color = discord.Color.red()
        
        embed = discord.Embed(
            title=f"📊 Productivity Score - {user.display_name}",
            description=f"**Score: {productivity_score:.1f}%** - {grade}",
            color=color,
            timestamp=datetime.datetime.now(PKT)
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        embed.add_field(
            name="📈 Breakdown (Last {days} days)",
            value=f"**Total Hours:** {stats['total_hours']:.1f}h\n"
                  f"**Active:** {stats['active_hours']:.1f}h ({stats['active_hours']/stats['total_hours']*100:.1f}%)\n"
                  f"**Idle:** {stats['idle_hours']:.1f}h ({stats['idle_hours']/stats['total_hours']*100:.1f}%)\n"
                  f"**Offline:** {stats['offline_hours']:.1f}h ({stats['offline_hours']/stats['total_hours']*100:.1f}%)\n"
                  f"**Breaks:** {stats['break_hours']:.1f}h",
            inline=False
        )
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print(f"Error in productivity command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="An error occurred while calculating productivity.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

# Email functionality removed - will be added back later for testing
# async def send_email_report(recipient: str, subject: str, html_content: str):
#     """Send email report"""
#     pass

# # Email report generation functions removed - will be added back later
# def generate_monthly_report_html(data: dict) -> str:

@tasks.loop(time=datetime.time(hour=9, minute=0, tzinfo=PKT))
async def check_missing_checkins():
    """Check for employees who haven't checked in by expected time"""
    try:
        missing = await tracker.get_missing_checkins(EXPECTED_CHECKIN_TIME)
        if missing:
            guild = bot.get_guild(GUILD_ID)
            if guild and guild.owner:
                message = "🔔 **Missing Check-Ins Alert**\n\n"
                for emp in missing:
                    message += f"❌ {emp['username']} - Expected check-in: {emp['expected_time']}\n"
                
                embed = discord.Embed(
                    title="⚠️ Missing Check-Ins",
                    description=message,
                    color=discord.Color.orange(),
                    timestamp=datetime.datetime.now(PKT)
                )
                await guild.owner.send(embed=embed)
                print(f"Alerted about {len(missing)} missing check-ins")
    except Exception as e:
        print(f"Error checking missing check-ins: {e}")

@tasks.loop(time=datetime.time(hour=18, minute=0, tzinfo=PKT))
async def check_missing_checkouts():
    """Check for employees who forgot to check out"""
    try:
        missing = await tracker.get_missing_checkouts()
        if missing:
            guild = bot.get_guild(GUILD_ID)
            if guild and guild.owner:
                message = "🔔 **Missing Check-Outs Alert**\n\n"
                for emp in missing:
                    message += f"❌ {emp['username']} - Checked in {emp['hours_ago']:.1f} hours ago\n"
                
                embed = discord.Embed(
                    title="⚠️ Missing Check-Outs",
                    description=message,
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now(PKT)
                )
                await guild.owner.send(embed=embed)
                print(f"Alerted about {len(missing)} missing check-outs")
    except Exception as e:
        print(f"Error checking missing check-outs: {e}")

# Email report tasks removed - will be added back later for testing
# @tasks.loop(time=datetime.time(hour=8, minute=0, tzinfo=PKT))
# async def send_weekly_report():
#     """Send weekly report every Monday"""
#     pass

# @tasks.loop(time=datetime.time(hour=8, minute=0, tzinfo=PKT))
# async def send_monthly_report():
#     """Send monthly report on the 1st of each month"""
#     pass

@tasks.loop(minutes=1)
async def check_breaks():
    """Background task to monitor break status"""
    # This is a backup check in case timers fail
    pass

# Run the bot
if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found in environment variables")
        print("Please set DISCORD_TOKEN in your deployment platform")
        exit(1)
    
    print("🚀 Starting Discord Bot...")
    print(f"Bot User: {bot.user if bot.user else 'Not logged in yet'}")
    print(f"Guild ID: {GUILD_ID if GUILD_ID else 'Global commands'}")
    
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("❌ Invalid Discord token! Please check your DISCORD_TOKEN")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        exit(1)
