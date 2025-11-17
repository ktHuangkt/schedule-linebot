import os
import json
from datetime import datetime
import pytz
import requests


class ScheduleParser:
    """使用 Groq LLM 解析自然語言行程"""

    def __init__(self, timezone='Asia/Taipei'):
        self.tz = pytz.timezone(timezone)
        self.api_key = os.getenv('GROQ_API_KEY')
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"

        if not self.api_key:
            raise ValueError("請設定 GROQ_API_KEY 環境變數")

    def parse(self, text):
        """
        解析使用者輸入的行程
        返回：{
            'success': True/False,
            'datetime': datetime 物件,
            'title': 事件標題,
            'error': 錯誤訊息（如果有）
        }
        """
        try:
            now = datetime.now(self.tz)

            # 建立給 LLM 的 prompt
            prompt = self._build_prompt(text, now)

            # 呼叫 Groq API
            llm_response = self._call_groq(prompt)

            if not llm_response:
                return {
                    'success': False,
                    'error': 'AI 服務暫時無法使用\n請稍後再試'
                }

            # 處理 LLM 的回應
            return self._process_response(llm_response, now)

        except Exception as e:
            print(f"[Parser Error] {e}")
            return {
                'success': False,
                'error': '解析時發生錯誤\n請重新輸入'
            }

    def _build_prompt(self, text, now):
        """建立給 LLM 的 prompt"""
        current_time = now.strftime('%Y-%m-%d %H:%M')
        weekday_names = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
        weekday = weekday_names[now.weekday()]

        prompt = f"""你是一個行程助手，負責解析使用者的行程安排。

【當前時間】
{current_time} ({weekday})

【使用者說】
{text}

【解析規則】
1. 時間關鍵字：
   - 明天 = 明天同時間
   - 後天 = 後天同時間  
   - 大後天 = 大後天同時間
   - 下星期X = 下週的星期X
   - 這週X = 本週的星期X

2. 時段對應：
   - 早上/早晨 = 07:00
   - 上午 = 09:00
   - 中午 = 12:00
   - 下午 = 14:00
   - 傍晚 = 17:00
   - 晚上 = 19:00
   - 深夜 = 22:00

3. 如果只說時間沒說日期：
   - 時間已過 → 設為明天
   - 時間未過 → 設為今天

4. 行程標題：
   - 簡潔明確
   - 移除無關字詞

【輸出格式】
嚴格按照以下 JSON 格式回覆，不要有任何其他文字：

成功時：
{{
    "success": true,
    "datetime": "2025-01-20 14:00",
    "title": "團隊會議"
}}

失敗時：
{{
    "success": false,
    "error": "無法理解時間"
}}

現在請解析："""

        return prompt

    def _call_groq(self, prompt):
        """呼叫 Groq API"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": "llama-3.3-70b-versatile",  # 使用正確的模型名稱
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 300
            }

            response = requests.post(
                self.api_url,
                headers=headers,
                json=data,
                timeout=15
            )

            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                print(f"[Groq API Error] Status: {response.status_code}")
                print(f"[Groq API Response] {response.text}")
                return None

        except requests.exceptions.Timeout:
            print("[Groq API] Timeout")
            return None
        except Exception as e:
            print(f"[Groq API] Error: {e}")
            return None

    def _process_response(self, response_text, now):
        """處理 LLM 的回應"""
        try:
            # 移除可能的 markdown 格式
            response_text = response_text.strip()
            if response_text.startswith('```'):
                # 提取 JSON 部分
                lines = response_text.split('\n')
                json_lines = [l for l in lines if l and not l.startswith('```')]
                response_text = '\n'.join(json_lines)

            # 找到 JSON 部分
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)
            else:
                return {
                    'success': False,
                    'error': 'AI 回應格式錯誤'
                }

            # 檢查解析是否成功
            if not result.get('success', False):
                error_msg = result.get('error', '無法理解時間格式')
                return {
                    'success': False,
                    'error': f'{error_msg}\n\n試試這樣說：\n• 明天早上9點開會\n• 後天下午2點聚餐\n• 1月20日晚上7點運動'
                }

            # 解析日期時間
            datetime_str = result['datetime']

            # 支援多種日期時間格式
            for fmt in ['%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M']:
                try:
                    event_time = datetime.strptime(datetime_str, fmt)
                    event_time = self.tz.localize(event_time)
                    break
                except ValueError:
                    continue
            else:
                return {
                    'success': False,
                    'error': 'AI 返回的時間格式錯誤'
                }

            # 檢查時間是否已過
            if event_time <= now:
                return {
                    'success': False,
                    'error': '這個時間已經過去了\n請設定未來的時間'
                }

            # 檢查標題
            title = result.get('title', '').strip()
            if not title or len(title) < 1:
                title = '待辦事項'

            return {
                'success': True,
                'datetime': event_time,
                'title': title
            }

        except json.JSONDecodeError as e:
            print(f"[JSON Error] {e}")
            print(f"[Response] {response_text}")
            return {
                'success': False,
                'error': 'AI 回應格式錯誤'
            }
        except Exception as e:
            print(f"[Process Error] {e}")
            return {
                'success': False,
                'error': '處理回應時出錯'
            }


# 測試程式碼
if __name__ == '__main__':
    # 需要設定環境變數 GROQ_API_KEY
    from dotenv import load_dotenv

    load_dotenv()

    parser = ScheduleParser()

    test_cases = [
        '明天早上7點開會',
        '後天下午兩點要去聚餐',
        '下禮拜一上午10點有會議',
        '1月20號晚上8點運動',
        '今天晚上7點吃飯',
        '禮拜五下午3點要交報告',
        '三天後中午12點半午餐',
        '下個月1號早上9點面試',
    ]

    print("=" * 60)
    print("LLM 行程解析測試")
    print("=" * 60)

    for case in test_cases:
        print(f'\n輸入: {case}')
        result = parser.parse(case)

        if result['success']:
            print(f"✓ 成功")
            print(f"  時間: {result['datetime'].strftime('%Y-%m-%d %H:%M')}")
            print(f"  標題: {result['title']}")
        else:
            print(f"✗ 失敗")
            print(f"  錯誤: {result['error']}")
        print("-" * 60)