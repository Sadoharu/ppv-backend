from pydantic import BaseModel, ConfigDict
from datetime import datetime

class CcuPoint(BaseModel):
    ts: datetime
    ccu: int
    model_config = ConfigDict(from_attributes=True)

class CodeStats(BaseModel):
    code_id: int
    sessions: int
    watch_seconds: int
    bytes_out: int