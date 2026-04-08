#!/usr/bin/env python3
"""
即梦 Token Auto Refresh - 连接到已运行的 Chrome
Connect to existing Chrome via CDP (Chrome DevTools Protocol)

使用方法：
1. 先启动 Chrome（开启远程调试）：
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
     --remote-debugging-port=9222 \
     --user-data-dir="/tmp/chrome-debug-profile"

   注意：必须使用临时数据目录（/tmp/chrome-debug-profile），
        使用默认数据目录会导致 Chrome 拒绝开启远程调试端口。

2. 在 Chrome 中手动登录即梦（只需要做一次）：https://ai.jimeng.ai

3. 运行此脚本：
   python refresh_jimeng_token_cdp.py
"""

import os
import sys
import time
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# 配置路径
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = Path.home() / ".claude/skills/shared-lib/config.json"

# Chrome CDP 地址
CDP_URL = "http://localhost:9222"

# 即梦网站
JIMENG_URL = "https://ai.jimeng.ai"


class JimengTokenRefresher:
    def __init__(self):
        self.captured_token = None

    def extract_token_from_request(self, request):
        """从网络请求中提取 JWT Token"""
        try:
            # 监控即梦 API 域名
            if "jimeng.ai" in request.url or "ai.jimeng.ai" in request.url:
                headers = request.headers
                auth_header = headers.get("authorization", "")

                if auth_header.startswith("Bearer "):
                    token = auth_header.replace("Bearer ", "").strip()
                    if len(token) > 100:  # JWT Token 很长
                        print(f"🎯 Captured JWT Token from: {request.url[:80]}...")
                        self.captured_token = token
                        return token
        except Exception as e:
            pass
        return None

    def update_config_file(self, token):
        """更新 config.json 文件中的 jimeng_session_id"""
        if not CONFIG_FILE.exists():
            print(f"❌ Config file not found: {CONFIG_FILE}")
            # 创建默认配置
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            config = {
                "jimeng_session_id": token,
                "jimeng_api_url": "http://localhost:8000",
                "jimeng_model": "jimeng-image-4.5"
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"✅ Created new config: {CONFIG_FILE}")
            return True

        try:
            # 读取现有配置
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 更新 jimeng_session_id
            config['jimeng_session_id'] = token

            # 写回文件
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            print(f"✅ Updated {CONFIG_FILE}")
            return True
        except Exception as e:
            print(f"❌ Failed to update config: {e}")
            return False

    def verify_token(self, token):
        """验证 Token 是否有效（可选，通过调用即梦 API）"""
        print("🔍 Verifying token...")
        try:
            import requests

            # 读取配置获取 API URL
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)

            api_url = config.get('jimeng_api_url', 'http://localhost:8000')

            # 发送测试请求（小图片）
            response = requests.post(
                f"{api_url}/v1/images/generations",
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {token}'
                },
                json={
                    'model': 'jimeng-image-4.5',
                    'prompt': 'test',
                    'width': 512,
                    'height': 512,
                    'n': 1
                },
                timeout=10
            )

            if response.status_code == 200:
                print("✅ Token is valid!")
                return True
            else:
                print(f"⚠️  Token validation returned: {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                return False
        except Exception as e:
            print(f"❌ Verification failed: {e}")
            return False

    def check_chrome_running(self):
        """检查 Chrome 是否在运行并开启了远程调试"""
        print("🔍 Checking Chrome remote debugging...")
        try:
            import requests
            response = requests.get(f"{CDP_URL}/json/version", timeout=2)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Chrome connected: {data.get('Browser', 'Unknown')}")
                return True
        except Exception as e:
            print(f"❌ Cannot connect to Chrome at {CDP_URL}")
            print(f"   Error: {e}")
            return False

    def run(self):
        """主运行流程"""
        print("🚀 即梦 Token Auto Refresh (CDP Mode)\n")

        # 检查 Chrome 是否运行
        if not self.check_chrome_running():
            print("\n💡 请先启动 Chrome（开启远程调试）：\n")
            print('"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="/tmp/chrome-debug-profile"\n')
            print("然后重新运行此脚本。")
            return

        try:
            with sync_playwright() as p:
                print("🌐 Connecting to Chrome via CDP...")
                browser = p.chromium.connect_over_cdp(CDP_URL)

                # 获取所有已打开的上下文
                contexts = browser.contexts
                if not contexts:
                    print("❌ No browser context found")
                    print("💡 请先在 Chrome 中打开一个窗口")
                    return

                context = contexts[0]
                pages = context.pages

                # 如果没有页面，创建新页面
                if not pages:
                    page = context.new_page()
                else:
                    # 使用第一个页面
                    page = pages[0]

                # 设置请求监听
                page.on("request", self.extract_token_from_request)

                print(f"📍 Current URL: {page.url}")

                # 如果不在即梦，则导航到即梦
                if "jimeng.ai" not in page.url:
                    print(f"📍 Navigating to {JIMENG_URL}...")
                    try:
                        page.goto(JIMENG_URL, wait_until="domcontentloaded", timeout=60000)
                    except Exception as e:
                        print(f"⚠️  Navigation warning: {e}")

                print("\n" + "="*60)
                print("👉 请检查 Chrome 窗口：")
                print("   1. 确保已登录即梦")
                print("   2. 如果未登录，请现在登录")
                print("   3. 脚本将在 60 秒后自动继续")
                print("="*60)

                print("\n⏳ 等待 60 秒...")
                wait_time = 60
                for i in range(wait_time):
                    time.sleep(1)
                    if i > 0 and i % 15 == 0:
                        remaining = wait_time - i
                        print(f"   还剩 {remaining} 秒...")

                print("\n✅ 继续执行...\n")

                # 尝试触发 API 请求
                if "jimeng.ai" not in page.url:
                    print(f"📍 Navigating to {JIMENG_URL}...")
                    try:
                        page.goto(JIMENG_URL, wait_until="domcontentloaded", timeout=60000)
                    except Exception as e:
                        print(f"⚠️  Navigation warning: {e}")

                # 等待 API 请求
                print("⏳ Waiting for API requests (15 seconds)...")
                time.sleep(15)

                # 如果还没捕获到，尝试交互触发
                if not self.captured_token:
                    print("🔄 Trying to trigger more API requests...")
                    try:
                        # 滚动页面
                        page.mouse.wheel(0, 500)
                        time.sleep(3)

                        # 刷新页面
                        print("🔄 Refreshing page...")
                        page.reload(wait_until="domcontentloaded", timeout=60000)
                        time.sleep(10)
                    except Exception as e:
                        print(f"⚠️  Interaction error: {e}")

                token = self.captured_token

                if token:
                    print(f"\n✅ Token captured! (Length: {len(token)})")
                    print(f"   Token preview: {token[:50]}...{token[-50:]}\n")

                    # 更新 config.json 文件
                    if self.update_config_file(token):
                        # 验证 Token（可选）
                        self.verify_token(token)

                        print("\n" + "="*60)
                        print("✅ Token refresh completed successfully!")
                        print("="*60)
                    else:
                        print("\n❌ Failed to update configuration")
                else:
                    print("\n❌ Failed to capture token")
                    print("💡 Possible reasons:")
                    print("   1. Not logged in to 即梦")
                    print("   2. Network issue")
                    print("   3. Try manually triggering requests (click around the page)")

                browser.close()

        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()


def main():
    refresher = JimengTokenRefresher()
    refresher.run()


if __name__ == "__main__":
    main()
