import os
import threading
import time
import requests
from datetime import datetime
from flask import Flask, request, abort, jsonify
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from dotenv import load_dotenv

# 載入自訂模組
from schedule_parser import ScheduleParser
from database import ScheduleDatabase
from reminder import ReminderSystem

# 載入環境變數
load_dotenv()

app = Flask(__name__)

# 設定 LINE Bot
configuration = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# 初始化核心模組
parser = ScheduleParser()
db = ScheduleDatabase()

# 全域變數：提醒系統（稍後初始化）
reminder_system = None


# ==================== 路由設定 ====================

@app.route("/")
def hello():
    """首頁 - 確認服務運行狀態"""
    return "Schedule LINE Bot is running! 🤖", 200


@app.route("/health")
def health():
    """健康檢查端點 - 供監控服務使用"""
    return "OK", 200


@app.route("/webhook", methods=['POST'])
def webhook():
    """LINE Webhook 端點"""
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        app.logger.warning("Missing signature")
        abort(400)

    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature")
        abort(400)

    return 'OK'


# ==================== LINE 訊息處理 ====================

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """處理使用者訊息"""
    user_message = event.message.text.strip()
    user_id = event.source.user_id

    app.logger.info(f"[User {user_id[:8]}...] {user_message}")

    # 查詢指令
    if user_message in ['今天行程', '今天的行程', '今日行程']:
        show_today_schedules(event, user_id)
        return

    if user_message in ['明天行程', '明天的行程']:
        show_tomorrow_schedules(event, user_id)
        return

    if user_message in ['本週行程', '這週行程', '本周行程']:
        show_week_schedules(event, user_id)
        return

    if user_message in ['所有行程', '全部行程', '我的行程']:
        show_all_schedules(event, user_id)
        return

    if user_message in ['幫助', 'help', '說明', '指令']:
        show_help(event)
        return

    # 刪除指令
    if user_message.startswith('刪除') or user_message.startswith('取消'):
        handle_delete_schedule(event, user_id, user_message)
        return

    # 預設：解析為行程
    handle_add_schedule(event, user_id, user_message)


def handle_add_schedule(event, user_id, user_message):
    """處理新增行程"""
    # 使用 LLM 解析行程
    parse_result = parser.parse(user_message)

    if not parse_result['success']:
        # 解析失敗
        error_msg = parse_result.get('error', '無法理解時間格式')
        reply_text = f"❌ {error_msg}"
        reply_message(event, reply_text)
        return

    # 解析成功，儲存到資料庫
    event_time = parse_result['datetime']
    title = parse_result['title']

    success, schedule_id, message = db.add_schedule(user_id, title, event_time)

    if success:
        # 建立確認訊息
        reply_text = create_schedule_confirmation(schedule_id, title, event_time)
    else:
        reply_text = f"❌ {message}"

    reply_message(event, reply_text)


def show_today_schedules(event, user_id):
    """顯示今天的行程"""
    schedules = db.get_today_schedules(user_id)
    reply_text = format_schedule_list(schedules, "今天")
    reply_message(event, reply_text)


def show_tomorrow_schedules(event, user_id):
    """顯示明天的行程"""
    schedules = db.get_tomorrow_schedules(user_id)
    reply_text = format_schedule_list(schedules, "明天")
    reply_message(event, reply_text)


def show_week_schedules(event, user_id):
    """顯示本週的行程"""
    schedules = db.get_week_schedules(user_id)
    reply_text = format_schedule_list(schedules, "本週")
    reply_message(event, reply_text)


def show_all_schedules(event, user_id):
    """顯示所有未來的行程"""
    schedules = db.get_all_upcoming_schedules(user_id)
    reply_text = format_schedule_list(schedules, "所有未來")
    reply_message(event, reply_text)


def handle_delete_schedule(event, user_id, user_message):
    """處理刪除行程"""
    import re
    match = re.search(r'#?(\d+)', user_message)

    if not match:
        reply_text = "請指定要刪除的行程編號\n例如：刪除 #123"
        reply_message(event, reply_text)
        return

    schedule_id = int(match.group(1))
    success, message = db.delete_schedule(schedule_id, user_id)

    if success:
        reply_text = f"✅ {message}\n行程 #{schedule_id} 已刪除"
    else:
        reply_text = f"❌ {message}"

    reply_message(event, reply_text)


def show_help(event):
    """顯示幫助訊息"""
    help_text = """📖 使用說明

🆕 新增行程
直接輸入時間和事項即可：
• 明天早上9點開會
• 後天下午2點聚餐
• 1月20日晚上7點運動
• 下週一上午10點會議

📋 查詢行程
• 今天行程
• 明天行程
• 本週行程
• 所有行程

🗑️ 刪除行程
• 刪除 #123（編號在行程列表中）

💡 提醒功能
系統會自動提醒：
• 前一天同時間（24小時後的行程）
• 前1小時
• 前15分鐘

有問題隨時說「幫助」查看說明！"""

    reply_message(event, help_text)


# ==================== 訊息格式化函式 ====================

def create_schedule_confirmation(schedule_id, title, event_time):
    """建立行程確認訊息"""
    weekday_names = ['週一', '週二', '週三', '週四', '週五', '週六', '週日']
    weekday = weekday_names[event_time.weekday()]

    # 計算提醒時間
    now = datetime.now(event_time.tzinfo)
    time_diff = (event_time - now).total_seconds() / 3600  # 小時

    reminders = []
    if time_diff >= 24:
        reminders.append("• 前一天同時間")
    if time_diff >= 1:
        reminders.append("• 前1小時")
    if time_diff >= 0.25:
        reminders.append("• 前15分鐘")

    reminder_text = "\n".join(reminders) if reminders else "• 無提醒（時間太近）"

    message = f"""✅ 行程已記錄

📅 時間：{event_time.strftime('%m月%d日')} ({weekday}) {event_time.strftime('%H:%M')}
📝 事項：{title}
🆔 編號：#{schedule_id}

🔔 將在以下時間提醒您：
{reminder_text}"""

    return message


def format_schedule_list(schedules, period_name):
    """格式化行程列表"""
    if not schedules:
        return f"📋 {period_name}沒有安排的行程\n\n💡 直接輸入時間和事項來新增行程\n例如：明天早上9點開會"

    weekday_names = ['週一', '週二', '週三', '週四', '週五', '週六', '週日']

    lines = [f"📋 {period_name}的行程\n"]

    current_date = None
    for schedule in schedules:
        event_time = schedule['event_time']
        date_str = event_time.strftime('%m月%d日')

        # 如果是新的日期，加上日期標題
        if date_str != current_date:
            weekday = weekday_names[event_time.weekday()]
            lines.append(f"\n📅 {date_str} ({weekday})")
            current_date = date_str

        time_str = event_time.strftime('%H:%M')
        lines.append(f"  {time_str} - {schedule['title']} #{schedule['id']}")

    lines.append(f"\n共 {len(schedules)} 個行程")
    lines.append("\n💡 說「刪除 #編號」可以刪除行程")

    return '\n'.join(lines)


def reply_message(event, text):
    """回覆訊息的統一介面"""
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=text)]
                )
            )
    except Exception as e:
        app.logger.error(f"Error sending reply: {e}")


# ==================== 內部保持喚醒機制 ====================

def keep_alive_internal():
    """內部保持喚醒執行緒"""
    print("[Keep-Alive] Thread started, waiting 90 seconds...")
    time.sleep(90)

    base_url = os.getenv('RENDER_EXTERNAL_URL', 'https://schedule-linebot.onrender.com')
    health_url = f"{base_url}/health"

    print(f"[Keep-Alive] Will ping {health_url} every 12 minutes")

    ping_count = 0
    while True:
        try:
            time.sleep(12 * 60)  # 12 分鐘
            ping_count += 1

            response = requests.get(health_url, timeout=10)
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if response.status_code == 200:
                print(f"[Keep-Alive #{ping_count}] [{current_time}] ✓ OK")
            else:
                print(f"[Keep-Alive #{ping_count}] [{current_time}] ✗ Status: {response.status_code}")

        except Exception as e:
            print(f"[Keep-Alive #{ping_count}] [{datetime.now()}] ✗ Error: {str(e)[:100]}")


# ==================== 主程式 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("Schedule LINE Bot Starting...")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 啟動內部保持喚醒執行緒
    keep_alive_thread = threading.Thread(
        target=keep_alive_internal,
        daemon=True,
        name="KeepAliveThread"
    )
    keep_alive_thread.start()
    print("✓ Internal keep-alive thread started")

    # 啟動提醒系統
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            reminder_system = ReminderSystem(line_bot_api)
            reminder_system.start()
            print("✓ Reminder system started")
    except Exception as e:
        print(f"⚠ Reminder system failed to start: {e}")

    # 啟動 Flask 服務
    port = int(os.getenv("PORT", 8000))
    print(f"✓ Starting Flask server on port {port}")
    print("=" * 60)

    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True
    )