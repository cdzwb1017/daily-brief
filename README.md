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

安全与注意事项
- 不要把 API Key / 密码直接写入仓库代码；请务必使用 GitHub Secrets。
- 若使用 Gmail SMTP，需要在发送账户上启用应用专用密码或允许 SMTP 登录。
