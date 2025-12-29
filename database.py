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
                    offline_minutes INTEGER DEFAULT 0,
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
            
            # Table for employee expected check-in times
            await db.execute("""
                CREATE TABLE IF NOT EXISTS employee_schedule (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    expected_checkin_time TEXT,
                    expected_checkout_time TEXT,
                    work_days TEXT
                )
            """)
            
            # Table for tracking sent reports
            await db.execute("""
                CREATE TABLE IF NOT EXISTS report_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_type TEXT,
                    report_date DATE,
                    sent_at TIMESTAMP
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
                
                # Get idle, offline, and break time from status logs
                idle_minutes = 0
                offline_minutes = 0
                break_minutes = 0
                
                # Get status logs for this shift
                async with db.execute("""
                    SELECT status, COALESCE(SUM(duration_minutes), 0) 
                    FROM status_logs 
                    WHERE user_id = ? AND start_time >= ?
                    GROUP BY status
                """, (user_id, check_in)) as cursor2:
                    async for row in cursor2:
                        status, duration = row
                        if status == 'idle':
                            idle_minutes += duration
                        elif status == 'offline':
                            offline_minutes += duration
                
                # Calculate any ongoing break
                if on_break and break_start:
                    break_start_dt = datetime.datetime.fromisoformat(break_start)
                    break_duration = int((now - break_start_dt).total_seconds() / 60)
                    break_minutes += min(break_duration, 40)  # Cap at 40 minutes
                
                # Get historical break time for this shift
                async with db.execute("""
                    SELECT COALESCE(SUM(duration_minutes), 0) FROM break_logs
                    WHERE user_id = ? AND break_start >= ?
                """, (user_id, check_in)) as cursor3:
                    result = await cursor3.fetchone()
                    if result:
                        break_minutes += result[0]
                
                # Calculate active time: total - idle - offline - break
                active_minutes = total_minutes - idle_minutes - offline_minutes - break_minutes
                active_minutes = max(0, active_minutes)  # Ensure non-negative
                
                # Save shift to history
                await db.execute("""
                    INSERT INTO shift_history (user_id, username, check_in_time, check_out_time, 
                                              total_minutes, idle_minutes, offline_minutes, break_minutes, active_minutes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, username, check_in, now, total_minutes, idle_minutes, offline_minutes, break_minutes, active_minutes))
                
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
                    "offline_minutes": offline_minutes,
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
        """Update user's Discord status (online/idle/offline) during their shift"""
        now = datetime.datetime.now(PKT)
        async with aiosqlite.connect(self.db_path) as db:
            # Check if user is checked in and not on break
            async with db.execute("""
                SELECT current_status, status_start_time, on_break, check_in_time
                FROM active_shifts WHERE user_id = ?
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:  # Not checked in
                    return
                
                # Unpack all values from the query
                old_status, status_start, on_break, check_in = row
                
                # Skip if on break
                if on_break == 1:
                    return
                
                if old_status == new_status:
                    return  # No change
                
                # Log the previous status period
                if status_start:
                    try:
                        status_start_dt = datetime.datetime.fromisoformat(status_start)
                        if status_start_dt.tzinfo is None:
                            status_start_dt = status_start_dt.replace(tzinfo=UTC).astimezone(PKT)
                        
                        duration_minutes = int((now - status_start_dt).total_seconds() / 60)
                        
                        # Only log if duration is significant (more than 1 minute)
                        if duration_minutes > 1 and old_status in ['idle', 'offline']:
                            await db.execute("""
                                INSERT INTO status_logs (user_id, status, start_time, end_time, duration_minutes)
                                VALUES (?, ?, ?, ?, ?)
                            """, (user_id, old_status, status_start, now, duration_minutes))
                    except Exception as e:
                        print(f"Error logging status change: {e}")
                
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
                    COALESCE(SUM(offline_minutes), 0) as offline_min,
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
                    "offline_hours": (row[4] or 0) / 60,
                    "break_hours": (row[5] or 0) / 60
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
                    COALESCE(SUM(idle_minutes), 0) as idle_min,
                    COALESCE(SUM(offline_minutes), 0) as offline_min,
                    COALESCE(SUM(break_minutes), 0) as break_min
                FROM shift_history
                WHERE user_id = ? AND check_in_time >= ?
                GROUP BY DATE(check_in_time)
                ORDER BY shift_date DESC
            """, (user_id, cutoff)) as cursor:
                async for row in cursor:
                    shift_date, shifts, total_min, active_min, idle_min, offline_min, break_min = row
                    daily_stats.append({
                        "date": shift_date,
                        "shifts": shifts,
                        "total_hours": total_min / 60,
                        "active_hours": active_min / 60,
                        "idle_hours": idle_min / 60,
                        "offline_hours": offline_min / 60,
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
    
    async def get_missing_checkins(self, expected_time: str = "09:00") -> List[Dict]:
        """Get employees who haven't checked in by expected time"""
        now = datetime.datetime.now(PKT)
        today = now.date()
        expected_dt = datetime.datetime.combine(today, datetime.time.fromisoformat(expected_time))
        expected_dt = expected_dt.replace(tzinfo=PKT)
        
        # Only check if current time is past expected time
        if now < expected_dt:
            return []
        
        async with aiosqlite.connect(self.db_path) as db:
            missing = []
            # Get all employees with schedules
            async with db.execute("""
                SELECT user_id, username, expected_checkin_time, work_days
                FROM employee_schedule
            """) as cursor:
                async for row in cursor:
                    user_id, username, expected, work_days = row
                    # Check if today is a work day
                    day_name = now.strftime('%A').lower()
                    if work_days and day_name not in work_days.lower():
                        continue
                    
                    # Check if user has checked in today
                    async with db.execute("""
                        SELECT user_id FROM active_shifts 
                        WHERE user_id = ? AND DATE(check_in_time) = DATE(?)
                    """, (user_id, now)) as check_cursor:
                        if await check_cursor.fetchone():
                            continue  # Already checked in
                    
                    missing.append({
                        "user_id": user_id,
                        "username": username,
                        "expected_time": expected or expected_time
                    })
            return missing
    
    async def get_missing_checkouts(self) -> List[Dict]:
        """Get employees who haven't checked out (still checked in from previous day)"""
        now = datetime.datetime.now(PKT)
        yesterday = now - datetime.timedelta(days=1)
        
        async with aiosqlite.connect(self.db_path) as db:
            missing = []
            # Get all active shifts that started before today
            async with db.execute("""
                SELECT user_id, username, check_in_time
                FROM active_shifts
                WHERE DATE(check_in_time) < DATE(?)
            """, (now,)) as cursor:
                async for row in cursor:
                    user_id, username, check_in = row
                    try:
                        check_in_dt = datetime.datetime.fromisoformat(check_in)
                        if check_in_dt.tzinfo is None:
                            check_in_dt = check_in_dt.replace(tzinfo=UTC).astimezone(PKT)
                        
                        # If checked in more than 12 hours ago, likely forgot to checkout
                        hours_ago = (now - check_in_dt).total_seconds() / 3600
                        if hours_ago > 12:
                            missing.append({
                                "user_id": user_id,
                                "username": username,
                                "check_in_time": check_in_dt,
                                "hours_ago": hours_ago
                            })
                    except Exception as e:
                        print(f"Error processing missing checkout: {e}")
            return missing
    
    async def set_employee_schedule(self, user_id: int, username: str, checkin_time: str, checkout_time: str, work_days: str = "monday,tuesday,wednesday,thursday,friday"):
        """Set expected schedule for an employee"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO employee_schedule 
                (user_id, username, expected_checkin_time, expected_checkout_time, work_days)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, username, checkin_time, checkout_time, work_days))
            await db.commit()
    
    async def get_weekly_report_data(self, start_date: datetime.date, end_date: datetime.date) -> Dict:
        """Get data for weekly report"""
        async with aiosqlite.connect(self.db_path) as db:
            # Get all shifts in date range
            async with db.execute("""
                SELECT 
                    user_id,
                    username,
                    COUNT(*) as shifts,
                    COALESCE(SUM(total_minutes), 0) as total_min,
                    COALESCE(SUM(active_minutes), 0) as active_min,
                    COALESCE(SUM(idle_minutes), 0) as idle_min,
                    COALESCE(SUM(offline_minutes), 0) as offline_min,
                    COALESCE(SUM(break_minutes), 0) as break_min
                FROM shift_history
                WHERE DATE(check_in_time) >= ? AND DATE(check_in_time) <= ?
                GROUP BY user_id, username
                ORDER BY active_min DESC
            """, (start_date, end_date)) as cursor:
                employees = []
                async for row in cursor:
                    user_id, username, shifts, total_min, active_min, idle_min, offline_min, break_min = row
                    employees.append({
                        "user_id": user_id,
                        "username": username,
                        "shifts": shifts,
                        "total_hours": total_min / 60,
                        "active_hours": active_min / 60,
                        "idle_hours": idle_min / 60,
                        "offline_hours": offline_min / 60,
                        "break_hours": break_min / 60,
                        "productivity_score": (active_min / total_min * 100) if total_min > 0 else 0
                    })
                
                return {
                    "start_date": start_date,
                    "end_date": end_date,
                    "employees": employees,
                    "total_employees": len(employees)
                }
    
    async def get_monthly_report_data(self, year: int, month: int) -> Dict:
        """Get data for monthly report"""
        start_date = datetime.date(year, month, 1)
        if month == 12:
            end_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            end_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
        
        return await self.get_weekly_report_data(start_date, end_date)
    
    async def log_report_sent(self, report_type: str, report_date: datetime.date):
        """Log that a report was sent"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO report_logs (report_type, report_date, sent_at)
                VALUES (?, ?, ?)
            """, (report_type, report_date, datetime.datetime.now(PKT)))
            await db.commit()
    
    async def was_report_sent(self, report_type: str, report_date: datetime.date) -> bool:
        """Check if a report was already sent"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT id FROM report_logs 
                WHERE report_type = ? AND report_date = ?
            """, (report_type, report_date)) as cursor:
                return await cursor.fetchone() is not None
