from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator


class SmartReplyConfig(BaseModel):
    smart_reply_enabled: bool = True
    smart_reply_memory_turns: int = Field(default=24, ge=2, le=80)
    smart_reply_max_replies: int = Field(default=1, ge=1, le=3)
    smart_reply_reply_probability: float = Field(default=0.55, ge=0.0, le=1.0)
    smart_reply_allowed_private: bool = True
    smart_reply_allowed_group: bool = True
    smart_reply_require_mention_in_group: bool = False
    smart_reply_batch_wait_seconds: float = Field(default=2.5, ge=0.3, le=20.0)
    smart_reply_max_batch_messages: int = Field(default=8, ge=1, le=30)
    smart_reply_max_reply_chars: int = Field(default=180, ge=20, le=500)
    smart_reply_wiki_enabled: bool = True
    smart_reply_wiki_api_base: str = "https://prts.wiki/api.php"
    smart_reply_wiki_timeout: float = Field(default=12.0, ge=3.0, le=60.0)
    smart_reply_wiki_max_pages: int = Field(default=3, ge=1, le=8)
    smart_reply_wiki_extract_chars: int = Field(default=1800, ge=200, le=3000)
    smart_reply_calc_enabled: bool = True

    smart_reply_api_key: str = ""
    smart_reply_api_base: str = "https://api.openai.com/v1"
    smart_reply_model: str = "gpt-4.1-mini"
    smart_reply_temperature: float = Field(default=0.65, ge=0.0, le=2.0)
    smart_reply_timeout: float = Field(default=30.0, ge=3.0, le=120.0)
    smart_reply_persona: str = (
        "You are PRTS, the Rhodes Island central control system. Reply in Chinese. "
        "Be calm, observant, warm, and precise. Call the user Doctor. "
        "When information is incomplete, ask one concise clarifying question instead of pretending to know."
    )

    @field_validator("smart_reply_api_base")
    @classmethod
    def normalize_api_base(cls, value: str) -> str:
        value = value.rstrip("/")
        if value.endswith("/chat/completions"):
            value = value.removesuffix("/chat/completions")
        return value


config = get_plugin_config(SmartReplyConfig)
