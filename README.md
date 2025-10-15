# Discord Employee Time Tracking Bot

A Discord bot that tracks employee work hours with manual check-in/check-out system, automatic idle time tracking, and 40-minute breaks.

## Features

- **Manual Check-In/Check-Out**: Employees check in when starting work and check out when done
- **Automatic Idle Tracking**: Tracks when employees go idle during their shift
- **40-Minute Breaks**: Automatic break timer that ends after 40 minutes
- **Work Statistics**: View detailed stats on hours worked, breaks taken, and active time
- **Live Status**: See who's currently working and their status
- **Persistent Storage**: SQLite database stores all shift history

## Commands

All commands use Discord's slash command system (`/`):

### For Employees

#### `/checkin`
Check in to start your work shift
- Use this when you start working
- You can only check in once at a time
- Your idle time will be automatically tracked

**Example**: `/checkin`

#### `/checkout`
Check out to end your work shift
- Use this when you're done working
- Shows summary of your shift (total time, active time, break time)
- Automatically ends any active breaks

**Example**: `/checkout`

#### `/break`
Start your 40-minute break
- Must be checked in first
- Break automatically ends after 40 minutes
- You'll get notified when break is over
- Only one break at a time

**Example**: `/break`

#### `/mystats [days]`
View your personal work statistics
- `days` (optional): Number of days to look back (default: 7)
- Shows shifts worked, total hours, active hours, break hours
- Shows current shift status if checked in

**Example**: 
- `/mystats` - Last 7 days
- `/mystats 30` - Last 30 days

### For Managers

#### `/whoisin`
See who is currently checked in
- Shows all employees currently working
- Displays their status (online/idle/on break)
- Shows shift duration for each employee
- Shows break time remaining if on break

**Example**: `/whoisin`

#### `/stats @user [days]`
View statistics for any employee
- `user` (required): The employee to check
- `days` (optional): Number of days to look back (default: 7)

**Example**: `/stats @john 14`

## How It Works

### Time Tracking System

1. **Check In**: When you use `/checkin`, your shift starts
2. **During Shift**: 
   - Bot automatically tracks if you're online or idle
   - Idle time is tracked separately
   - You can take a 40-minute break with `/break`
3. **Check Out**: Use `/checkout` to end your shift
   - View summary of total time, active time, and breaks
   - Data is saved to history

### Break System

- Breaks are exactly **40 minutes long**
- Timer starts when you use `/break`
- Break ends automatically after 40 minutes
- You'll get a notification when break is over
- Break time is subtracted from total shift time
- Only one break can be active at a time

### Idle Time Tracking

- Bot monitors your Discord status during shifts
- Tracks when you're:
  - 🟢 **Online** - Counted as active time
  - 🟡 **Idle** - Tracked separately (future feature)
  - 🔴 **DND** - Counted as active/online
- Only tracked while checked in (not on break)

### Statistics

View detailed breakdowns including:
- **Shifts Worked**: Number of times you checked in/out
- **Total Hours**: Complete shift duration
- **Active Hours**: Time spent active (not on break)
- **Break Hours**: Time spent on breaks
- **Daily Average**: Average hours per day

## Setup Instructions

### 1. Prerequisites
- Python 3.8 or higher
- A Discord account
- Administrator access to your Discord server

### 2. Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section and click "Add Bot"
4. Under "Privileged Gateway Intents", enable:
   - ✅ **Presence Intent** (required for idle tracking)
   - ✅ **Server Members Intent** (required)
5. Click "Reset Token" to get your bot token (save this for later)

### 3. Get Your Server ID

1. Enable Developer Mode in Discord (User Settings → Advanced → Developer Mode)
2. Right-click your server name and select "Copy ID"

### 4. Install the Bot

1. Download/clone this repository
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file:
   ```bash
   cp config_example.txt .env
   ```

4. Edit the `.env` file:
   ```
   DISCORD_TOKEN=your_bot_token_here
   GUILD_ID=your_server_id_here
   ```

### 5. Invite Bot to Your Server

Replace `YOUR_APP_ID` with your Application ID from the Developer Portal:

```
https://discord.com/api/oauth2/authorize?client_id=YOUR_APP_ID&permissions=68608&scope=bot%20applications.commands
```

**Important**: Make sure you enabled the Presence and Server Members intents BEFORE inviting the bot!

### 6. Run the Bot

```bash
python3 bot.py
```

You should see:
```
Idlee#0471 has connected to Discord!
Bot is in 1 server(s)
Database initialized!
✅ Commands synced to guild 123456789
🤖 Bot is ready!
```

## Usage Examples

### Starting Your Workday

```
You: /checkin
Bot: ✅ Checked In
     YourName has checked in!
     Time: 9:00 AM
```

### Taking a Break

```
You: /break
Bot: ☕ Break Started
     YourName is now on break!
     ⏰ Break Duration: 40 minutes
     ⏳ Break Ends At: 10:40 AM

[40 minutes later]
Bot: ✅ Break Ended
     @YourName, your break is over!
     Break Duration: 40 minutes
```

### Checking Out

```
You: /checkout
Bot: ✅ Checked Out
     YourName has checked out!
     📅 Shift Duration: 8.5 hours
     💼 Active Time: 7.83 hours
     ☕ Break Time: 0.67 hours
```

### Viewing Your Stats

```
You: /mystats 30
Bot: 📊 Work Statistics - YourName
     Last 30 days
     🗓️ Shifts Worked: 22 shifts
     ⏱️ Total Hours: 176.5 hours
     💼 Active Hours: 162.3 hours
     ☕ Break Hours: 14.2 hours
     📈 Daily Average: 5.88 hours/day
```

### Manager Checking Who's Working

```
Manager: /whoisin
Bot: 👥 Currently Checked In
     3 employee(s) are working
     
     John: 🟢 Online
     Shift: 3h 25m
     
     Sarah: ☕ On Break (15 min left)
     Shift: 2h 10m
     
     Mike: 🟡 Idle
     Shift: 1h 5m
```

## Data Storage

- All data stored in `presence_data.db` (SQLite database)
- Tables:
  - `active_shifts` - Current shifts in progress
  - `shift_history` - Completed shifts
  - `break_logs` - Break history
  - `status_logs` - Status change logs

## Troubleshooting

### Bot doesn't respond to commands
- Verify bot has proper permissions
- Check that commands are synced (see bot startup logs)
- Make sure bot is actually in your server

### Idle tracking not working
- Ensure "Presence Intent" is enabled in Developer Portal
- Bot must be able to see member status
- Only tracks during active shifts (after check-in)

### Break timer doesn't work
- Make sure bot stays running
- Break ends after exactly 40 minutes
- Check bot logs for errors

### Can't check in
- Make sure you've checked out from previous shift
- Only one shift per user at a time

## Privacy & Data

- Bot only tracks:
  - Check-in/check-out times
  - Discord online/idle status during shifts
  - Break times
- No message content is accessed
- All data stored locally
- Only works in specified server

## Support

For issues:
1. Check bot logs for errors
2. Verify all setup steps were completed
3. Ensure intents are properly enabled
4. Check bot permissions in server

## License

Open source - free for personal and commercial use.
