import aiosqlite
import datetime
from typing import Optional, List, Dict
from zoneinfo import ZoneInfo

# Pakistan timezone
PKT = ZoneInfo("Asia/Karachi")
UTC = ZoneInfo("UTC")

class TimeTracker:
    """Database handler for tracking employee work shifts, breaks, and idle time"""
    
    def __init__(self, db_path: str = "presence_data.db"):
        self.db_path = db_path
    
    async def initialize(self):
        """Initialize the database with required tables"""
        async with aiosqlite.connect(self.db_path) as db:
            # Table for active shifts (who's currently checked in)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS active_shifts (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    check_in_time TIMESTAMP,
                    current_status TEXT,
                    status_start_time TIMESTAMP,
                    on_break INTEGER DEFAULT 0,
                    break_start_time TIMESTAMP
                )
            """)
            
            # Table for completed shifts
            await db.execute("""
                CREATE TABLE IF NOT EXISTS shift_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    check_in_time TIMESTAMP,
                    check_out_time TIMESTAMP,
                    total_minutes INTEGER,
                    idle_minutes INTEGER,
                    break_minutes INTEGER,
                    active_minutes INTEGER
                )
            """)
            
            # Table for tracking status changes during shift
            await db.execute("""
                CREATE TABLE IF NOT EXISTS status_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    shift_id INTEGER,
                    status TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    duration_minutes INTEGER
                )
            """)
            
            # Table for break history
            await db.execute("""
                CREATE TABLE IF NOT EXISTS break_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    shift_id INTEGER,
                    break_start TIMESTAMP,
                    break_end TIMESTAMP,
                    duration_minutes INTEGER
                )
            """)
            
            await db.commit()
    
    async def check_in(self, user_id: int, username: str) -> bool:
        """Check in a user for their shift"""
        now = datetime.datetime.now(PKT)
        async with aiosqlite.connect(self.db_path) as db:
            # Check if already checked in
            async with db.execute(
                "SELECT user_id FROM active_shifts WHERE user_id = ?", (user_id,)
            ) as cursor:
                if await cursor.fetchone():
                    return False  # Already checked in
            
            # Create new shift
            await db.execute("""
                INSERT INTO active_shifts (user_id, username, check_in_time, current_status, status_start_time, on_break)
                VALUES (?, ?, ?, 'online', ?, 0)
            """, (user_id, username, now, now))
            await db.commit()
            return True
    
    async def check_out(self, user_id: int) -> Optional[Dict]:
        """Check out a user and return shift summary"""
        now = datetime.datetime.now(PKT)
        async with aiosqlite.connect(self.db_path) as db:
            # Get active shift
            async with db.execute("""
                SELECT username, check_in_time, current_status, status_start_time, on_break, break_start_time
                FROM active_shifts WHERE user_id = ?
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                
                if not row:
                    return None  # Not checked in
                
                username, check_in, current_status, status_start, on_break, break_start = row
                check_in_dt = datetime.datetime.fromisoformat(check_in)
                status_start_dt = datetime.datetime.fromisoformat(status_start)
                
                # Calculate total shift time
                total_minutes = int((now - check_in_dt).total_seconds() / 60)
                
                # Get idle and break time from previous status changes
                idle_minutes = 0
                break_minutes = 0
                
                # Calculate any ongoing break
                if on_break and break_start:
                    break_start_dt = datetime.datetime.fromisoformat(break_start)
                    break_duration = int((now - break_start_dt).total_seconds() / 60)
                    break_minutes += min(break_duration, 40)  # Cap at 40 minutes
                
                # Get historical break time for this shift
                async with db.execute("""
                    SELECT COALESCE(SUM(duration_minutes), 0) FROM break_logs
                    WHERE user_id = ? AND break_start >= ?
                """, (user_id, check_in)) as cursor2:
                    result = await cursor2.fetchone()
                    if result:
                        break_minutes += result[0]
                
                # Calculate idle time (we'll track this separately)
                # For now, active = total - break
                active_minutes = total_minutes - break_minutes
                
                # Save shift to history
                await db.execute("""
                    INSERT INTO shift_history (user_id, username, check_in_time, check_out_time, 
                                              total_minutes, idle_minutes, break_minutes, active_minutes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, username, check_in, now, total_minutes, idle_minutes, break_minutes, active_minutes))
                
                # Remove from active shifts
                await db.execute("DELETE FROM active_shifts WHERE user_id = ?", (user_id,))
                await db.commit()
                
                return {
                    "username": username,
                    "check_in": check_in_dt,
                    "check_out": now,
                    "total_minutes": total_minutes,
                    "active_minutes": active_minutes,
                    "idle_minutes": idle_minutes,
                    "break_minutes": break_minutes
                }
    
    async def start_break(self, user_id: int) -> Optional[datetime.datetime]:
        """Start a break for a user"""
        now = datetime.datetime.now(PKT)
        async with aiosqlite.connect(self.db_path) as db:
            # Check if user is checked in
            async with db.execute(
                "SELECT on_break FROM active_shifts WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None  # Not checked in
                if row[0] == 1:
                    return None  # Already on break
            
            # Start break
            await db.execute("""
                UPDATE active_shifts 
                SET on_break = 1, break_start_time = ?
                WHERE user_id = ?
            """, (now, user_id))
            await db.commit()
            
            # Return when break ends (40 minutes from now)
            return now + datetime.timedelta(minutes=40)
    
    async def end_break(self, user_id: int, username: str) -> Optional[int]:
        """End a break for a user (called automatically after 40 min)"""
        now = datetime.datetime.now(PKT)
        async with aiosqlite.connect(self.db_path) as db:
            # Get break info
            async with db.execute("""
                SELECT break_start_time, check_in_time FROM active_shifts 
                WHERE user_id = ? AND on_break = 1
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                
                break_start, check_in = row
                break_start_dt = datetime.datetime.fromisoformat(break_start)
                duration = int((now - break_start_dt).total_seconds() / 60)
                duration = min(duration, 40)  # Cap at 40 minutes
                
                # Log the break
                await db.execute("""
                    INSERT INTO break_logs (user_id, username, break_start, break_end, duration_minutes)
                    VALUES (?, ?, ?, ?, ?)
                """, (user_id, username, break_start, now, duration))
                
                # End break
                await db.execute("""
                    UPDATE active_shifts 
                    SET on_break = 0, break_start_time = NULL
                    WHERE user_id = ?
                """, (user_id,))
                await db.commit()
                
                return duration
    
    async def update_status(self, user_id: int, new_status: str):
        """Update user's Discord status (online/idle) during their shift"""
        now = datetime.datetime.now(PKT)
        async with aiosqlite.connect(self.db_path) as db:
            # Check if user is checked in and not on break
            async with db.execute("""
                SELECT current_status, status_start_time, on_break 
                FROM active_shifts WHERE user_id = ?
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:  # Not checked in
                    return
                
                # Unpack all three values from the query
                old_status, status_start, on_break = row
                
                # Skip if on break
                if on_break == 1:
                    return
                
                if old_status == new_status:
                    return  # No change
                
                # Update status
                await db.execute("""
                    UPDATE active_shifts 
                    SET current_status = ?, status_start_time = ?
                    WHERE user_id = ?
                """, (new_status, now, user_id))
                await db.commit()
    
    async def get_active_shift(self, user_id: int) -> Optional[Dict]:
        """Get current active shift info"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT username, check_in_time, current_status, on_break, break_start_time
                FROM active_shifts WHERE user_id = ?
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                
                username, check_in, status, on_break, break_start = row
                check_in_dt = datetime.datetime.fromisoformat(check_in)
                now = datetime.datetime.now(PKT)
                
                return {
                    "username": username,
                    "check_in": check_in_dt,
                    "duration": now - check_in_dt,
                    "status": status,
                    "on_break": bool(on_break),
                    "break_start": datetime.datetime.fromisoformat(break_start) if break_start else None
                }
    
    async def get_user_stats(self, user_id: int, days: int = 7) -> Dict:
        """Get user's work statistics for last N days"""
        cutoff = datetime.datetime.now(PKT) - datetime.timedelta(days=days)
        
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT 
                    COUNT(*) as shifts,
                    COALESCE(SUM(total_minutes), 0) as total_min,
                    COALESCE(SUM(active_minutes), 0) as active_min,
                    COALESCE(SUM(idle_minutes), 0) as idle_min,
                    COALESCE(SUM(break_minutes), 0) as break_min
                FROM shift_history
                WHERE user_id = ? AND check_in_time >= ?
            """, (user_id, cutoff)) as cursor:
                row = await cursor.fetchone()
                
                return {
                    "shifts": row[0] or 0,
                    "total_hours": (row[1] or 0) / 60,
                    "active_hours": (row[2] or 0) / 60,
                    "idle_hours": (row[3] or 0) / 60,
                    "break_hours": (row[4] or 0) / 60
                }
    
    async def get_daily_stats(self, user_id: int, days: int = 7) -> List[Dict]:
        """Get user's work statistics broken down by day"""
        cutoff = datetime.datetime.now(PKT) - datetime.timedelta(days=days)
        
        async with aiosqlite.connect(self.db_path) as db:
            daily_stats = []
            
            # Get shifts grouped by date
            async with db.execute("""
                SELECT 
                    DATE(check_in_time) as shift_date,
                    COUNT(*) as shifts,
                    COALESCE(SUM(total_minutes), 0) as total_min,
                    COALESCE(SUM(active_minutes), 0) as active_min,
                    COALESCE(SUM(break_minutes), 0) as break_min
                FROM shift_history
                WHERE user_id = ? AND check_in_time >= ?
                GROUP BY DATE(check_in_time)
                ORDER BY shift_date DESC
            """, (user_id, cutoff)) as cursor:
                async for row in cursor:
                    shift_date, shifts, total_min, active_min, break_min = row
                    daily_stats.append({
                        "date": shift_date,
                        "shifts": shifts,
                        "total_hours": total_min / 60,
                        "active_hours": active_min / 60,
                        "break_hours": break_min / 60
                    })
            
            return daily_stats
    
    async def get_all_active_shifts(self) -> List[Dict]:
        """Get all currently active shifts"""
        async with aiosqlite.connect(self.db_path) as db:
            shifts = []
            async with db.execute("""
                SELECT user_id, username, check_in_time, current_status, on_break, break_start_time
                FROM active_shifts
            """) as cursor:
                async for row in cursor:
                    try:
                        user_id, username, check_in, status, on_break, break_start = row
                        
                        # Handle both old UTC timestamps and new PKT timestamps
                        try:
                            check_in_dt = datetime.datetime.fromisoformat(check_in)
                            # If it's a naive datetime (old UTC), assume it's UTC and convert to PKT
                            if check_in_dt.tzinfo is None:
                                check_in_dt = check_in_dt.replace(tzinfo=UTC).astimezone(PKT)
                        except ValueError:
                            # Fallback for any parsing issues
                            check_in_dt = datetime.datetime.now(PKT)
                        
                        now = datetime.datetime.now(PKT)
                        
                        # Handle break_start similarly
                        break_start_dt = None
                        if break_start:
                            try:
                                break_start_dt = datetime.datetime.fromisoformat(break_start)
                                if break_start_dt.tzinfo is None:
                                    break_start_dt = break_start_dt.replace(tzinfo=UTC).astimezone(PKT)
                            except ValueError:
                                break_start_dt = None
                        
                        shifts.append({
                            "user_id": user_id,
                            "username": username,
                            "check_in": check_in_dt,
                            "duration": now - check_in_dt,
                            "status": status,
                            "on_break": bool(on_break),
                            "break_start": break_start_dt
                        })
                    except Exception as e:
                        print(f"Error processing shift row: {e}")
                        continue
            return shifts
