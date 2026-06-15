"""AIOps request and response models."""

from datetime import datetime

from pydantic import BaseModel, Field


class AlertInfo(BaseModel):
    """Alertmanager-compatible alert payload."""

    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    generator_url: str | None = Field(default=None, alias="generatorURL")
    fingerprint: str | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}


class AIOpsRequest(BaseModel):
    """AIOps diagnosis request."""

    session_id: str | None = Field(default="default", description="会话ID，用于追踪诊断历史")
    alert: AlertInfo | None = Field(
        default=None,
        description="单个告警；存在时优先于主动拉取 Alertmanager",
    )
    alerts: list[AlertInfo] = Field(
        default_factory=list,
        description="Alertmanager 兼容的告警数组",
    )
    lookback_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="日志和指标默认回看时间",
    )

    model_config = {
        "json_schema_extra": {"example": {"session_id": "session-123", "lookback_minutes": 60}}
    }
