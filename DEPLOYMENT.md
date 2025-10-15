# 🚀 Discord Bot Deployment Guide

## Option 1: Railway (Recommended)

### Step 1: Create Railway Account
1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub
3. Click "New Project" → "Deploy from GitHub repo"

### Step 2: Prepare Your Repository
1. Push this code to a GitHub repository
2. Make sure all files are included:
   - `bot.py`
   - `database.py` 
   - `requirements.txt`
   - `railway.json`
   - `.env` (with your Discord token)

### Step 3: Deploy
1. Connect your GitHub repo to Railway
2. Railway will automatically detect it's a Python project
3. Add environment variables:
   - `DISCORD_TOKEN` = your bot token
   - `GUILD_ID` = your server ID (optional)
4. Deploy!

### Step 4: Keep Running
- Railway will keep your bot running 24/7
- Automatic restarts if it crashes
- Free tier: 500 hours/month (enough for 24/7)

---

## Option 2: Heroku

### Step 1: Create Heroku Account
1. Go to [heroku.com](https://heroku.com)
2. Sign up for free account

### Step 2: Install Heroku CLI
```bash
# macOS
brew install heroku/brew/heroku

# Or download from heroku.com
```

### Step 3: Deploy
```bash
# Login to Heroku
heroku login

# Create app
heroku create your-bot-name

# Set environment variables
heroku config:set DISCORD_TOKEN=your_token_here
heroku config:set GUILD_ID=your_guild_id

# Deploy
git add .
git commit -m "Deploy bot"
git push heroku main
```

---

## Option 3: Replit (Easiest)

### Step 1: Create Replit Account
1. Go to [replit.com](https://replit.com)
2. Sign up with GitHub

### Step 2: Import Project
1. Click "Create Repl" → "Import from GitHub"
2. Paste your repository URL
3. Click "Import"

### Step 3: Configure
1. Add environment variables in the "Secrets" tab:
   - `DISCORD_TOKEN`
   - `GUILD_ID`
2. Click "Run" button
3. Enable "Always On" in the settings

---

## Environment Variables Needed

Create a `.env` file or set these in your deployment platform:

```env
DISCORD_TOKEN=your_bot_token_here
GUILD_ID=your_server_id_here
```

## Important Notes

- ✅ Bot will run 24/7 online
- ✅ Automatic restarts if it crashes  
- ✅ No need to keep your computer on
- ✅ Database persists between restarts
- ✅ All features work the same

## Troubleshooting

If deployment fails:
1. Check environment variables are set correctly
2. Make sure Discord token is valid
3. Check logs in your deployment platform
4. Ensure all dependencies are in requirements.txt
