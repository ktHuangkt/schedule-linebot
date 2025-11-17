import threading
import time
from datetime import datetime, timedelta
import pytz
from database import ScheduleDatabase


class ReminderSystem:
    """智能提醒系統"""

    def __init__(self, line_bot_api, timezone='Asia/Taipei'):
        self.tz = pytz.timezone(timezone)
        self.db = ScheduleDatabase(timezone=timezone)
        self.line_bot_api = line_bot_api  # 傳入 MessagingApi 實例
        self.is_running = False
        self.check_interval = 60  # 每 60 秒檢查一次

    def start(self):
        """啟動提醒系統"""
        if self.is_running:
            print("[Reminder] Already running")
            return

        self.is_running = True
        reminder_thread = threading.Thread(
            target=self._check_loop,
            daemon=True,
            name="ReminderThread"
        )
        reminder_thread.start()
        print("[Reminder] System started")

    def stop(self):
        """停止提醒系統"""
        self.is_running = False
        print("[Reminder] System stopped")

    def _check_loop(self):
        """持續檢查需要提醒的行程"""
        print(f"[Reminder] Check loop started - interval: {self.check_interval}s")

        # 等待服務完全啟動
        time.sleep(90)

        while self.is_running:
            try:
                self._check_and_send_reminders()
            except Exception as e:
                print(f"[Reminder] Check error: {e}")

            time.sleep(self.check_interval)

    def _check_and_send_reminders(self):
        """檢查並發送提醒"""
        now = datetime.now(self.tz)

        # 從資料庫取得需要提醒的行程
        reminders = self.db.get_schedules_for_reminder()

        if not reminders:
            return

        print(f"[Reminder] Found {len(reminders)} schedules to check at {now.strftime('%H:%M:%S')}")

        for reminder in reminders:
            try:
                # 發送提醒訊息
                message = self._create_reminder_message(reminder)
                self._send_push_message(reminder['user_id'], message)

                # 標記為已提醒
                self.db.mark_as_notified(reminder['id'], reminder['reminder_type'])

                print(f"[Reminder] Sent {reminder['reminder_type']} reminder for: {reminder['title']}")

            except Exception as e:
                print(f"[Reminder] Failed to send reminder: {e}")

    def _create_reminder_message(self, reminder):
        """建立提醒訊息"""
        event_time = reminder['event_time']
        title = reminder['title']
        reminder_type = reminder['reminder_type']

        # 根據提醒類型建立不同訊息
        if reminder_type == '1day':
            time_desc = "明天同時間"
            emoji = "📅"
        elif reminder_type == '1hour':
            time_desc = "1小時後"
            emoji = "⏰"
        elif reminder_type == '15min':
            time_desc = "15分鐘後"
            emoji = "🔔"
        else:
            time_desc = "即將開始"
            emoji = "⏰"

        # 格式化時間
        weekday_names = ['週一', '週二', '週三', '週四', '週五', '週六', '週日']
        weekday = weekday_names[event_time.weekday()]
        time_str = event_time.strftime('%m月%d日 %H:%M')

        message = f"""{emoji} 行程提醒

{time_desc}

📝 {title}
🕐 {time_str} ({weekday})

請準時參加！"""

        return message

    def _send_push_message(self, user_id, message):
        """發送 LINE 推播訊息"""
        try:
            from linebot.v3.messaging import PushMessageRequest, TextMessage

            self.line_bot_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=message)]
                )
            )
        except Exception as e:
            print(f"[Reminder] Push message error: {e}")
            raise