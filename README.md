每日科技/科学日报自动化部署说明
--------------------------------

功能概览
- 每天抓取一组 RSS/Atom 源与 arXiv，生成 20 条最新科技/科学新闻（中英双语标题 + 链接 + 来源 + 发布时间），通过邮件发送到指定收件人。
- 使用 GitHub Actions 定时触发（已设为 Asia/Shanghai 09:00 -> cron: 0 1 * * *）。

部署步骤
1. 在你的 GitHub 仓库（owner/repo）中添加本项目文件（digest.py 与 .github/workflows/digest.yml）。
2. 在仓库 Settings -> Secrets -> Actions 中添加以下 Secrets：
   - RECIPIENT_EMAIL: 收件人（例如 cdzwb1017@sina.com）
   - SENDER_EMAIL: 发件人邮箱（例如 no-reply@yourdomain.com）
   - 推选发送方式之一：
     - SENDGRID_API_KEY: 如果使用 SendGrid（推荐）
     - 或者 SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS: 使用 SMTP（如 Gmail SMTP）
   - OPENAI_API_KEY (可选): 如果想要自动把英文标题翻译成中文（或做更智能的摘要）
3. 手动触发 workflow（Actions -> 选择 Daily Science & Tech Digest -> Run workflow）来立即发送第一期，或者等到下一个计划时间（每天 09:00 Asia/Shanghai）。
4. 如需添加/删除 RSS 源，请编辑 digest.py 中的 FEEDS 列表。

脚本
一个可在本地仓库根目录运行的脚本：它会创建一个分支、替换 digest.py 和 .github/workflows/digest.yml 为我之前准备的修复版本、提交更改，并在上层目录输出两种 patch 格式：1) mbox（git format-patch，可用 git am 应用）和 2) unified diff（可用 git apply 应用）。请在仓库根目录运行此脚本。

脚本（复制到本地仓库根目录，保存为 make_patch.sh，然后运行：bash make_patch.sh）

bash


#!/usr/bin/env bash
set -euo pipefail

# 在仓库根目录运行
BRANCH="ci/add-smoke-test"
PATCH_DIR=".."
MBX="${PATCH_DIR}/daily-brief-ci-smoke-test.mbox"
DIFF="${PATCH_DIR}/daily-brief-ci-smoke-test.diff"

echo "Creating branch ${BRANCH}..."
git checkout -b "${BRANCH}"

# 备份原文件（若存在）
[ -f digest.py ] && cp digest.py digest.py.bak || true
[ -f .github/workflows/digest.yml ] && mkdir -p .github/workflows && cp .github/workflows/digest.yml .github/workflows/digest.yml.bak || true

echo "Writing new digest.py..."
cat > digest.py <<'PYEOF'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日科技/科学日报脚本（自动化）
功能：
- 从多个 RSS/Atom 源抓取新闻（包含 arXiv）
- 去重、按发布时间排序，取最新 N 条（默认 20）
- 生成中英双语邮件（标题原文 + 可选的中文翻译）
- 支持通过 SendGrid API 或 SMTP 发送
- 可选：使用 OpenAI API 做标题翻译为中文（需设置 OPENAI_API_KEY）
环境变量：
- RECIPIENT_EMAIL (必需)
- SENDER_EMAIL (必需)
- MAX_ITEMS (可选，默认 20)
- SENDGRID_API_KEY OR SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS
- OPENAI_API_KEY (可选，用于中英翻译)
"""

import os
import feedparser
import requests
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

# 推荐的 RSS 源（可增删）
FEEDS = [
    "https://www.nature.com/nature.rss",
    "https://www.sciencemag.org/rss/news_current.xml",
    "https://export.arxiv.org/rss/cs",
    "https://export.arxiv.org/rss/astro-ph",
    "https://export.arxiv.org/rss/q-bio",
    "https://feeds.feedburner.com/TechCrunch/",
    "https://www.theverge.com/rss/index.xml",
    "https://www.wired.com/feed/rss",
    "https://www.sciencedaily.com/rss/top/science.xml",
]

MAX_ITEMS = int(os.getenv("MAX_ITEMS", "20"))


def parse_date(entry):
    # 优先使用 feedparser 提供的结构化时间
    for pkey in ("published_parsed", "updated_parsed"):
        t = entry.get(pkey)
        if t:
            try:
                return datetime(*t[:6])
            except Exception:
                pass
    # 回退到解析字符串（保守处理）
    for f in ("published", "updated", "pubDate"):
        val = entry.get(f)
        if val:
            try:
                parsed = feedparser._parse_date(val)
                if parsed:
                    return datetime(*parsed[:6])
            except Exception:
                pass
    return None


def fetch_items():
    items = {}
    for url in FEEDS:
        try:
            d = feedparser.parse(url)
        except Exception:
            # 单个源错误不影响整体
            continue
        for e in getattr(d, "entries", []):
            link = e.get("link") or ""
            title = (e.get("title") or "").strip()
            source = (d.feed.get("title") if hasattr(d, "feed") and getattr(d, "feed", None) else url) or url
            published_dt = parse_date(e)
            published = published_dt.isoformat() if published_dt else (e.get("published") or e.get("updated") or "")
            key = link or title
            items[key] = {
                "title": title,
                "link": link,
                "summary": e.get("summary", "") or e.get("description", ""),
                "published": published,
                "published_dt": published_dt or datetime.min,
                "source": source
            }
    sorted_items = sorted(items.values(), key=lambda x: x["published_dt"], reverse=True)
    return sorted_items[:MAX_ITEMS]


def translate_to_chinese(text):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        prompt = [
            {"role": "system", "content": "You are a concise translator that translates English news titles into simplified Chinese. Return only the Chinese translation, no extra commentary."},
            {"role": "user", "content": text}
        ]
        data = {
            "model": "gpt-4o-mini",
            "messages": prompt,
            "temperature": 0.2,
            "max_tokens": 128
        }
        r = requests.post(url, headers=headers, json=data, timeout=15)
        r.raise_for_status()
        resp = r.json()
        return resp["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def make_html(items):
    html = []
    html.append("<html><body>")
    html.append(f"<h2>每日科技/科学要闻（{len(items)} 条） — Daily Science & Tech Highlights</h2>")
    html.append("<ol>")
    for it in items:
        title_en = it["title"]
        title_cn = translate_to_chinese(title_en)
        source = it["source"]
        published = it["published"] or ""
        link = it["link"] or ""
        html.append("<li>")
        html.append(f"<div><strong>EN:</strong> <a href='{link}' target='_blank'>{escape_html(title_en)}</a></div>")
        if title_cn:
            html.append(f"<div><strong>中:</strong> {escape_html(title_cn)}</div>")
        else:
            html.append(f"<div><strong>中:</strong> （未启用翻译或翻译失败）</div>")
        html.append(f"<div style='color:#666;font-size:0.9em;'>来源: {escape_html(source)} | 发布时间: {escape_html(published)}</div>")
        html.append("</li><br>")
    html.append("</ol>")
    html.append("<hr><div style='font-size:0.85em;color:#888'>由自动化脚本生成。若需更详细摘要或按主题分类，请调整脚本。</div>")
    html.append("</body></html>")
    return "\n".join(html)


def escape_html(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;") if s else "")


def send_via_sendgrid(html, subject="每日科技/科学要闻 Daily Science & Tech Digest"):
    key = os.getenv("SENDGRID_API_KEY")
    if not key:
        raise RuntimeError("SENDGRID_API_KEY not set")
    payload = {
        "personalizations": [{"to": [{"email": os.getenv("RECIPIENT_EMAIL") or ""}]}],
        "from": {"email": os.getenv("SENDER_EMAIL") or ""},
        "subject": subject,
        "content": [{"type": "text/html", "value": html}]
    }
    r = requests.post("https://api.sendgrid.com/v3/mail/send",
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json=payload, timeout=30)
    r.raise_for_status()


def send_via_smtp(html, subject="每日科技/科学要闻 Daily Science & Tech Digest"):
    host = os.getenv("SMTP_HOST")
    if not host:
        raise RuntimeError("SMTP_HOST not set")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pwd = os.getenv("SMTP_PASS")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = os.getenv("SENDER_EMAIL")
    msg["To"] = os.getenv("RECIPIENT_EMAIL")
    msg.attach(MIMEText(html, "html"))
    s = smtplib.SMTP(host, port, timeout=30)
    s.starttls()
    if user and pwd:
        s.login(user, pwd)
    s.sendmail(msg["From"], [msg["To"]], msg.as_string())
    s.quit()


if __name__ == "__main__":
    items = fetch_items()
    html = make_html(items)
    if os.getenv("SENDGRID_API_KEY"):
        try:
            send_via_sendgrid(html)
            print("Sent via SendGrid. Items:", len(items))
        except Exception as e:
            print("SendGrid send failed:", e)
    elif os.getenv("SMTP_HOST"):
        try:
            send_via_smtp(html)
            print("Sent via SMTP. Items:", len(items))
        except Exception as e:
            print("SMTP send failed:", e)
    else:
        print("No mail sending configuration found. Set SENDGRID_API_KEY or SMTP_HOST and SMTP_* secrets.")
PYEOF

echo "Writing .github/workflows/digest.yml..."
mkdir -p .github/workflows
cat > .github/workflows/digest.yml <<'YAML'
name: Daily Science & Tech Digest

on:
  push:
    branches: [main]
  schedule:
    # 每天 UTC 01:00 -> Asia/Shanghai 09:00
    - cron: "0 1 * * *"
  workflow_dispatch:

jobs:
  run-and-send:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install feedparser requests pyflakes

      - name: Lint: pyflakes (syntax/static check)
        if: github.event_name == 'push'
        run: |
          echo "Running pyflakes on digest.py..."
          python -m pyflakes digest.py

      - name: Smoke test: fetch one feed
        if: github.event_name == 'push'
        run: |
          echo "Running smoke test: fetch a single feed via feedparser"
          python - <<'PY'
import feedparser, sys
url = "https://export.arxiv.org/rss/cs"
d = feedparser.parse(url)
entries = getattr(d, 'entries', None)
if not entries:
    print('No entries fetched from', url)
    sys.exit(1)
print('Fetched', len(entries), 'entries from', url)
PY

      - name: Run digest
        env:
          RECIPIENT_EMAIL: ${{ secrets.RECIPIENT_EMAIL }}
          SENDER_EMAIL: ${{ secrets.SENDER_EMAIL }}
          SENDGRID_API_KEY: ${{ secrets.SENDGRID_API_KEY }}
          SMTP_HOST: ${{ secrets.SMTP_HOST }}
          SMTP_PORT: ${{ secrets.SMTP_PORT }}
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_PASS: ${{ secrets.SMTP_PASS }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          MAX_ITEMS: "20"
        run: python3 digest.py
YAML

echo "Staging files..."
git add digest.py .github/workflows/digest.yml

echo "Committing..."
git commit -m "ci: add pyflakes lint and feed smoke test before sending; fix digest.py"

echo "Generating patches..."
git format-patch -1 HEAD --stdout > "${MBX}"
git diff HEAD~1 HEAD > "${DIFF}"

echo "Done."
echo "Patch files created:"
echo " - mbox (apply with: git am ${MBX}): ${MBX}"
echo " - unified diff (apply with: git apply ${DIFF}): ${DIFF}"
echo ""
echo "To undo local changes (if you wish):"
echo "  git checkout -- digest.py"
echo "  git checkout -- .github/workflows/digest.yml"
echo "  git branch -D ${BRANCH}"


如何使用生成的 patch

mbox（git format-patch）：在目标仓库上执行 git am path/to/daily-brief-ci-smoke-test.mbox
unified diff：在目标仓库上执行 git apply path/to/daily-brief-ci-smoke-test.diff 之后 git add/commit
安全提示与注意

脚本会备份原文件到 digest.py.bak 与 .github/workflows/digest.yml.bak（若存在）。但仍建议先在本地创建分支并确认改动内容再推送到远程。脚本本身就创建了分支 ci/add-smoke-test，并提交更改。
workflow 含对外网络的 smoke test（抓取 arXiv RSS），在公司网络或防火墙环境中可能被限制；如果你的 CI 环境不能访问外网，请修改 smoke test 改为访问一个内部可访问的 URL 或改用本地离线检查。

安全与注意事项
- 不要把 API Key / 密码直接写入仓库代码；请务必使用 GitHub Secrets。
- 若使用 Gmail SMTP，需要在发送账户上启用应用专用密码或允许 SMTP 登录。
