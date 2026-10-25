from enum import Enum
from asyncio import Lock
from pydantic import BaseModel


class Platform(Enum):
    """
    台服平台id（仅台服）
    与游戏登录那块无关

    tw_id: 台一（美食殿堂），绑定一个登录账号
    tw_other_id: 台二/三/四，绑定另一个登录账号
    """

    tw_id = 2
    tw_other_id = 3


class NoticeType(Enum):
    """
    通知类型id
    """

    jjc = 0
    pjjc = 1
    online = 2


class Priority(Enum):
    """
    优先级，越大优先度越低
    """

    query_all = 10
    detial_query = 2
    query_user = 3
    bind = 4
    query_talent = 5


class BaseSet(Enum):
    """
    tw_max_pri：台服最大私聊人数
    """

    tw_max_pri = 0


class LoadBase(BaseModel):
    tw_group_user: int
    tw_group_pcrid: int
    tw_private_user: int
    tw_private_pcrid: int
    tw_today_send: int
    tw_yesterday_send: int


queue_dict = {
    Platform.tw_id.value: False,
    Platform.tw_other_id.value: False,
}

private_dict = {
    Platform.tw_id.value: BaseSet.tw_max_pri.value,
}

platform_dict = {
    Platform.tw_id.value: "台",
    "台": Platform.tw_id.value,
}

platform_tw = {1: "美食殿堂", 2: "真步真步王国", 3: "破晓之星", 4: "小小甜心"}

cache = {}
lck = Lock()
query_cache = {}
talent_cache = {}
jjc_log = {Platform.tw_id.value: [], Platform.tw_other_id.value: []}
