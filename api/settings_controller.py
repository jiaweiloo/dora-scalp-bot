from typing import List
from fastapi import Header, APIRouter, HTTPException

from database.dora_bot_settings import DoraBotSettingsDAL, DoraBotSettings, DoraBotSettingsModel
from utils.json_utils import parse_obj_to_dict

settings = APIRouter()
trade_txn_dal: DoraBotSettingsDAL = DoraBotSettingsDAL()


@settings.get('/')
async def index(dora_setting_seqno: int = 1):
    obj: DoraBotSettings = (trade_txn_dal.get_single_obj(dora_setting_seqno=dora_setting_seqno))
    print(obj.__dict__)
    return obj


@settings.post('/', status_code=201)
async def add_settings(dora_bot_settings_model: DoraBotSettingsModel):

    if dora_bot_settings_model.dora_setting_seqno:
        temp = trade_txn_dal.get_single_obj(dora_bot_settings_model.dora_setting_seqno)
        for key, value in parse_obj_to_dict(dora_bot_settings_model).items():
            setattr(temp, key, value)
        trade_txn_dal.create(temp)
    else:
        dora_bot_settings: DoraBotSettings = DoraBotSettings(**dora_bot_settings_model.dict())
        trade_txn_dal.create(dora_bot_settings)

    return dora_bot_settings_model

