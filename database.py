import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager
import pytz


class ScheduleDatabase:
    """行程資料庫管理"""

    def __init__(self, db_file='schedules.db', timezone='Asia/Taipei'):
        self.db_file = db_file
        self.tz = pytz.timezone(timezone)
        self.init_database()

    @contextmanager
    def get_connection(self):
        """取得資料庫連線的 context manager"""
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_database(self):
        """初始化資料庫表格"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_notified_1day INTEGER DEFAULT 0,
                    is_notified_1hour INTEGER DEFAULT 0,
                    is_notified_15min INTEGER DEFAULT 0,
                    is_deleted INTEGER DEFAULT 0,
                    UNIQUE(user_id, event_time, title)
                )
            ''')

            # 建立索引加速查詢
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_time 
                ON schedules(user_id, event_time, is_deleted)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_notifications 
                ON schedules(event_time, is_deleted, is_notified_1day, is_notified_1hour, is_notified_15min)
            ''')

            conn.commit()

    def add_schedule(self, user_id, title, event_time):
        """
        新增行程
        返回：(success: bool, schedule_id: int, message: str)
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 檢查是否有重複行程
                cursor.execute('''
                    SELECT id FROM schedules 
                    WHERE user_id = ? AND event_time = ? AND title = ? AND is_deleted = 0
                ''', (user_id, event_time.isoformat(), title))

                if cursor.fetchone():
                    return False, None, '這個行程已經存在了'

                # 新增行程
                cursor.execute('''
                    INSERT INTO schedules (user_id, title, event_time, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (
                    user_id,
                    title,
                    event_time.isoformat(),
                    datetime.now(self.tz).isoformat()
                ))

                schedule_id = cursor.lastrowid
                conn.commit()

                return True, schedule_id, '新增成功'

        except sqlite3.IntegrityError:
            return False, None, '行程已存在'
        except Exception as e:
            return False, None, f'新增失敗: {str(e)}'

    def get_schedules(self, user_id, start_time=None, end_time=None, limit=50):
        """取得使用者的行程列表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = '''
                SELECT id, title, event_time, created_at
                FROM schedules
                WHERE user_id = ? AND is_deleted = 0
            '''
            params = [user_id]

            if start_time:
                query += ' AND event_time >= ?'
                params.append(start_time.isoformat())

            if end_time:
                query += ' AND event_time <= ?'
                params.append(end_time.isoformat())

            query += ' ORDER BY event_time ASC LIMIT ?'
            params.append(limit)

            cursor.execute(query, params)

            schedules = []
            for row in cursor.fetchall():
                schedules.append({
                    'id': row['id'],
                    'title': row['title'],
                    'event_time': datetime.fromisoformat(row['event_time']),
                    'created_at': datetime.fromisoformat(row['created_at'])
                })

            return schedules

    def get_today_schedules(self, user_id):
        """取得今天的行程"""
        now = datetime.now(self.tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self.get_schedules(user_id, start, end)

    def get_tomorrow_schedules(self, user_id):
        """取得明天的行程"""
        now = datetime.now(self.tz)
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self.get_schedules(user_id, start, end)

    def get_week_schedules(self, user_id):
        """取得本週的行程"""
        now = datetime.now(self.tz)
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        return self.get_schedules(user_id, start, end)

    def get_all_upcoming_schedules(self, user_id):
        """取得所有未來的行程"""
        now = datetime.now(self.tz)
        return self.get_schedules(user_id, start_time=now)

    def delete_schedule(self, schedule_id, user_id):
        """刪除行程（軟刪除）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE schedules 
                    SET is_deleted = 1 
                    WHERE id = ? AND user_id = ? AND is_deleted = 0
                ''', (schedule_id, user_id))

                if cursor.rowcount > 0:
                    conn.commit()
                    return True, '刪除成功'
                else:
                    return False, '找不到這個行程'

        except Exception as e:
            return False, f'刪除失敗: {str(e)}'

    def get_schedules_for_reminder(self):
        """取得需要提醒的行程"""
        now = datetime.now(self.tz)

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, user_id, title, event_time,
                       is_notified_1day, is_notified_1hour, is_notified_15min
                FROM schedules
                WHERE is_deleted = 0 AND event_time > ?
                ORDER BY event_time
            ''', (now.isoformat(),))

            reminders = []

            for row in cursor.fetchall():
                event_time = datetime.fromisoformat(row['event_time'])
                time_diff = (event_time - now).total_seconds() / 60

                schedule_info = {
                    'id': row['id'],
                    'user_id': row['user_id'],
                    'title': row['title'],
                    'event_time': event_time,
                    'reminder_type': None
                }

                # 前一天提醒
                if not row['is_notified_1day'] and 1410 <= time_diff <= 1470:
                    schedule_info['reminder_type'] = '1day'
                    reminders.append(schedule_info)
                # 前1小時提醒
                elif not row['is_notified_1hour'] and 55 <= time_diff <= 65:
                    schedule_info['reminder_type'] = '1hour'
                    reminders.append(schedule_info)
                # 前15分鐘提醒
                elif not row['is_notified_15min'] and 13 <= time_diff <= 17:
                    schedule_info['reminder_type'] = '15min'
                    reminders.append(schedule_info)

            return reminders

    def mark_as_notified(self, schedule_id, reminder_type):
        """標記行程已提醒"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            column_map = {
                '1day': 'is_notified_1day',
                '1hour': 'is_notified_1hour',
                '15min': 'is_notified_15min'
            }

            column = column_map.get(reminder_type)
            if column:
                cursor.execute(f'''
                    UPDATE schedules 
                    SET {column} = 1 
                    WHERE id = ?
                ''', (schedule_id,))
                conn.commit()