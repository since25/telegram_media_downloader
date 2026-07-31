
<h1 align="center">Telegram Media Downloader</h1>

<p align="center">
<a href="https://github.com/tangyoha/telegram_media_downloader/actions"><img alt="Unittest" src="https://github.com/tangyoha/telegram_media_downloader/workflows/Unittest/badge.svg"></a>
<a href="https://codecov.io/gh/tangyoha/telegram_media_downloader"><img alt="Coverage Status" src="https://codecov.io/gh/tangyoha/telegram_media_downloader/branch/master/graph/badge.svg"></a>
<a href="https://github.com/tangyoha/telegram_media_downloader/blob/master/LICENSE"><img alt="License: MIT" src="https://black.readthedocs.io/en/stable/_static/license.svg"></a>
<a href="https://github.com/python/black"><img alt="Code style: black" src="https://img.shields.io/badge/code%20style-black-000000.svg"></a>
<a href="https://github.com/tangyoha/telegram_media_downloader/releases">
<img alt="Code style: black" src="https://img.shields.io/github/v/release/tangyoha/telegram_media_downloader?display_name=tag"></a>
</p>

<h3 align="center">
  <a href="./README_CN.md">中文</a><span> · </span>
  <a href="https://github.com/tangyoha/telegram_media_downloader/discussions/categories/ideas">Feature request</a>
  <span> · </span>
  <a href="https://github.com/tangyoha/telegram_media_downloader/issues">Report a bug</a>
  <span> · </span>
  Support: <a href="https://github.com/tangyoha/telegram_media_downloader/discussions">Discussions</a>
  <span> & </span>
  <a href="https://t.me/TeegramMediaDownload">Telegram Community</a>
</h3>

## Overview
> Support two default running

* Run the management Bot for download, prescan, and administration commands

* Download as a one-time download tool

* Download matching indexed channel-library packages automatically

* Optionally run a second resource Bot for activated users to search indexed packages
  and publish them to their own bound channel

### Indexed Package Monitoring

Keyword monitor groups are stored in the channel-library database and managed from the
Web console; keyword rules are not read from `config.yaml`. Each group supports required,
matching, and blacklist keywords. Saving a group or completing a channel scan evaluates
the current cross-channel package index and queues matching stable packages through the
normal persistent download workflow. Completed and `outdated` packages are never
automatically repeated; they remain available for explicit manual download.

The Resources tab searches and selects packages across all indexed channels. Channel
identity remains attached to every package and can be used as an optional multi-channel
filter. The Channels tab shows per-channel package/download totals and the distribution
of stable packages across enabled keyword monitor groups.

The Channels tab owns one database-backed automatic incremental-scan schedule for all
indexed channels. Set its five-field cron expression and IANA timezone in the Web
console; saving enables, disables, or changes the schedule immediately without a
restart. These settings are not read from `config.yaml`. A scheduled tick creates no
empty job when the latest message ID is unchanged. The whole sweep yields while any
recoverable full scan exists, and otherwise skips channels that already have
recoverable scan work.

### UI

#### Web page

> After running, open a browser and visit `localhost:5000`
> If it is a remote machine, you need to configure web_host: 0.0.0.0


<img alt="Code style: black" style="width:100%; high:60%;" src="./screenshot/web_ui.gif"/>

### Robot

> Need to configure bot_token, please refer to [Documentation](https://github.com/tangyoha/telegram_media_downloader/wiki/How-to-Download-Using-Robots)

<img alt="Code style: black" style="width:60%; high:30%; " src="./screenshot/bot.gif"/>

#### Dual-role resource publishing Bot

The process can run two Telegram Bot accounts through the same application lifecycle:

- `bot_token` is the existing management Bot for download and administration.
- `resource_bot_token` is the optional activated-user Bot for binding a destination
  channel, searching stable indexed packages, and publishing them.
- The resource Bot requires the management Bot because activation keys are issued and
  users are revoked through the management role.

Administrators use `/create_resource_key` and
`/revoke_resource_user <telegram_user_id>` in the management Bot. A resource user then
uses `/activate <key>`, `/bind`, and `/search <keyword>` in the resource Bot. The user
adds only the resource Bot to the destination channel as an administrator with permission
to post messages.

The main Telegram account reads and downloads source media; the resource Bot uploads the
temporary files to the bound channel. The resource Bot therefore does not need access to
private source channels. Delivery is globally serial and stages one compatible media
group or single item at a time in a private staging channel: download, stage, then
immediately delete that group's local files. After the whole package is staged, the Bot
copies each group to the user's channel. Compatible Telegram albums remain intact, with
at most 10 items per group, so temporary disk usage is bounded by the active group and
download/staging failures publish nothing to the user's channel. A later destination
copy failure is reported as `partial_upload` with the published count and is not retried
automatically. State is stored
separately in `resource_bot.sqlite3`. The Web console has an independent Publishing tab
for queue position, download/upload item counts, live speeds, results, queued-job
cancellation, and terminal-history cleanup. See
[`docs/resource-bot-server-handoff.md`](docs/resource-bot-server-handoff.md) for the
production handoff.

### Support

| Category             | Support                                          |
| -------------------- | ------------------------------------------------ |
| Language             | `Python 3.11`                                    |
| Download media types | audio, document, photo, video, video_note, voice |

### Version release plan

* [v2.2.0](https://github.com/tangyoha/telegram_media_downloader/issues/2)

## Installation

For *nix os distributions with `make` availability

```sh
git clone https://github.com/tangyoha/telegram_media_downloader.git
cd telegram_media_downloader
make install
```

For Windows which doesn't have `make` inbuilt

```sh
git clone https://github.com/tangyoha/telegram_media_downloader.git
cd telegram_media_downloader
pip3 install -r requirements.txt
```

## Docker
> For more detailed installation tutorial, please check the wiki

Make sure you have **docker** and **docker-compose** installed
```sh
docker pull tangyoha/telegram_media_downloader:latest
mkdir -p ~/app/{downloads,log,rclone,sessions,state,temp} && cd ~/app
wget https://raw.githubusercontent.com/tangyoha/telegram_media_downloader/master/docker-compose.yaml -O docker-compose.yaml
wget https://raw.githubusercontent.com/tangyoha/telegram_media_downloader/master/config.example.yaml -O state/config.yaml
wget https://raw.githubusercontent.com/tangyoha/telegram_media_downloader/master/data.example.yaml -O state/data.yaml
printf 'TMD_UID=%s\nTMD_GID=%s\n' "$(id -u)" "$(id -g)" > .env
sudo chown -R "$(id -u):$(id -g)" downloads log rclone sessions state temp
# enable_web may remain false; container health does not depend on the Web listener.
vi state/config.yaml
# Optional: copy an existing Rclone configuration into the project-local mount.
cp "$HOME/.config/rclone/rclone.conf" rclone/rclone.conf

# The first time you need to start the foreground
# enter your phone number and code, then exit(ctrl + c)
docker compose run --rm telegram_media_downloader

# After performing the above operations, all subsequent startups will start in the background
docker compose up -d

# Upgrade
docker pull tangyoha/telegram_media_downloader:latest
cd ~/app
docker compose down
docker compose up -d
```

The image runs without root privileges. Compose reads `TMD_UID` and `TMD_GID` from
`.env` so mounted files remain owned by the host operator. Every writable mount must be
accessible to that numeric user. The whole `./state` directory is mounted at
`/app/state`; it stores `state/config.yaml`, `state/data.yaml`, all three SQLite
databases, and `.web_auth.json`, allowing atomic configuration replacement inside one
directory mount.

For an existing Docker installation, stop the container and back it up before changing
ownership. Migrate each live SQLite database with the SQLite backup API and verify
`PRAGMA integrity_check`; do not copy a live WAL database. Then move `config.yaml` to
`state/config.yaml`, `data.yaml` to `state/data.yaml`, and the Web auth file into
`state/`. Copy Rclone configuration into `./rclone/`, create `.env` with the chosen
`TMD_UID`/`TMD_GID`, and run `chown -R` over `downloads`, `log`, `rclone`, `sessions`,
`state`, and `temp` before starting the non-root container. Keep the stopped pre-migration
directory as the rollback point.

The published runtime image is built only from the checked-out source and its local
`compile-image` stage. Real `config.yaml`, `data.yaml`, sessions, databases, downloads,
logs, and Web credentials are excluded from the build context and must be mounted at
runtime. The Python base image is pinned to the reviewed multi-architecture digest and
the Alpine build/runtime packages are version-pinned. The Pyrogram fork is pinned to an
immutable commit/archive checksum. Rclone commands are executed as argument arrays, and
upload success is determined by the process exit code rather than a human-readable
progress line. The container health check reads the atomic
`/app/state/runtime-health.json` marker and verifies that it belongs to the live ready
process, so it also works when `enable_web: false`.

Docker publication runs the complete tests, import/compile/dependency checks, the
blocking static boundary, pre-commit, and Compose rendering in the same workflow before
the image job becomes reachable. Every pushed image has an immutable
`sha-<40-character-commit>` tag; release tags are retained, and `latest` is emitted only
for a verified default-branch build. The Python wheel contains `media_downloader.py`,
the runtime `module` and `utils` packages, and the Web templates/static assets.

The container paths are explicit and may be overridden when needed:

```yaml
TMD_CONFIG_PATH: /app/state/config.yaml
TMD_DATA_PATH: /app/state/data.yaml
TMD_TASK_DB_PATH: /app/state/web_tasks.sqlite3
TMD_CHANNEL_LIBRARY_DB_PATH: /app/state/channel_library.sqlite3
TMD_RESOURCE_BOT_DB_PATH: /app/state/resource_bot.sqlite3
TMD_WEB_AUTH_FILE: /app/state/.web_auth.json
TMD_RUNTIME_HEALTH_PATH: /app/state/runtime-health.json
```

## Upgrade installation

```sh
cd telegram_media_downloader
pip3 install -r requirements.txt
```

## Configuration

All the configurations are  passed to the Telegram Media Downloader via `config.yaml` file.

**Getting your API Keys:**
The very first step requires you to obtain a valid Telegram API key (API id/hash pair):

1. Visit  [https://my.telegram.org/apps](https://my.telegram.org/apps)  and log in with your Telegram Account.
2. Fill out the form to register a new Telegram application.
3. Done! The API key consists of two parts:  **api_id**  and  **api_hash**.

**Getting chat id:**

**1. Using web telegram:**

1. Open <https://web.telegram.org/?legacy=1#/im>

2. Now go to the chat/channel and you will see the URL as something like
   - `https://web.telegram.org/?legacy=1#/im?p=u853521067_2449618633394` here `853521067` is the chat id.
   - `https://web.telegram.org/?legacy=1#/im?p=@somename` here `somename` is the chat id.
   - `https://web.telegram.org/?legacy=1#/im?p=s1301254321_6925449697188775560` here take `1301254321` and add `-100` to the start of the id => `-1001301254321`.
   - `https://web.telegram.org/?legacy=1#/im?p=c1301254321_6925449697188775560` here take `1301254321` and add `-100` to the start of the id => `-1001301254321`.

**2. Using bot:**

1. Use [@username_to_id_bot](https://t.me/username_to_id_bot) to get the chat_id of
    - almost any telegram user: send username to the bot or just forward their message to the bot
    - any chat: send chat username or copy and send its joinchat link to the bot
    - public or private channel: same as chats, just copy and send to the bot
    - id of any telegram bot

### config.yaml

```yaml
api_hash: your_api_hash
api_id: your_api_id
bot_token: your_bot_token
resource_bot_token: your_resource_bot_token
resource_staging_chat_id: -1001234567890
chat:
- chat_id: telegram_chat_id
  last_read_message_id: 0
  download_filter: message_date >= 2022-12-01 00:00:00 and message_date <= 2023-01-17 00:00:00
- chat_id: telegram_chat_id_2
  last_read_message_id: 0
# note we remove ids_to_retry to data.yaml
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
  # required
  enable_upload_file: true
  # required
  remote_dir: drive:/telegram
  # required
  upload_adapter: rclone
  # option,when config upload_adapter rclone then this config are required
  rclone_path: D:\rclone\rclone.exe
  # option
  before_upload_file_zip: True
  # option
  after_upload_file_delete: True
hide_file_name: true
file_name_prefix:
- message_id
- file_name
file_name_prefix_split: ' - '
max_download_task: 5
web_host: 127.0.0.1
web_port: 5000
language: EN
web_login_secret: set-a-strong-unique-password
web_secure_cookie: false
allowed_user_ids:
- 'me'
date_format: '%Y_%m'
enable_download_txt: false
```

- **api_hash**  - The api_hash you got from telegram apps
- **api_id** - The api_id you got from telegram apps
- **bot_token** - Your bot token
- **resource_bot_token** - Optional activated-user resource Bot token. It shares the
  management Bot lifecycle and cannot be configured without `bot_token`.
- **resource_staging_chat_id** - Private staging channel ID. The resource Bot must be an
  administrator that can publish and delete messages.
- **chat** - Chat list
  - `chat_id` -  The id of the chat/channel you want to download media. Which you get from the above-mentioned steps.
  - `download_filter` - Download filter, see [How to use Filter](https://github.com/tangyoha/telegram_media_downloader/wiki/How-to-use-Filter)
  - `last_read_message_id` - If it is the first time you are going to read the channel let it be `0` or if you have already used this script to download media it will have some numbers which are auto-updated after the scripts successful execution. Don't change it.
  - `ids_to_retry` - `Leave it as it is.` This is used by the downloader script to keep track of all skipped downloads so that it can be downloaded during the next execution of the script.
- **media_types** - Type of media to download, you can update which type of media you want to download it can be one or any of the available types.
- **file_formats** - File types to download for supported media types which are `audio`, `document` and `video`. Default format is `all`, downloads all files.
- **save_path** - The root directory where you want to store downloaded files.
- **file_path_prefix** - Store file subfolders, the order of the list is not fixed, can be randomly combined.
  - `chat_title`      - Channel or group title, it will be chat id if not exist title.
  - `media_datetime`  - Media date.
  - `media_type`      - Media type, also see `media_types`.
- **upload_drive** - You can upload file to cloud drive.
  - `enable_upload_file` - Enable upload file, default `false`.
  - `remote_dir` - Where you upload, like `drive_id/drive_name`.
  - `upload_adapter` - Upload file adapter, which can be `rclone`, `aligo`. If it is `rclone`, it supports all `rclone` servers that support uploading. If it is `aligo`, it supports uploading `Ali cloud disk`. Aligo is an optional dependency and is not installed by `requirements.txt`; install the reviewed pinned version with `pip install aligo==5.4.0`, select the adapter, and restart the service. Startup fails with a clear error when the package is unavailable.
  - `rclone_path` - RClone exe path, see [How to use rclone](https://github.com/tangyoha/telegram_media_downloader/wiki/Rclone)
  - `before_upload_file_zip` - Zip file before upload, default `false`.
  - `after_upload_file_delete` - Delete file after upload success, default `false`.
- **file_name_prefix** - Custom file name, use the same as **file_path_prefix**
  - `message_id` - Message id
  - `file_name` - File name (may be empty)
  - `caption` - The title of the message (may be empty)
- **file_name_prefix_split** - Custom file name prefix symbol, the default is `-`
- **max_download_task** - The maximum number of task download tasks, the default is 5.
- **hide_file_name** - Whether to hide the web interface file name, default `false`
- **web_host** - Web host
- **web_port** - Web port
- **language** - Application language, the default is English (`EN`), optional `ZH`(Chinese),`RU`,`UA`
- **web_login_secret** - Web page login password. Use a strong, unique value. The Web console always requires login and should be exposed through HTTPS when it is reachable beyond localhost.
- **web_secure_cookie** - Set `true` only when the Web console is served over HTTPS, then restart. HTTPS production deployments should enable it; direct HTTP deployments must leave it `false` or the browser will not return the session cookie.
- **log_level** - see `logging._nameToLevel`.
- **forward_limit** - Limit the number of forwards per minute, the default is 33, please do not modify this parameter by default.
- **allowed_user_ids** - Who is allowed to use the robot? The default login account can be used. Please add single quotes to the name with @.
- **date_format** Support custom configuration of media_datetime format in file_path_prefix.see [python-datetime](https://docs.python.org/3/library/datetime.html)
- **enable_download_txt** Enable download txt file, default `false`

Web settings are validated as one request before any live value or file is changed.
Malformed types, unsupported list values, out-of-range integers, and invalid
`date_format` directives return `400 invalid_settings` with the rejected field.
`config.yaml` and `data.yaml` are saved as one journaled generation; startup completes
an interrupted paired write before reading either file and fails clearly if recovery
evidence is inconsistent.

The Web auth file stores a password verifier instead of the configured plaintext
password. An existing plaintext `.web_auth.json` is migrated on startup without changing
the accepted password. If `web_login_secret` is empty, a generated bootstrap password is
written to the auth file only until the first successful login, then removed atomically.
For credential recovery, stop the service, set a new `web_login_secret` in `config.yaml`,
and restart. Back up `.web_auth.json` with the other state files; when rolling back to an
older release, configure `web_login_secret` because older code cannot consume the new
password-hash field.

## Execution

```sh
python3 media_downloader.py
```

All downloaded media will be stored at the root of `save_path`.
The specific location reference is as follows:

The complete directory of video download is: `save_path`/`chat_title`/`media_datetime`/`media_type`.
The order of the list is not fixed and can be randomly combined.
If the configuration is empty, all files are saved under `save_path`.

## Proxy

`socks4, socks5, http` proxies are supported in this project currently. To use it, add the following to the bottom of your `config.yaml` file

```yaml
proxy:
  scheme: socks5
  hostname: 127.0.0.1
  port: 1234
  username: your_username(delete the line if none)
  password: your_password(delete the line if none)
```

If your proxy doesn’t require authorization you can omit username and password. Then the proxy will automatically be enabled.

## Contributing

### Contributing Guidelines

Read through our [contributing guidelines](https://github.com/tangyoha/telegram_media_downloader/blob/master/CONTRIBUTING.md) to learn about our submission process, coding rules and more.

### Want to Help?

Want to file a bug, contribute some code, or improve documentation? Excellent! Read up on our guidelines for [contributing](https://github.com/tangyoha/telegram_media_downloader/blob/master/CONTRIBUTING.md).

### Code of Conduct

Help us keep Telegram Media Downloader open and inclusive. Please read and follow our [Code of Conduct](https://github.com/tangyoha/telegram_media_downloader/blob/master/CODE_OF_CONDUCT.md).


### Sponsor

[PayPal](https://paypal.me/tangyoha?country.x=C2&locale.x=zh_XC)

<p>
<img alt="Code style: black" style="width:30%" src="./screenshot/alipay.JPG">
<img alt="Code style: black" style="width:30%" src="./screenshot/wechat.JPG">
</p>
