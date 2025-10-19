# qtrader/configs/config_schema.py

from typing import Optional
from pydantic import BaseModel, model_validator

class EngineConfig(BaseModel):
    mode: str = 'backtest'
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    @model_validator(mode='after')
    def check_dates_for_backtest(self) -> 'EngineConfig':
        if self.mode == 'backtest' and (self.start_date is None or self.end_date is None):
            raise ValueError('start_date and end_date are required for backtest mode')
        return self

class MinimalQTraderConfig(BaseModel):
    engine: EngineConfig
