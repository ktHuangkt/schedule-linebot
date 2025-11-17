import os
import threading
import time
import requests
from datetime import datetime
from flask import Flask, request, abort, jsonify
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

app = Flask(__name__)

# 設定 LINE Bot
configuration = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))


# ==================== 路由設定 ====================

@app.route("/")
def hello():
    """首頁 - 確認服務運行狀態"""
    return "Schedule LINE Bot is running! v3 API", 200


@app.route("/health")
def health():
    """健康檢查端點 - 簡化輸出避免 cron-job 錯誤"""
    return "OK", 200


@app.route("/webhook", methods=['POST'])
def webhook():
    """LINE Webhook 端點"""
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        app.logger.warning("Missing signature")
        abort(400)

    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")

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
    user_message = event.message.text
    app.logger.info(f"Received message: {user_message}")

    # 簡單回應（之後會擴展成行程解析）
    reply_text = f"收到訊息：{user_message}\n\n功能開發中，敬請期待！"

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
    except Exception as e:
        app.logger.error(f"Error sending reply: {e}")


# ==================== 內部保持喚醒機制 ====================

def keep_alive_internal():
    """
    內部保持喚醒執行緒
    每 12 分鐘 ping 一次自己，確保服務不休眠
    """
    # 等待服務完全啟動
    print("[Keep-Alive] Waiting for service to start...")
    time.sleep(90)

    # 獲取服務 URL
    base_url = os.getenv('RENDER_EXTERNAL_URL', 'https://schedule-linebot.onrender.com')
    health_url = f"{base_url}/health"

    print(f"[Keep-Alive] Started - will ping {health_url} every 12 minutes")

    while True:
        try:
            # 等待 12 分鐘（比 15 分鐘休眠時間短）
            time.sleep(12 * 60)

            # Ping 健康檢查端點
            response = requests.get(health_url, timeout=10)
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if response.status_code == 200:
                print(f"[Keep-Alive] [{current_time}] ✓ Service is healthy")
            else:
                print(f"[Keep-Alive] [{current_time}] ✗ Unexpected status: {response.status_code}")

        except requests.exceptions.Timeout:
            print(f"[Keep-Alive] [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✗ Timeout")
        except requests.exceptions.RequestException as e:
            print(f"[Keep-Alive] [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✗ Error: {e}")
        except Exception as e:
            print(f"[Keep-Alive] [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✗ Unexpected error: {e}")


# ==================== 主程式 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("Schedule LINE Bot Starting...")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python Version: {os.sys.version}")
    print("=" * 60)

    # 啟動內部保持喚醒執行緒
    keep_alive_thread = threading.Thread(
        target=keep_alive_internal,
        daemon=True,
        name="KeepAliveThread"
    )
    keep_alive_thread.start()
    print("✓ Internal keep-alive thread started")

    # 啟動 Flask 服務
    port = int(os.getenv("PORT", 8000))
    print(f"✓ Starting Flask server on port {port}")
    print("=" * 60)

    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True  # 支援多執行緒
    )