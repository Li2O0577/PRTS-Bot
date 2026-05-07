# NoneBot NapCat QQ 智能回复

这是一个基于 NoneBot2 的 QQ 智能回复项目，用 OneBot V11 适配器对接 NapCat。

它已经内置：

- 私聊、群聊消息监听
- 按会话隔离的短期记忆
- 由模型自由决定是否回复
- 单次可回复 0 到多条消息
- OpenAI-compatible 接口配置
- 无 API key 时的本地兜底回复逻辑

## 1. 安装

建议使用 Python 3.10 或更新版本。

```powershell
cd "$HOME\Desktop\new"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .
```

## 2. 配置

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```env
HOST=127.0.0.1
PORT=8080
SMART_REPLY_API_KEY=你的模型 API Key
SMART_REPLY_API_BASE=https://api.openai.com/v1
SMART_REPLY_MODEL=gpt-4.1-mini
```

如果你在 NapCat 的 OneBot 配置里设置了 token，也要在 `.env` 里设置同一个值：

```env
ONEBOT_ACCESS_TOKEN=你的 token
```

没有 API key 时，机器人仍会运行，但只会使用本地兜底策略，智能程度会明显低一些。

## 3. NapCat 对接

在 NapCat 中添加 OneBot V11 连接，推荐使用反向 WebSocket：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

常见配置：

- 类型：WebSocket 客户端 / 反向 WebSocket
- 地址：`ws://127.0.0.1:8080/onebot/v11/ws`
- token：如果填写，要和 `.env` 的 `ONEBOT_ACCESS_TOKEN` 一致

## 4. 启动

```powershell
cd "$HOME\Desktop\new"
.\.venv\Scripts\Activate.ps1
python bot.py
```

看到 NoneBot 启动后，再启动或重连 NapCat。NapCat 连上后，QQ 消息会自动进入 `smart_reply` 插件。

## 5. 行为调节

这些配置都在 `.env` 中：

```env
SMART_REPLY_MEMORY_TURNS=16
SMART_REPLY_MAX_REPLIES=3
SMART_REPLY_REPLY_PROBABILITY=0.55
SMART_REPLY_ALLOWED_PRIVATE=true
SMART_REPLY_ALLOWED_GROUP=true
SMART_REPLY_REQUIRE_MENTION_IN_GROUP=false
SMART_REPLY_PERSONA=你是一个自然、有分寸、不刷屏的 QQ 聊天助手。
```

说明：

- `SMART_REPLY_MEMORY_TURNS`：每个私聊或群聊保存最近多少条上下文
- `SMART_REPLY_MAX_REPLIES`：模型一次最多能拆成几条 QQ 消息
- `SMART_REPLY_REPLY_PROBABILITY`：无 API key 兜底模式下的主动回复概率
- `SMART_REPLY_REQUIRE_MENTION_IN_GROUP`：群聊是否必须 @ 机器人后才回复
- `SMART_REPLY_PERSONA`：机器人的口吻和边界

短期记忆保存在：

```text
data/short_term_memory.json
```

## 6. 项目结构

```text
new/
  bot.py
  pyproject.toml
  .env.example
  src/
    plugins/
      smart_reply/
        __init__.py
        config.py
        llm.py
        memory.py
```
