# NoneBot NapCat QQ Smart Reply

这是一个基于 NoneBot2 的 QQ 智能回复项目，用 OneBot V11 适配器对接 NapCat。

当前能力：

- 私聊、群聊消息监听
- 同一会话多条消息合并成上下文后再回复
- 按会话隔离的短期记忆
- AI 自行判断是否需要回复
- 默认简短回复，避免连续刷屏
- OpenAI-compatible 模型接口
- PRTS wiki 查询 skill
- 明日方舟基础 DPS / HPS / 总伤计算 skill

## 安装

建议使用 Python 3.10 或更新版本。

```powershell
cd "$HOME\Desktop\new"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .
```

之后日常启动直接运行：

```powershell
cd "$HOME\Desktop\new"
.\start.ps1
```

## NapCat 对接

在 NapCat 中添加 OneBot V11 反向 WebSocket：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

如果 NapCat 配置了 token，需要在 `.env` 中设置同一个值：

```env
ONEBOT_ACCESS_TOKEN=你的token
```

## 核心配置

真实配置写在 `.env`，`.env.example` 只是模板。

```env
HOST=127.0.0.1
PORT=8080
SMART_REPLY_API_KEY=你的APIKey
SMART_REPLY_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
SMART_REPLY_MODEL=qwen-plus
```

常用行为参数：

```env
SMART_REPLY_MEMORY_TURNS=16
SMART_REPLY_MAX_REPLIES=1
SMART_REPLY_MAX_REPLY_CHARS=150
SMART_REPLY_BATCH_WAIT_SECONDS=2.5
SMART_REPLY_MAX_BATCH_MESSAGES=8
SMART_REPLY_TEMPERATURE=0.65
```

说明：

- `SMART_REPLY_MAX_REPLIES`：一次最多回复几条，推荐保持 `1`
- `SMART_REPLY_MAX_REPLY_CHARS`：单条回复最大长度
- `SMART_REPLY_BATCH_WAIT_SECONDS`：等待用户把连续消息说完的时间
- `SMART_REPLY_MAX_BATCH_MESSAGES`：一次最多合并多少条连续消息
- `SMART_REPLY_MEMORY_TURNS`：每个会话保留多少条短期记忆

## Wiki Skill

明日方舟资料查询 skill 位于：

```text
src/skills/arknights_wiki/
  __init__.py
  skill.py
  README.md
```

它会在用户询问干员、技能、材料、敌人、关卡、活动、机制等资料时，由 AI 判断是否需要查询 PRTS wiki。

相关配置：

```env
SMART_REPLY_WIKI_ENABLED=true
SMART_REPLY_WIKI_API_BASE=https://prts.wiki/api.php
SMART_REPLY_WIKI_TIMEOUT=12
SMART_REPLY_WIKI_MAX_PAGES=3
SMART_REPLY_WIKI_EXTRACT_CHARS=2500
```

## Calculator Skill

明日方舟基础数值计算 skill 位于：

```text
src/skills/arknights_calculator/
  __init__.py
  skill.py
  README.md
```

当前支持：

- 物理 DPS / 总伤
- 法术 DPS / 总伤
- 真伤 DPS / 总伤
- 治疗 HPS / 总治疗量

相关配置：

```env
SMART_REPLY_CALC_ENABLED=true
```

示例问题：

```text
PRTS，帮我算法伤DPS，攻击1000，倍率240%，攻击间隔1.6秒，持续30秒，敌人20法抗
```

如果缺少攻击力、倍率、攻击间隔、持续时间、防御/法抗等关键参数，bot 会提示缺少参数，不会硬算。

## 项目结构

```text
new/
  bot.py
  pyproject.toml
  start.ps1
  .env.example
  README.md
  data/
    short_term_memory.json
  src/
    plugins/
      smart_reply/
        __init__.py        # 消息监听、合并、编排 skill
        config.py          # 配置定义
        llm.py             # AI 判断：是否回复、是否查 wiki、是否计算
        memory.py          # 短期记忆
        wiki.py            # 兼容转发到 skills/arknights_wiki
        calculator.py      # 兼容转发到 skills/arknights_calculator
    skills/
      arknights_wiki/
        __init__.py
        skill.py
        README.md
      arknights_calculator/
        __init__.py
        skill.py
        README.md
```

## Skill 调用流程

```text
QQ 消息
→ smart_reply 合并短时间内的多条消息
→ AI 判断是否需要查 wiki
→ 需要时调用 arknights_wiki skill
→ AI 判断是否需要计算
→ 需要时调用 arknights_calculator skill
→ AI 根据聊天上下文、wiki 资料、计算结果生成简短回复
```

短期记忆保存在：

```text
data/short_term_memory.json
```