import traceback
import asyncio
from typing import List
from httpx import HTTPError
from nonebot import logger
from .client.tw_pcrclient import (
    pcrclient as tw_pcrclient,
    ApiException,
    get_ver,
)
from .database.dal import PCRBind, pcr_sqla, Account
from .var import Platform, Priority, platform_dict, queue_dict


class MatchError(Exception):
    pass


async def _query(client: tw_pcrclient, platform_id: int):
    viewer_id: str = client.viewer_id
    queue: asyncio.PriorityQueue = queue_dict[platform_id]
    while True:
        try:
            DA = await queue.get()
            uid = None
            queue.task_done()
            data = DA[2]
            callback, info, result_storage = data
            uid = int(info.pcrid)
            res = await client.callapi('/profile/get_profile', {'target_viewer_id': uid})
            if 'user_info' not in res:
                await client.login()  # 失败重连
                res = await client.callapi('/profile/get_profile', {'target_viewer_id': uid})
            elif res["user_info"]["viewer_id"] != uid:
                raise MatchError
            result_storage["res"] = res
            result_storage["uid"] = uid
            result_storage["bind_info"] = info
            await callback(result_storage)
        except ApiException as e:
            if str(e) == "服务器在维护":
                await asyncio.sleep(e.code)
            else:
                logger.info(f"{viewer_id}查询{uid}失败")
                logger.info(traceback.format_exc())
        except (HTTPError, MatchError):
            logger.info(f"重试：{viewer_id} 对于 {uid} 的查询请求超时或不匹配。")
            try:
                await queue.put(DA)
            except Exception:
                logger.info(f"失败：{viewer_id} 对于 {uid} 重试失败")
                logger.info(traceback.format_exc())
        except Exception:
            # 这里不能用裸 except：会把 CancelledError 一起吞掉，导致 reload/关停时任务无法取消
            logger.info(f"失败：{viewer_id} 未能完成查询请求。")
            logger.info(traceback.format_exc())


async def query_all(query_list: List[PCRBind], platform, function, result_storage: dict = {}, priority: int = Priority.query_all.value):
    """
    台服查询入口：台一（美食殿堂）与其他服分别走各自的登录账号队列
    """
    temp1 = []  # 台一
    temp2 = []  # 台二/三/四
    for query in query_list:
        if query.pcrid // 1000000000 == 1:
            temp1.append(query)
        else:
            temp2.append(query)

    queue: asyncio.PriorityQueue = queue_dict[Platform.tw_id.value]
    if queue:
        if priority == Priority.query_all.value:
            await queue.join()
        await asyncio.gather(*map(lambda info: queue.put((priority, (info.pcrid, info.user_id, info.platform), (function, info, result_storage))), temp1))
    elif temp1:
        logger.warn("未绑定台一服务器的查询账户，但有玩家查询，已自动忽略")

    queue2: asyncio.PriorityQueue = queue_dict[Platform.tw_other_id.value]
    if queue2:
        if priority == Priority.query_all.value:
            await queue2.join()
        await asyncio.gather(*map(lambda info: queue2.put((priority, (info.pcrid, info.user_id, info.platform), (function, info, result_storage))), temp2))
    elif temp2:
        logger.warn("未绑定台其他服务器的查询账户，但有玩家查询，已自动忽略")


async def login_all():
    acinfo: List[Account] = await pcr_sqla.select_account()
    if not any(i.platform == Platform.tw_id.value for i in acinfo):
        # 数据库为空、或只剩旧版 b服/渠道服记录时，直接退回 account 目录解析，
        # 避免数据库环节出问题导致整个推送起不来
        from .tool import parse_accounts

        direct = [Account(**a) for a in parse_accounts()]
        if direct:
            logger.warning(
                f"数据库里没有可用的台服账号，已直接使用 account 目录解析出的 {len(direct)} 个账号"
            )
            acinfo = direct
    loop = asyncio.get_event_loop()

    # 先确认版本号能不能取到：这一行失败通常意味着部署的是旧的 tw_pcrclient.py
    try:
        logger.info(f"当前台服 APP-VER = {get_ver()}")
    except Exception:
        logger.error(f"APP-VER 获取失败，请检查 client/tw_pcrclient.py 是否为最新版本：\n{traceback.format_exc()}")

    loaded = 0
    for i in acinfo:
        if i.platform != Platform.tw_id.value:
            continue
        tw_platform = int(i.viewer_id) // 1000000000
        queue_id = (
            Platform.tw_id.value if tw_platform == 1 else Platform.tw_other_id.value
        )
        try:
            client = tw_pcrclient(i.account, i.password, i.viewer_id, tw_platform)
        except Exception:
            # 单个账号初始化失败不能拖垮整个 login_all，也不能留下没有消费者的队列
            logger.error(
                f"账号 {i.viewer_id} 初始化失败，已跳过：\n{traceback.format_exc()}"
            )
            continue
        if not queue_dict[queue_id]:
            queue_dict[queue_id] = asyncio.PriorityQueue()
        loop.create_task(_query(client, queue_id))
        loaded += 1
        logger.info(
            f"加载账号：ID{i.viewer_id}, 服务器：{platform_dict.get(i.platform, '台')}服-{tw_platform}区"
        )

    logger.info(
        f"账号登录完成：{loaded}/{len(acinfo)} 个可用，"
        f"台一队列={'已启动' if queue_dict[Platform.tw_id.value] else '未启动'}，"
        f"台其他队列={'已启动' if queue_dict[Platform.tw_other_id.value] else '未启动'}"
    )
