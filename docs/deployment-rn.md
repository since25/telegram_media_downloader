# RN 部署约束流程

RN 磁盘空间较小，生产部署只允许使用仓库中的 `scripts/deploy_rn.sh`，或逐项执行与它相同的步骤。脚本运行在 RN 的生产 checkout 中，不负责拉取代码；执行前应先完成代码审查、测试和 fast-forward 更新。

## 发布前

1. 确认目录、分支、提交和服务名：

   ```bash
   cd /root/telegram_media_downloader
   pwd
   git status --short --branch
   git log -1 --oneline
   systemctl status tg-downloader.service --no-pager
   ```

2. 确认当前工作树没有无关修改，确认配置、会话和三个 SQLite 数据库的路径。
3. 确认备份目录中最多有两个 `.bak` 文件或目录；超过两个时先停止发布并轮换。

## 执行部署

停止服务、创建带提交号的备份、使用 SQLite backup API 复制数据库、验证每个数据库的 `PRAGMA integrity_check`、轮换旧备份、重启服务和检查服务状态：

```bash
TMD_CONFIRM_DEPLOY=YES ./scripts/deploy_rn.sh
```

脚本只打印提交、数据库完整性和服务检查结果，不打印配置内容、Token 或会话内容。备份目录命名为 `*.bak`，始终保留最新两个；新备份未完成校验时不会删除旧备份。脚本失败时会尝试恢复启动服务，但仍需人工检查 `systemctl status`。

## 发布后

```bash
systemctl is-active tg-downloader.service
journalctl -u tg-downloader.service --since "10 minutes ago" --no-pager
find backups -mindepth 1 -maxdepth 1 -name '*.bak' -print
```

检查启动日志没有认证、数据库、依赖或 traceback 错误；确认 Web 登录和一个小型下载任务。检查 `temp/`、`save_path` 磁盘占用和启动文件对账日志。发现备份超过两个、服务未 active、数据库校验失败或文件清理异常时，停止继续发布并保留现场。

## 回滚

停止服务后选择一个已校验的 `.bak` 目录，恢复代码到其 `pre-deploy-commit.txt` 记录的提交，并只恢复需要回滚的配置、会话或数据库。恢复后重新启动服务并执行发布后检查；不得在服务运行时覆盖 SQLite、配置或会话。
