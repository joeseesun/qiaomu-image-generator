#!/usr/bin/env python3
"""
统一配图生成器（独立版）

用法:
    python generate.py <visual_config.json>
    python generate.py <visual_config.json> --workers 3
    python generate.py <visual_config.json> --dry-run

功能:
    - 读取 visual_config.json 配置
    - 使用本地 styles.json 风格模板（不依赖 shared-lib）
    - 多线程并发生成图片
    - 自动重试失败的任务
"""

import argparse
import json
import os
import sys
import time
import threading
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 配置目录
CONFIG_DIR = Path(__file__).parent.parent / 'config'

# 线程锁（用于打印）
print_lock = threading.Lock()


def safe_print(*args, **kwargs):
    """线程安全的打印"""
    with print_lock:
        print(*args, **kwargs)


def load_styles() -> Dict:
    """加载风格模板"""
    styles_file = CONFIG_DIR / 'styles.json'
    if not styles_file.exists():
        raise FileNotFoundError(f"风格配置文件不存在: {styles_file}")
    return json.loads(styles_file.read_text(encoding='utf-8'))


def load_templates() -> Dict:
    """加载场景模板"""
    templates_file = CONFIG_DIR / 'templates.json'
    if not templates_file.exists():
        raise FileNotFoundError(f"场景模板文件不存在: {templates_file}")
    return json.loads(templates_file.read_text(encoding='utf-8'))


def load_providers() -> Dict:
    """加载 API 配置"""
    providers_file = CONFIG_DIR / 'providers.json'
    if not providers_file.exists():
        raise FileNotFoundError(f"API 配置文件不存在: {providers_file}")
    return json.loads(providers_file.read_text(encoding='utf-8'))


def load_config(config_path: str) -> Dict:
    """加载任务配置"""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    return json.loads(config_file.read_text(encoding='utf-8'))


def get_api_credentials() -> Dict:
    """获取 API 凭据"""
    # 从 shared-lib 的 config.json 读取
    config_path = Path.home() / '.claude' / 'skills' / 'shared-lib' / 'config.json'
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding='utf-8'))
        return {
            'jimeng_session_id': config.get('jimeng_session_id', ''),
            'jimeng_api_key': config.get('jimeng_api_key', os.environ.get('JIMENG_API_KEY', 'jimeng@42')),
            'jimeng_api_url': config.get('jimeng_api_url', 'https://api.qiaomu.ai/jimeng-auth'),
            'jimeng_model': config.get('jimeng_model', 'jimeng-4.5'),
            'modelscope_api_key': config.get('modelscope_api_key', '')
        }

    # 回退到环境变量
    return {
        'jimeng_session_id': os.environ.get('JIMENG_SESSION_ID', ''),
        'jimeng_api_key': os.environ.get('JIMENG_API_KEY', 'jimeng@42'),
        'jimeng_api_url': os.environ.get('JIMENG_API_URL', 'https://api.qiaomu.ai/jimeng-auth'),
        'jimeng_model': os.environ.get('JIMENG_MODEL', 'jimeng-4.5'),
        'modelscope_api_key': os.environ.get('MODELSCOPE_API_KEY', '')
    }


def extract_cover_keywords(article_path: str) -> str:
    """
    从文章内容中提取封面关键词（4-6字）

    简单策略：读取文章标题所在行，提取核心概念词
    """
    try:
        with open(article_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 找第一段有意义的文字（通常包含核心主题）
        for line in lines:
            if len(line.strip()) > 20:
                text = line.strip()

                # 匹配常见主题词
                import re
                words = re.findall(r'[\u4e00-\u9fff]{2,4}', text)

                # 核心主题词库
                topic_words = [
                    # AI/技术
                    'AI', '人工智能', '大模型', 'LLM', 'ChatGPT', 'Transformer', '注意力',
                    '智能', '硬件', '机器人', '芯片', '算力', '模型', '算法', '数据',
                    # 应用
                    '教育', '儿童', '玩具', '学习', '医疗', '办公', '创作', '设计',
                    # 行业
                    '深圳', '创业', '产品', '市场', '商业', '产业', '供应链', '出海',
                    # 概念
                    '趋势', '洞察', '思考', '复盘', '总结', '分享', '经验', '方法论',
                ]

                matched = []
                for tw in topic_words:
                    if tw in text:
                        matched.append(tw)

                if matched:
                    # 返回第一个匹配的主题词
                    kw = matched[0]
                    # 如果是英文，尝试加中文
                    if len(kw) <= 3 and 'AI' in kw or 'LLM' in kw:
                        return kw
                    return kw[:6] if len(kw) > 6 else kw

                # 如果没匹配，返回第一个2-4字词
                if words:
                    return words[0][:6]

                break

        return "科技"
    except Exception as e:
        return "科技"


def build_prompt(style_name: str, description: str, styles: Dict, aspect_ratio: str = '16:9') -> str:
    """
    构建完整的生图提示词

    最终提示词 = 前缀(prompt) + 画面描述(description) + 后缀(suffix) + 比例说明
    """
    if style_name not in styles:
        available_list = list(styles.keys())[:10]  # 只显示前10个
        raise ValueError(
            f"未找到匹配的风格: '{style_name}'\n\n"
            f"可用风格（共 {len(styles)} 种）:\n"
            + '\n'.join(f"  {i+1}. {styles[s]['name']} ({s})" for i, s in enumerate(available_list))
            + f"\n  ... 等 {len(styles)} 种风格"
        )

    style = styles[style_name]

    # 根据比例生成构图说明
    aspect_instructions = {
        "16:9": "超宽横向构图，画面宽度是高度的约两倍，电影级宽屏比例。",
        "9:16": "竖版构图，画面高度是宽度的约两倍，适合手机屏幕。",
        "1:1": "正方形构图，宽高相等。",
        "4:3": "横向构图，经典4:3比例。",
        "3:4": "竖版构图，3:4比例。",
        "2.35:1": "超宽横幅，电影宽银幕比例。",
        "5:2": "超宽横幅，5:2比例，适合Banner。",
    }
    aspect_hint = aspect_instructions.get(aspect_ratio, "")

    return f"{style['prompt']}\n\n{description}\n\n{style['suffix']}\n\n{aspect_hint}"


def merge_defaults(item: Dict, config_defaults: Dict, template_defaults: Dict) -> Dict:
    """
    合并默认值

    优先级: 单项配置 > config.defaults > template.defaults
    """
    merged = {}

    # 先应用 template 默认值
    merged.update(template_defaults)

    # 再应用 config 默认值
    merged.update(config_defaults)

    # 最后应用单项配置
    merged.update(item)

    return merged


def get_aspect_ratio_size(aspect_ratio: str) -> Tuple[int, int]:
    """
    根据比例获取尺寸

    即梦 API 支持的标准比例：
    - 1:1 (1024x1024) - 方形
    - 16:9 (1280x720) - 横版
    - 9:16 (720x1280) - 竖版
    - 4:3 (1024x768) - 横向
    - 3:4 (768x1024) - 竖向
    - 2.35:1 (1280x544) - 超宽横版

    不支持的比例会自动 fallback 到 16:9
    """
    # 标准尺寸映射（即梦 API 支持的尺寸）
    standard_sizes = {
        "1:1": (1024, 1024),
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "4:3": (1024, 768),
        "3:4": (768, 1024),
        "2.35:1": (1280, 544),
    }

    if aspect_ratio not in standard_sizes:
        # 不支持的比例，fallback 到 16:9
        import warnings
        warnings.warn(f"即梦 API 不支持比例 '{aspect_ratio}'，已自动使用 16:9")
        return (1280, 720)

    return standard_sizes[aspect_ratio]


def get_jimeng_ratio(aspect_ratio: str) -> str:
    """Map local aspect ratio names to the ratio values accepted by Jimeng."""
    supported = {"1:1", "16:9", "9:16", "4:3", "3:4", "2.35:1"}
    if aspect_ratio in supported:
        return aspect_ratio
    import warnings
    warnings.warn(f"即梦 API 不支持比例 '{aspect_ratio}'，已自动使用 16:9")
    return "16:9"


def call_jimeng_api(
    prompt: str,
    aspect_ratio: str = '16:9',
    max_retries: int = 3
) -> str:
    """
    直接调用即梦 API 生成图片（通过本地 Docker 代理）

    Args:
        prompt: 完整的提示词
        aspect_ratio: 图片比例
        max_retries: 最大重试次数

    Returns:
        图片 URL
    """
    credentials = get_api_credentials()
    session_id = credentials['jimeng_session_id']
    api_key = credentials.get('jimeng_api_key', '')
    api_url = credentials['jimeng_api_url'].rstrip('/')
    model = credentials['jimeng_model']

    if not api_key and not session_id:
        raise ValueError("未设置 jimeng_api_key 或 jimeng_session_id，请检查 ~/.claude/skills/shared-lib/config.json")

    url = f"{api_url}/v1/images/generations"
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    else:
        headers['Authorization'] = f'Bearer {session_id}'
    data = {
        'model': model,
        'prompt': prompt,
        'negative_prompt': '低质量，模糊，变形，多余的文字，水印，杂乱，中文字符，中文标签，中文标注，中文标语，字母，数字，符号，文本框，标签，云文字，混合文字，乱码文字，彩色文字，文字覆盖层，字幕，说明文字，标题文字，any text, any words, any letters, any numbers, any Chinese characters, any symbols, watermarks, logos, labels',
        'ratio': get_jimeng_ratio(aspect_ratio),
        'resolution': '1k',
        'sample_strength': 0.7,
        'n': 1
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=data, timeout=120)
            response.raise_for_status()
            result = response.json()

            if 'data' not in result or not result['data']:
                raise Exception(f"API返回格式错误: {json.dumps(result, ensure_ascii=False)[:200]}")

            return result['data'][0]['url']
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            else:
                raise Exception(f"即梦API失败: {str(e)}")


def call_zimage_api(
    prompt: str,
    aspect_ratio: str = '16:9',
    max_retries: int = 3
) -> str:
    """
    调用通义 Z-Image API 生成图片

    Args:
        prompt: 完整的提示词
        aspect_ratio: 图片比例
        max_retries: 最大重试次数

    Returns:
        图片 URL
    """
    credentials = get_api_credentials()
    api_key = credentials['modelscope_api_key']

    if not api_key:
        raise ValueError("未设置 modelscope_api_key，请检查 ~/.claude/skills/shared-lib/config.json")

    width, height = get_aspect_ratio_size(aspect_ratio)
    size = f"{width}x{height}"

    base_url = 'https://api-inference.modelscope.cn/'
    model = 'Tongyi-MAI/Z-Image-Turbo'

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-ModelScope-Async-Mode": "true"
    }

    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "negative_prompt": "低质量，模糊，变形，多余的文字，水印，杂乱，中文字符，中文标签，中文标注，中文标语，字母，数字，符号，文本框，标签，云文字，混合文字，乱码文字，彩色文字，文字覆盖层，字幕，说明文字，标题文字，any text, any words, any letters, any numbers, any Chinese characters, any symbols, watermarks, logos, labels"
    }

    for attempt in range(max_retries):
        try:
            # 提交任务
            response = requests.post(
                f"{base_url}v1/images/generations",
                headers=headers,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                timeout=60
            )

            if response.status_code == 429:
                wait_time = 2 ** attempt * 10
                safe_print(f"  ⚠️  Z-Image 限流，等待 {wait_time} 秒...")
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            task_id = response.json().get("task_id")

            if not task_id:
                raise Exception("Z-Image API 返回缺少 task_id")

            # 轮询任务状态
            poll_headers = {
                "Authorization": f"Bearer {api_key}",
                "X-ModelScope-Task-Type": "image_generation"
            }

            while True:
                result = requests.get(
                    f"{base_url}v1/tasks/{task_id}",
                    headers=poll_headers,
                    timeout=30
                )
                result.raise_for_status()
                data = result.json()
                status = data.get("task_status")

                if status == "SUCCEED":
                    return data["output_images"][0]
                elif status == "FAILED":
                    raise Exception(f"Z-Image 生成失败: {data.get('error', '未知错误')}")
                else:
                    time.sleep(5)

        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            else:
                raise Exception(f"Z-Image API 失败: {str(e)}")


def save_image(url: str, output_path: str):
    """下载并保存图片"""
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    with open(output_path, 'wb') as f:
        f.write(response.content)


def generate_single_image(
    item: Dict,
    styles: Dict,
    output_dir: Path,
    index: int,
    is_cover: bool = False,
    provider: str = 'jimeng'
) -> Dict:
    """
    生成单张图片

    Args:
        item: 图片配置（包含 description, style, aspect_ratio 等）
        styles: 风格模板（本地 styles.json）
        output_dir: 输出目录
        index: 序号（用于文件名）
        is_cover: 是否是封面
        provider: API 提供商（jimeng 或 z-image）

    Returns:
        结果字典 {status, path, error?}
    """
    retry_count = item.get('retry_count', 2)
    style_name = item.get('style', 'minimalist')
    description = item.get('description', item.get('visual_description', ''))
    aspect_ratio = item.get('aspect_ratio', '16:9')
    section_title = item.get('section', item.get('h2_title', ''))  # 兼容两种字段名

    # 构建提示词（使用本地 styles.json + 比例说明）
    try:
        prompt = build_prompt(style_name, description, styles, aspect_ratio)
    except ValueError as e:
        return {
            "status": "error",
            "index": index,
            "error": str(e)
        }

    # 生成文件名：优先使用配置文件中定义的 filename
    if 'filename' in item:
        filename = item['filename']
    elif is_cover:
        filename = item.get('filename', f"{index:02d}--{style_name}.png")
    else:
        # 后备方案：自动生成文件名
        filename = f"{index:02d}--{style_name}.png"

    output_path = output_dir / filename

    # 带重试的生成
    last_error = None
    for attempt in range(retry_count + 1):
        try:
            provider_label = "即梦" if provider == 'jimeng' else "Z-Image"
            safe_print(f"  🎨 [{index:02d}] {provider_label} 生成中... (尝试 {attempt + 1}/{retry_count + 1})")

            # 根据 provider 调用不同的 API
            if provider == 'z-image':
                image_url = call_zimage_api(
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    max_retries=1
                )
            else:
                # 默认使用即梦
                image_url = call_jimeng_api(
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    max_retries=1
                )

            # 保存图片
            output_dir.mkdir(parents=True, exist_ok=True)
            save_image(image_url, str(output_path))

            safe_print(f"  ✅ [{index:02d}] 完成: {filename}")

            return {
                "status": "success",
                "index": index,
                "path": str(output_path),
                "filename": filename,
                "provider": provider
            }

        except Exception as e:
            last_error = str(e)
            if attempt < retry_count:
                safe_print(f"  ⚠️  [{index:02d}] 失败，等待重试: {str(e)[:50]}")
                time.sleep(2)
            else:
                safe_print(f"  ❌ [{index:02d}] 最终失败: {str(e)[:50]}")

    return {
        "status": "error",
        "index": index,
        "error": last_error
    }


def generate_images(config: Dict, styles: Dict, templates: Dict, providers: Dict, workers: int = 3, dry_run: bool = False) -> Dict:
    """
    批量生成图片

    Args:
        config: 任务配置（visual_config.json 内容）
        styles: 风格模板
        templates: 场景模板
        providers: API 配置
        workers: 并发线程数
        dry_run: 是否只打印不执行

    Returns:
        生成结果
    """
    start_time = time.time()

    # 获取模板默认值
    template_name = config.get('template', 'article')
    template = templates.get(template_name, {})
    template_defaults = template.get('defaults', {})

    # 获取 config 级别默认值
    config_defaults = config.get('defaults', {})

    # 输出目录
    output_dir = Path(config.get('output_dir', '.'))

    # 获取 provider
    provider_name = config_defaults.get('provider', providers.get('default', 'jimeng'))

    # 获取风格
    default_style = config_defaults.get('style', 'minimalist')

    print(f"\n📋 任务配置:")
    print(f"   模板: {template_name}")
    print(f"   风格: {default_style} ({styles.get(default_style, {}).get('name', '未知')})")
    print(f"   输出: {output_dir}")
    print(f"   API: {provider_name}")
    print(f"   并发: {workers} 线程")
    print(f"   可用风格: {len(styles)} 种")

    if dry_run:
        print(f"\n🔍 Dry Run 模式，不会实际生成图片\n")

    results = {
        "cover": None,
        "illustrations": [],
        "summary": {
            "total": 0,
            "success": 0,
            "failed": 0,
            "duration": 0
        }
    }

    tasks = []

    # 封面任务
    cover_config = config.get('cover', {})
    if cover_config.get('enabled', False):
        merged_cover = merge_defaults(cover_config, config_defaults, template_defaults)

        # 只有当 description 完全为空时才自动提取关键词
        article_path = config.get('source', '')
        current_desc = merged_cover.get('description', '')

        if not current_desc or current_desc.strip() == '':
            # 从文章提取关键词（仅作为后备方案）
            keywords = extract_cover_keywords(article_path)
            # 生成简洁的封面描述
            merged_cover['description'] = f"{keywords}，科技感场景，简约大气"
            safe_print(f"  📝 自动提取封面关键词: {keywords}")

        tasks.append(('cover', 0, merged_cover))

    # 配图任务
    for item in config.get('illustrations', []):
        index = item.get('index', len(tasks))
        merged_item = merge_defaults(item, config_defaults, template_defaults)
        tasks.append(('illustration', index, merged_item))

    results["summary"]["total"] = len(tasks)

    if dry_run:
        print(f"📝 待生成任务: {len(tasks)} 张图片")
        for task_type, index, item in tasks:
            style = item.get('style', default_style)
            style_info = styles.get(style, {})
            print(f"   [{index:02d}] {task_type}: {item.get('h2_title', '封面')[:30]}")
            print(f"        风格: {style} ({style_info.get('name', '未知')}), 比例: {item.get('aspect_ratio')}")
        return results

    print(f"\n🚀 开始生成 {len(tasks)} 张图片...\n")

    # 多线程执行
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}

        for task_type, index, item in tasks:
            is_cover = (task_type == 'cover')
            future = executor.submit(
                generate_single_image,
                item,
                styles,
                output_dir,
                index,
                is_cover,
                provider_name
            )
            futures[future] = (task_type, index)

        # 收集结果
        for future in as_completed(futures):
            task_type, index = futures[future]
            result = future.result()

            if task_type == 'cover':
                results["cover"] = result
            else:
                results["illustrations"].append(result)

            if result["status"] == "success":
                results["summary"]["success"] += 1
            else:
                results["summary"]["failed"] += 1

    # 按 index 排序
    results["illustrations"].sort(key=lambda x: x.get("index", 0))

    # 计算耗时
    duration = time.time() - start_time
    results["summary"]["duration"] = round(duration, 1)

    # 打印总结
    print(f"\n{'='*50}")
    print(f"✅ 生成完成！")
    print(f"   成功: {results['summary']['success']}/{results['summary']['total']}")
    print(f"   失败: {results['summary']['failed']}")
    print(f"   耗时: {results['summary']['duration']}秒")
    print(f"   输出: {output_dir}")
    print(f"{'='*50}\n")

    return results


def insert_images_to_markdown(
    markdown_path: Path,
    results: Dict,
    config: Dict
) -> bool:
    """
    将生成的图片插入到 Markdown 文件

    Args:
        markdown_path: Markdown 文件路径
        results: 生成结果
        config: 任务配置

    Returns:
        是否成功
    """
    if not markdown_path.exists():
        print(f"⚠️  Markdown 文件不存在: {markdown_path}")
        return False

    # 读取文件
    content = markdown_path.read_text(encoding='utf-8')
    lines = content.split('\n')

    # 获取输出目录的相对路径
    output_dir = Path(config.get('output_dir', '.'))

    # 计算相对路径
    try:
        relative_dir = output_dir.relative_to(markdown_path.parent)
    except ValueError:
        # 如果不在同一目录树下，使用绝对路径
        relative_dir = output_dir

    # 创建 h2_title 到结果的映射
    title_to_result = {}
    for result in results.get('illustrations', []):
        if result.get('status') == 'success':
            # 从配置中找到对应的 h2_title
            for item in config.get('illustrations', []):
                if item.get('index') == result.get('index'):
                    title = item.get('h2_title', '')
                    title_to_result[title] = result
                    break

    # 在每个 H2 标题下插入图片
    new_lines = []
    i = 0
    inserted_count = 0

    while i < len(lines):
        line = lines[i]
        new_lines.append(line)

        # 用于匹配的标题文本
        h2_title = None

        # 检查是否是 H2 标题
        if line.startswith('## '):
            # 提取标题文本
            h2_title = line[3:].strip()
        # 检查是否是加粗文本作为标题（如 **新的瓶颈正在形成**）
        elif line.strip().startswith('**') and line.strip().endswith('**') and len(line.strip()) > 4:
            # 完整的加粗行，包括星号
            h2_title = line.strip()

        # 查找匹配的结果
        if h2_title:
            result = title_to_result.get(h2_title)
            if result:
                filename = result.get('filename', '')
                # Obsidian 会自动搜索 vault，只需文件名即可
                img_path = filename

                # 提取纯文本标题（去掉星号）用于图片说明
                clean_title = h2_title.strip('*').strip() if h2_title.startswith('**') else h2_title

                # 插入空行和图片
                new_lines.append('')
                new_lines.append(f'![{clean_title}]({img_path})')
                new_lines.append('')
                inserted_count += 1

        i += 1

    # 写回文件
    markdown_path.write_text('\n'.join(new_lines), encoding='utf-8')

    print(f"✅ 已插入 {inserted_count} 张图片到 {markdown_path.name}")
    return True


def main():
    parser = argparse.ArgumentParser(description='统一配图生成器')
    parser.add_argument('config', help='visual_config.json 配置文件路径')
    parser.add_argument('--workers', '-w', type=int, default=3, help='并发线程数（默认 3）')
    parser.add_argument('--dry-run', '-n', action='store_true', help='只打印不执行')
    parser.add_argument('--no-insert', action='store_true', help='不自动插入到 Markdown')
    parser.add_argument('--output', '-o', help='输出结果到 JSON 文件')

    args = parser.parse_args()

    try:
        # 加载配置
        print("📂 加载配置...")
        config = load_config(args.config)
        styles = load_styles()
        templates = load_templates()
        providers = load_providers()

        print(f"   ✅ 已加载 {len(styles)} 种风格")

        # 生成图片
        results = generate_images(
            config=config,
            styles=styles,
            templates=templates,
            providers=providers,
            workers=args.workers,
            dry_run=args.dry_run
        )

        # 插入到 Markdown
        if not args.dry_run and not args.no_insert:
            source = config.get('source')
            if source:
                markdown_path = Path(source)
                insert_images_to_markdown(markdown_path, results, config)

        # 输出结果
        if args.output:
            output_path = Path(args.output)
            output_path.write_text(
                json.dumps(results, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            print(f"📄 结果已保存到: {args.output}")

        # 返回结果
        if results["summary"]["failed"] > 0:
            sys.exit(1)

    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
