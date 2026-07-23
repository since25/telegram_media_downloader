
<h1 align="center">电报资源下载</h1>

<p align="center">
<a href="https://github.com/tangyoha/telegram_media_downloader/actions"><img alt="Unittest" src="https://github.com/tangyoha/telegram_media_downloader/workflows/Unittest/badge.svg"></a>
<a href="https://codecov.io/gh/tangyoha/telegram_media_downloader"><img alt="Coverage Status" src="https://codecov.io/gh/tangyoha/telegram_media_downloader/branch/master/graph/badge.svg"></a>
<a href="https://github.com/tangyoha/telegram_media_downloader/blob/master/LICENSE"><img alt="License: MIT" src="https://black.readthedocs.io/en/stable/_static/license.svg"></a>
<a href="https://github.com/python/black"><img alt="Code style: black" src="https://img.shields.io/badge/code%20style-black-000000.svg"></a>
<a href="https://github.com/tangyoha/telegram_media_downloader/releases">
<img alt="Code style: black" src="https://img.shields.io/github/v/release/tangyoha/telegram_media_downloader?display_name=tag">
</a>
</p>

<h3 align="center">
  <a href="./README.md">English</a><span> · </span>
  <a href="https://github.com/tangyoha/telegram_media_downloader/discussions/categories/ideas">新功能请求</a>
  <span> · </span>
  <a href="https://github.com/tangyoha/telegram_media_downloader/issues">报告bug</a>
  <span> · </span>
  帮助: <a href="https://github.com/tangyoha/telegram_media_downloader/discussions">讨论</a>
  <span> & </span>
  <a href="https://t.me/TeegramMediaDownload">电报讨论群</a>
</h3>

## 概述

> 支持两种默认运行

* 机器人运行，从机器人下发命令`下载`或者`转发`

* 作为一个一次性的下载工具下载

* 索引关键词下载：在跨频道资源包索引中匹配标题，并自动下载命中的包

### 索引关键词下载

关键词监控组保存在数据库中，只通过 Web“关键词监控”页面管理，不从 `config.yaml` 读取。每个组可配置必要关键词、命中关键词和黑名单关键词，每行一个。保存监控组或完成全量、增量、补扫后，系统会匹配跨频道当前索引中的稳定资源包；不会监听 Telegram 实时消息、回扫频道，也不会发送 Discord 通知。

- 关键词采用 Unicode 规范化后的不区分大小写子串匹配。
- 必要关键词必须全部命中；命中关键词至少命中一个；任一黑名单关键词命中即排除。
- 仅下载状态为 `never` 的稳定包。
- 已成功下载或 `outdated` 的包不会自动重复下载，但仍可在“资源包”页面手动确认下载。
- 同一资源包同时命中多个监控组时只创建一个下载批次，各监控组分别保存实际命中词和下载进度历史。

### 界面

#### 网页

> 运行后打开浏览器访问`localhost:5000`
> 如果是远程机器需要配置web_host: 0.0.0.0

网页端 Tasks 页支持提交 Telegram 私密消息资源包链接和评论链接；提交后先扫描预览，确认后才开始下载。也可以选择 Prescan 模式扫描多个连续资源包、勾选需要下载的包，再串行下载。接口和使用边界见 [`docs/web-control-console.md`](docs/web-control-console.md)。

#### 资源包与频道

“资源包”标签是跨频道聚合入口，可直接搜索、筛选和选择多个频道的资源包，来源频道是每个包的关联元数据和可选多选筛选条件。“频道”标签只负责提交频道链接、查看扫描状态和维护索引。重复提交同一会话不会重复扫描一份数据。

- 首次全量扫描固定每批 50 个消息 ID，批间等待 4-6 秒。扫描按 ID 范围而不是可见消息条数计费，删除或不可见缺口不会减少批次。以 15,000 个 ID 为例，共 300 批、299 次批间等待，单纯节流理论约 19 分 56 秒至 29 分 54 秒（约 20-30 分钟），这不是完成承诺；API 网络耗时、FloodWait、临时重试、下载自动让行和手动暂停都会继续延长总时长。
- 扫描在 Telegram 下载排队或进行时自动让行，下载空闲后继续；也可在批次边界手动暂停、继续或停止。
- 扫描期间可浏览稳定包。首次全量到达 `ready` 或 `partial` 后，才能提交下载。
- 可按来源频道、标题、发布时间、媒体数量、已知总大小和下载状态筛选；“全选筛选结果”跨分页和频道生效，选择在刷新后保留。
- `partial` 表示已扫描到快照终点但仍有失败区间；远离失败区间的稳定包仍可使用，失败区间通过“补扫”修复。
- 首次全量结束后可手动发起增量扫描。增量和补扫固定每批 50 个消息 ID，批间等待 1-2 秒。
- 已成功下载的包默认禁止重复提交；内容 revision 变化后显示为 `outdated`，重新下载需要明确确认。
- 可在“关键词监控”页面维护多个监控组；保存后立即匹配已扫描索引，之后每次扫描完成也会继续匹配。
- 资源包按创建时间 FIFO 下载。启动前会预约完整已知大小的本地空间，默认始终保留 3GB；未知大小的包不会猜测占用，而是以错误状态结束并保留记录。

完整的页面流程、状态、接口和数据库备份/回滚说明见 [`docs/web-control-console.md`](docs/web-control-console.md)。


<img alt="Code style: black" style="width:100%; high:60%;" src="./screenshot/web_ui.gif"/>

### 机器人

> 需要配置bot_token,具体参考[文档](https://github.com/since25/telegram_media_downloader/wiki/%E5%A6%82%E4%BD%95%E4%BD%BF%E7%94%A8%E6%9C%BA%E5%99%A8%E4%BA%BA%E4%B8%8B%E8%BD%BD)


<img alt="Code style: black" style="width:60%; high:30%; " src="./screenshot/bot.gif"/>

#### 手动添加标签功能

在 bot 交互的批量下载选项中，新增了手动添加标签的功能，允许你为下载的文件添加自定义标签，方便后续管理和分类。

**使用示例：**

1. **批量下载添加标签**：在命令末尾添加标签参数
   ```
   /download https://t.me/channel_name 1 100 电影
   ```

2. **批量下载带过滤器和标签**：先指定过滤器，再添加标签
   ```
   /download https://t.me/channel_name 1 100 media_type == "video" 电影
   ```

3. **评论下载添加标签**：为评论下载添加标签
   ```
   /download https://t.me/channel_name/123?comment= 10 20 评论标签
   ```

4. **多个标签**：可以输入多个标签，用空格分隔
   ```
   /download https://t.me/channel_name 1 100 电影 动作 科幻
   ```

5. **带空格的标签**：标签中可以包含空格
   ```
   /download https://t.me/channel_name 1 100 经典电影 科幻大片
   ```

**标签的作用**：
- 标签会被添加到下载文件的元数据中
- 可以在文件路径中包含标签信息（需在配置中设置）
- 便于后续通过标签搜索和管理下载的文件
- 单条消息下载时，系统会自动从消息文本或caption中提取标签

#### 评论链接媒体下载向导

直接把评论链接发送给 bot：

```text
https://t.me/zhyseseb/422?comment=4978
```

bot 会自动识别原帖和评论起点，扫描该帖评论区，过滤非媒体评论，并在下载前展示：

- 评论扫描数量
- 可下载媒体数量
- 媒体类型统计
- 预计总大小、单文件大小示例、最大文件
- 推荐 C 命名预览
- rclone 上传和上传后删除本地文件状态

确认后才会开始下载。固定使用推荐 C 命名：

```text
频道名/原帖ID-原帖标题/评论ID - 原文件名.ext
```

所有路径和文件名都会先进行非法字符清理；如果标题、caption、作者或原文件名缺失，会使用稳定兜底名称。

#### 私密消息链接连续资源包向导

直接把普通消息链接发送给 bot：

```text
https://t.me/c/1298283297/126711
```

bot 会自动把 `/c/1298283297/126711` 转换为内部 chat_id `-1001298283297` 和起始消息 ID `126711`，然后向后扫描连续媒体资源包。

适合一组连续视频/图片共用同一标题的频道：如果后续媒体没有 caption，会继承最近的资源包标题；如果扫描到新的不同 caption，会把它显示为“下一包起点预览”，但不会纳入本次下载。

确认下载前会展示：

- 本包标题和消息范围
- 可下载媒体数量和类型统计
- 预计总大小、单文件大小示例、最大文件
- 继承 caption 的媒体数量
- 下一包起点预览
- 推荐 C 命名预览
- rclone 上传和上传后删除本地文件状态

确认命名方案后才会开始下载、上传，并按配置删除本地文件。所有路径和文件名同样会进行非法字符清理。

#### 预扫模式批量资源包选择

在 Telegram bot 菜单里点击 `预扫模式`，然后发送起始频道消息链接：

```text
https://t.me/c/1446289027/156439
```

bot 会从这条消息开始慢速向后扫描，识别多个连续资源包，并用按钮分页展示。你可以勾选需要下载的包，再点击 `下载已选`。

预扫模式固定使用推荐 C 命名：

```text
频道名/起始ID-包标题/消息ID - 原文件名.ext
```

扫描会分批请求并在批次之间暂停；如果 Telegram 返回限流等待，bot 会等待后继续。选中多个包时不会同时并发下载，而是按消息顺序一个包一个包串行下载。

### 支持

| 类别         | 支持                                     |
| ------------ | ---------------------------------------- |
| 语言         | `Python 3.7` 及以上                      |
| 下载媒体类型 | 音频、文档、照片、视频、video_note、语音 |
| 索引关键词下载 | 数据库监控组匹配跨频道资源包并自动创建下载批次 |
| 标签功能     | 手动添加标签、多标签支持、标签分类管理   |

### 版本发布计划

* [v2.2.0](https://github.com/since25/telegram_media_downloader/issues/2)

## 安装

对于具有 `make` 可用性的 *nix 操作系统发行版

```sh
git clone https://github.com/since25/telegram_media_downloader.git
cd telegram_media_downloader
cp config.example.yaml config.yaml #按照实际情况修改你的配置文件，具体参考后续文档
python3 -m venv venv #python or python3
source venv/bin/activate
make install
#第一次运行需要前台启动，输入你的电话号码和密码，然后退出(ctrl + c)，配置systemctl服务以后后台运行
```

对于没有内置 `make` 的 Windows

```sh
git clone https://github.com/since25/telegram_media_downloader.git
cd telegram_media_downloader
pip3 install -r requirements.txt
```
## Docker容器
> 更详细安装教程请查看wiki

确保安装了 **docker** 和 **docker-compose**
```sh
docker pull tangyoha/telegram_media_downloader:latest
mkdir -p ~/app && mkdir -p ~/app/log/ && cd ~/app
wget https://raw.githubusercontent.com/since25/telegram_media_downloader/master/docker-compose.yaml -O docker-compose.yaml
wget https://raw.githubusercontent.com/since25/telegram_media_downloader/master/config.example.yaml -O config.example.yaml
wget https://raw.githubusercontent.com/since25/telegram_media_downloader/master/data.yaml -O data.yaml
# 复制配置文件示例为实际配置文件
cp config.example.yaml config.yaml
# 编辑配置文件
vi config.yaml

# 第一次需要前台启动
# 输入你的电话号码和密码，然后退出(ctrl + c)
docker-compose run --rm telegram_media_downloader

# 执行完以上操作后，后面的所有启动都在后台启动
docker-compose up -d

＃ 升级
docker pull tangyoha/telegram_media_downloader:latest
cd ~/app
docker-compose down
docker-compose up -d
```

## 升级安装

```sh
cd telegram_media_downloader
git pull
pip3 install -r requirements.txt
```

## 配置

> 项目提供了 `config.example.yaml` 作为配置文件模板，使用前请复制为 `config.yaml` 并根据实际情况修改。

所有配置都通过 config.yaml 文件传递​​给 `Telegram Media Downloader`。

**获取您的 API 密钥：**
第一步需要您获得有效的 Telegram API 密钥（API id/hash pair）：

1. 访问 [https://my.telegram.org/apps](https://my.telegram.org/apps) 并使用您的 Telegram 帐户登录。
2. 填写表格以注册新的 Telegram 应用程序。
3. 完成！ API 密钥由两部分组成：**api_id** 和**api_hash**。

**获取聊天ID：**
> 如果你需要下载收藏夹的内容请填`me`

**1。使用网络电报：**

1. 打开 <https://web.telegram.org/?legacy=1#/im>
2. 现在转到聊天/频道，您将看到 URL 类似

- `https://web.telegram.org/?legacy=1#/im?p=u853521067_2449618633394` 这里 `853521067` 是聊天 ID。
- `https://web.telegram.org/?legacy=1#/im?p=@somename` 这里的 `somename` 是聊天 ID。
- `https://web.telegram.org/?legacy=1#/im?p=s1301254321_6925449697188775560` 此处取 `1301254321` 并将 `-100` 添加到 id => `-1001301254321` 的开头。
- `https://web.telegram.org/?legacy=1#/im?p=c1301254321_6925449697188775560` 此处取 `1301254321` 并将 `-100` 添加到 id => `-1001301254321` 的开头。

**2。使用机器人：**
1.使用[@username_to_id_bot](https://t.me/username_to_id_bot)获取chat_id
    - 几乎所有电报用户：将用户名发送给机器人或将他们的消息转发给机器人
    - 任何聊天：发送聊天用户名或复制并发送其加入聊天链接到机器人
    - 公共或私人频道：与聊天相同，只需复制并发送给机器人
    - 任何电报机器人的 ID

### 配置文件

> 项目提供了 `config.example.yaml` 作为配置文件模板，使用前请复制为 `config.yaml` 并根据实际情况修改。

```yaml
api_hash: your_api_hash
api_id: your_api_id
bot_token: your_bot_token
chat:
- chat_id: telegram_chat_id
  last_read_message_id: 0
  download_filter: message_date >= 2022-12-01 00:00:00 and message_date <= 2023-01-17 00:00:00
- chat_id: telegram_chat_id_2
  last_read_message_id: 0
# 我们将ids_to_retry移到data.yaml
ids_to_retry: []
media_types:
- audio
- document
- photo
- video
- voice
- animation #gif
file_formats:
  audio:
  - all
  document:
  - pdf
  - epub
  video:
  - mp4
save_path: D:\telegram_media_downloader
file_path_prefix:
- chat_title
- media_datetime
upload_drive:
  enable_upload_file: true
  remote_dir: drive:/telegram
  before_upload_file_zip: True
  after_upload_file_delete: True
hide_file_name: true
file_name_prefix:
- message_id
- file_name
file_name_prefix_split: ' - '
max_download_task: 5
web_host: 127.0.0.1
web_port: 5000
web_login_secret: 请设置高强度且唯一的密码
allowed_user_ids:
- 'me'
date_format: '%Y_%m'
enable_download_txt: false

```

- **api_hash** - 你从电报应用程序获得的 api_hash
- **api_id** - 您从电报应用程序获得的 api_id
- **bot_token** - 你的机器人凭证
- **chat** -  多频道
  - `chat_id` -  您要下载媒体的聊天/频道的 ID。你从上述步骤中得到的。
  - `download_filter` - 下载过滤器, 查阅 [如何使用过滤器](https://github.com/tangyoha/telegram_media_downloader/wiki/%E5%A6%82%E4%BD%95%E4%BD%BF%E7%94%A8%E8%BF%87%E6%BB%A4%E5%99%A8)
  - `last_read_message_id` -如果这是您第一次阅读频道，请将其设置为“0”，或者如果您已经使用此脚本下载媒体，它将有一些数字，这些数字会在脚本成功执行后自动更新。不要改变它。
- **chat_id** - 您要下载媒体的聊天/频道的 ID。你从上述步骤中得到的。
- **last_read_message_id** - 如果这是您第一次阅读频道，请将其设置为“0”，或者如果您已经使用此脚本下载媒体，它将有一些数字，这些数字会在脚本成功执行后自动更新。不要改变它。
- **ids_to_retry** - `保持原样。`下载器脚本使用它来跟踪所有跳过的下载，以便在下次执行脚本时可以下载它。
- **media_types** - 要下载的媒体类型，您可以更新要下载的媒体类型，它可以是一种或任何可用类型。
- **file_formats** - 为支持的媒体类型（“音频”、“文档”和“视频”）下载的文件类型。默认格式为“all”，下载所有文件。
- **save_path** - 你想存储下载文件的根目录
- **file_path_prefix** - 存储文件子文件夹，列表的顺序不定，可以随机组合
  - `chat_title`      - 聊天频道或者群组标题, 如果找不到标题则为配置文件中的`chat_id`
  - `media_datetime`  - 资源的发布时间
  - `media_type`      - 资源类型，类型查阅 `media_types`
- **upload_drive** - 您可以将文件上传到云盘
  - `enable_upload_file` - [必填]启用上传文件，默认为`false`
  - `remote_dir` - [必填]你上传的地方
  - `upload_adapter` - [必填]上传文件适配器，可以为`rclone`,`aligo`。如果为`rclone`，则支持rclone所有支持上传的服务器，如果为aligo，则支持上传阿里云盘
  - `rclone_path`，如果配置`upload_adapter`为`rclone`则为必填，`rclone`的可执行目录，查阅 [如何使用rclone](https://github.com/tangyoha/telegram_media_downloader/wiki/Rclone)
  - `before_upload_file_zip` - 上传前压缩文件，默认为`false`
  - `after_upload_file_delete` - 上传成功后删除文件，默认为`false`
- **file_name_prefix** - 自定义文件名称,使用和 **file_path_prefix** 一样
  - `message_id` - 消息id
  - `file_name` - 文件名称（可能为空）
  - `caption` - 消息的标题（可能为空）
- **file_name_prefix_split** - 自定义文件名称分割符号，默认为` - `
- **max_download_task** - 最大任务下载任务个数，默认为5个。
- **hide_file_name** - 是否隐藏web界面文件名称，默认`false`
- **web_host** - web界面地址
- **web_port** - web界面端口
- **language** - 应用语言，默认为英文(`EN`),可选`ZH`（中文）,`RU`,`UA`
- **web_login_secret** - 网页登录密码。请使用高强度且唯一的值；Web 控制台暴露到本机以外时应通过 HTTPS 访问。
- **log_level** - 默认日志等级，请参阅 `logging._nameToLevel`
- **forward_limit** - 限制每分钟转发次数，默认为33，默认请不要修改该参数
- **allowed_user_ids** - 允许哪些人使用机器人，默认登录账号可以使用，带@的名称请加单引号
- **date_format** - 支持自定义配置file_path_prefix中media_datetime的格式，具体格式查看 [python-datetime](https://docs.python.org/zh-cn/3/library/time.html)
- **enable_download_txt** 启用下载txt文件，默认`false`

#### 频道库下载配置参数
- **channel_library.min_free_disk_bytes** - 下载生命周期保留的最小可用磁盘空间，默认 `3221225472`（3GB）。资源包会在下载前预约完整已知大小，上传和清理结束后才释放预约。
## 执行

```sh
python3 media_downloader.py
```

所有下载的媒体都将存储在`save_path`根目录下。
具体位置参考如下：

```yaml
file_path_prefix:
  - chat_title
  - media_datetime
  - media_type
```

视频下载完整目录为：`save_path`/`chat_title`/`media_datetime`/`media_type`。
列表的顺序不定，可以随机组合。
如果配置为空，则所有文件保存在`save_path`下。

## 代理

该项目目前支持 socks4、socks5、http 代理。要使用它，请将以下内容添加到`config.yaml`文件的底部

```yaml
proxy:
  scheme: socks5
  hostname: 127.0.0.1
  port: 1234
  username: 你的用户名（无则删除该行）
  password: 你的密码（无则删除该行）
```

如果您的代理不需要授权，您可以省略用户名和密码。然后代理将自动启用。

## 贡献

### 贡献指南

通读我们的[贡献指南](./CONTRIBUTING.md)，了解我们的提交流程、编码规则等。

### 想帮忙？

想要提交错误、贡献一些代码或改进文档？出色的！阅读我们的 [贡献指南](./CONTRIBUTING.md)。

### 行为守则

帮助我们保持 Telegram Media Downloader 的开放性和包容性。请阅读并遵守我们的[行为准则](./CODE_OF_CONDUCT.md)。


### 赞助

<p>
<img alt="Code style: black" style="width:30%" src="./screenshot/alipay.JPG">
<img alt="Code style: black" style="width:30%" src="./screenshot/wechat.JPG">
</p>
