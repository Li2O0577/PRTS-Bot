from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator


class SmartReplyConfig(BaseModel):
    smart_reply_enabled: bool = True
    smart_reply_memory_turns: int = Field(default=16, ge=2, le=80)
    smart_reply_max_replies: int = Field(default=3, ge=1, le=5)
    smart_reply_reply_probability: float = Field(default=0.55, ge=0.0, le=1.0)
    smart_reply_allowed_private: bool = True
    smart_reply_allowed_group: bool = True
    smart_reply_require_mention_in_group: bool = False
    smart_reply_batch_wait_seconds: float = Field(default=2.5, ge=0.3, le=20.0)
    smart_reply_max_batch_messages: int = Field(default=8, ge=1, le=30)

    smart_reply_api_key: str = ""
    smart_reply_api_base: str = "https://api.openai.com/v1"
    smart_reply_model: str = "gpt-4.1-mini"
    smart_reply_temperature: float = Field(default=0.85, ge=0.0, le=2.0)
    smart_reply_timeout: float = Field(default=30.0, ge=3.0, le=120.0)
    smart_reply_persona: str = (
        "You are PRTS, the Rhodes Island central control system. Reply in Chinese. "
        "Be calm, professional, concise, and efficient. Call the user Doctor."
    )

    @field_validator("smart_reply_api_base")
    @classmethod
    def normalize_api_base(cls, value: str) -> str:
        value = value.rstrip("/")
        if value.endswith("/chat/completions"):
            value = value.removesuffix("/chat/completions")
        return value


config = get_plugin_config(SmartReplyConfig)
