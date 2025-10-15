#!/usr/bin/env python3
"""
Setup script for Discord Idle Bot
Run this to check if everything is configured correctly
"""

import os
import sys
from dotenv import load_dotenv

def check_environment():
    """Check if all required environment variables are set"""
    load_dotenv()
    
    print("🔍 Checking environment configuration...")
    
    # Check Discord token
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ DISCORD_TOKEN not found!")
        print("   Please add DISCORD_TOKEN=your_bot_token to your .env file")
        return False
    else:
        print("✅ DISCORD_TOKEN found")
    
    # Check Guild ID (optional)
    guild_id = os.getenv('GUILD_ID')
    if guild_id:
        print(f"✅ GUILD_ID found: {guild_id}")
    else:
        print("⚠️  GUILD_ID not set (will use global commands)")
    
    return True

def check_dependencies():
    """Check if all required packages are installed"""
    print("\n📦 Checking dependencies...")
    
    required_packages = [
        'discord.py',
        'aiosqlite', 
        'python-dotenv'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} - not installed")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n📥 Install missing packages with:")
        print(f"pip install {' '.join(missing_packages)}")
        return False
    
    return True

def main():
    """Main setup function"""
    print("🤖 Discord Idle Bot Setup")
    print("=" * 30)
    
    # Check environment
    env_ok = check_environment()
    
    # Check dependencies
    deps_ok = check_dependencies()
    
    print("\n" + "=" * 30)
    
    if env_ok and deps_ok:
        print("🎉 Setup complete! You can now run: python3 bot.py")
        return 0
    else:
        print("❌ Setup incomplete. Please fix the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
