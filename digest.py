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
