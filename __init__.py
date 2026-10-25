import asyncio
import traceback
from datetime import datetime
import os
from json import load, dump
import re
from typing import Dict, List
from nonebot import get_bot, logger, on_command, on_startup
from hoshino import priv, Service
from hoshino.config import SUPERUSERS
from hoshino.typing import HoshinoBot, CQEvent
from nonebot import NoticeSession, MessageSegment
from .utils import bind_pcrid, detial_query, get_platform_id, get_tw_platform, query_loop, talent_query, user_query, get_qid, read_knight_exp_rank
from .query import login_all, query_all
from .var import LoadBase, platform_dict, query_cache, talent_cache, queue_dict, private_dict, Platform, Priority
from .tool import refresh_account
from .img.text2img import image_draw
from .database.dal import pcr_sqla, PCRBind

sv_tw = Service('台服竞技场推送', help_="发送【竞技场帮助】", bundle='pcr查询')


# 本插件为台服专用，所有指令都不带「台」前缀。
# 每条指令都额外保留了一份「台xxx」旧写法（叠加的第二个装饰器），
# 想彻底只留无前缀版本时，把每个装饰器组里带「台」的那几行删掉即可。

@sv_tw.on_fullmatch('台竞技场帮助')
@sv_tw.on_fullmatch('竞技场帮助')
async def send_jjchelp(bot: HoshinoBot, ev: CQEvent):
    platform_name = platform_dict.get(Platform.tw_id.value, "台")
    sv_help = f'''\t\t\t\t\t【{platform_name}服竞技场帮助】
可以添加的订阅：[jjc][pjjc][排名上升][上线提醒]
# 本插件台服专用，指令不需要加「台」前缀（旧的「台xxx」写法也能用）
# 排名上升提醒对jjc和pjjc同时生效
# 每个QQ号至多添加8个uid的订阅
# 默认开启jjc、pjjc，关闭排名上升、上线提醒
# 手动查询时，返回昵称、jjc/pjjc排名、场次、
jjc/pjjc当天排名上升次数、最后登录时间。
# 支持群聊使用。只允许群聊使用！！！
------------------------------------------------
命令格式：
# 只绑定1个uid时，绑定的序号可以不填。
[绑定的序号]1~8对应绑定的第1~8个uid，序号0表示全部
1）竞技场绑定[uid][昵称]（昵称可省略）
2）删除竞技场绑定[绑定的序号]（这里序号不可省略）
3）清空竞技场绑定
4）竞技场查询[uid]/@某人
（uid可省略，@为查别人，uid优先级大于at）
5）竞技场订阅状态[@某人](@某人省略为查自己)
6）竞技场修改昵称 [绑定的序号] [新昵称]
7）竞技场设置[开启/关闭][订阅内容][绑定的序号]
8）竞技场/击剑记录[绑定的序号]（序号可省略）
9）竞技场设置1110[绑定的序号]
# 0表示关闭，1表示开启
# 4个数字依次代表jjc、pjjc、排名上升、上线提醒
# 例如：“竞技场设置1011 2” “竞技场设置1110 0”
# 上线提醒：第4位表示上线提醒等级，可以写0~3
0表示关闭，1表示10分钟cd，仅在18:30~19:00（结算前）报，
2表示10分钟cd，全天报；3表示1分钟cd全天报。
等级3推送最频繁，需要降低频率请手动改回2。
10）详细查询[uid或绑定的序号]
11）深域查询[uid1] [uid2] ...（可同时查询多个uid）
12）更换头像框[文件名] / 查询头像框
13）在本群推送（限群聊发送，无需好友）'''
    if not priv.check_priv(ev, priv.SUPERUSER):
        pic = image_draw(sv_help)
    else:
        sv_help_adm = f'''------------------------------------------------
管理员帮助：
1）pcrjjc负载查询
2）pcrjjc删除绑定[qq号]
3）pcrjjc关闭私聊推送
'''
        pic = image_draw(sv_help+sv_help_adm)
    await bot.send(ev, f'[CQ:image,file={pic}]')

# ========================================查询========================================


@sv_tw.on_fullmatch('台查询竞技场订阅数')
@sv_tw.on_fullmatch('查询竞技场订阅数')
async def pcrjjc_number(bot: HoshinoBot, ev: CQEvent):
    platform_id = get_platform_id(ev)
    await bot.send(ev, f'当前竞技场已订阅的账号数量为【{len(await pcr_sqla.get_bind(platform_id))}】个')


@sv_tw.on_rex(r'^台?竞技场查询 ?(\d+)?$')
async def on_query_arena(bot: HoshinoBot, ev: CQEvent):
    ret: re.Match = ev['match']
    qid = get_qid(ev)
    platform_id = get_platform_id(ev)
    query_dict: Dict[int, int] = {}
    if ret.group(1):
        valid_len = 10
        if (len(ret.group(1))) != (valid_len):
            await bot.send(ev, f'位数不对，uid是{valid_len}位的！')
            return
        pcrid = int(ret.group(1))
        query_list = [PCRBind(platform=platform_id, pcrid=pcrid)]  # 手动查询的列表
        query_dict[pcrid] = 0
    else:
        query_list: List[PCRBind] = await pcr_sqla.get_bind(platform_id, qid)
        for i, bind in enumerate(query_list):
            query_dict[bind.pcrid] = i
    query_cache[ev.user_id] = []
    await query_all(query_list, platform_id, user_query, {"bot": bot, "ev": ev, "info": query_dict, "platform": platform_id}, Priority.query_user.value)


@sv_tw.on_fullmatch('台竞技场订阅状态')
@sv_tw.on_fullmatch('竞技场订阅状态')
async def send_arena_sub_status(bot: HoshinoBot, ev: CQEvent):
    qid = get_qid(ev)
    platfrom_id = get_platform_id(ev)
    user_bind: List[PCRBind] = await pcr_sqla.get_bind(platfrom_id, qid)
    if not user_bind:
        await bot.send(ev, '您还没有绑定竞技场！')
        return
    gid = ev.group_id
    member_info = await bot.get_group_member_info(group_id=gid, user_id=qid)
    name = member_info["card"] or member_info["nickname"]
    reply = f'{name}（{qid}）的竞技场订阅列表：\n\n群号：{user_bind[0].group}\n推送方式：{"私聊推送" if user_bind[0].private else "群聊推送"}\n'
    for i, bind in enumerate(user_bind):
        reply += f'\n【{i+1}】{bind.name}（{bind.pcrid}）\n'
        reply += f"服务器：{get_tw_platform(bind.pcrid)}\n"
        noticeType = '推送内容：'
        if bind.jjc_notice:
            noticeType += 'jjc、'
        if bind.pjjc_notice:
            noticeType += 'pjjc、'
        if bind.up_notice:
            noticeType += '排名上升、'
        if bind.online_notice:
            noticeType += f'上线提醒LV{bind.online_notice}、'

        if noticeType == '推送内容：':
            noticeType += '无'
        else:
            noticeType = noticeType.strip('、')

        reply += noticeType + '\n'
    reply += '###上线提醒LV越高，提醒越频繁。详情见竞技场帮助\n'
    await bot.send(ev, f'[CQ:image,file={image_draw(reply)}]')


@sv_tw.on_rex(r'^台?(?:击剑|竞技场)记录 ?(\d)?$')
async def jjc_log_query(bot: HoshinoBot, ev: CQEvent):
    qid = get_qid(ev)
    platform_id = get_platform_id(ev)
    user_bind: List[PCRBind] = await pcr_sqla.get_bind(platform_id, qid)

    if not user_bind:
        await bot.send(ev, '您还没有绑定竞技场！')
        return

    ret: re.Match = ev["match"]
    pcrid_id_input = int(ret.group(1)) if ret.group(1) else 0

    if pcrid_id_input > len(user_bind):
        await bot.send(ev, '序号超出范围，请检查您绑定的竞技场列表')
        return

    msg = '没有击剑记录！'
    member_info = await bot.get_group_member_info(group_id=ev.group_id, user_id=qid)
    if jjc_historys := await pcr_sqla.get_history(platform_id, qid, user_bind[pcrid_id_input-1].pcrid if pcrid_id_input else 0):
        msg = f'\t\t\t\t【{member_info["card"] or member_info["nickname"]}的击剑记录】\n' + "\n".join(
            [f"{datetime.fromtimestamp(history.date).strftime('%H:%M:%S')} {history.name} {'jjc ' if not history.item else 'pjjc'}：{history.before}->{history.after} [{'▲' if history.before > history.after else '▽'}{abs(history.after-history.before)}]"
             for history in jjc_historys])

    await bot.send(ev, f'[CQ:image,file={image_draw(msg)}]')

# ========================================竞技场绑定========================================


@sv_tw.on_rex(r'^台?竞技场绑定 ?(\d+) ?(\S+)?$')
async def on_arena_bind(bot: HoshinoBot, ev: CQEvent):
    ret: re.Match = ev["match"]
    if len(nickname := ret.group(2) if ret.group(2) else "") > 12:
        await bot.send(ev, '昵称不能超过12个字，换个短一点的昵称吧~')
        return
    pcr_id = int(ret.group(1))
    platform_id = get_platform_id(ev)
    await query_all([PCRBind(platform=platform_id, pcrid=pcr_id, name=nickname, group=ev.group_id, user_id=ev.user_id)], platform_id, bind_pcrid,
                {"bot": bot, "ev": ev, "info": {"platform": platform_id, "pcrid": pcr_id, "name": nickname, "group": ev.group_id, "user_id": ev.user_id}}, Priority.bind.value)


@sv_tw.on_rex(r'^台?删除竞技场绑定 ?(\d)?$')
async def delete_arena_sub(bot: HoshinoBot, ev: CQEvent):
    qid = ev.user_id
    ret: re.Match = ev["match"]
    if not ret.group(1):
        await bot.send(ev, '输入格式不对！“删除竞技场绑定+【序号】”（序号不可省略）')
        return
    platform_id = get_platform_id(ev)
    user_bind: List[PCRBind] = await pcr_sqla.get_bind(platform_id, qid)
    pcrid_num = len(user_bind)
    if 0 < (pcrid_id := int(ret.group(1))) <= pcrid_num:
        delete_bind = user_bind[pcrid_id-1]
        result = f'您已成功删除：【{pcrid_id}】{delete_bind.name}（{delete_bind.pcrid}）'
        await pcr_sqla.delete_bind(qid, platform_id, delete_bind.pcrid)
        await bot.send(ev, result)
    else:
        await bot.send(ev, '输入的序号超出范围！')


@sv_tw.on_fullmatch('台清空竞技场绑定')
@sv_tw.on_fullmatch('清空竞技场绑定')
async def pcrjjc_del(bot: HoshinoBot, ev: CQEvent):
    qid = ev.user_id
    platform_id = get_platform_id(ev)
    user_bind: List[PCRBind] = await pcr_sqla.get_bind(platform_id, qid)
    if not user_bind:
        await bot.send(ev, '您还没有绑定竞技场！')
        return
    reply = '删除成功！\n' + \
        "\n".join([f'【{i+1}】{bind.name}\n（{bind.pcrid}）' for i,
                  bind in enumerate(user_bind)])
    await pcr_sqla.delete_bind(qid, platform_id)
    await bot.send(ev, reply)

# ========================================竞技场设置========================================


@sv_tw.on_rex(r'^台?竞技场修改昵称 ?(\d)? (\S+)$')
async def change_nickname(bot: HoshinoBot, ev: CQEvent):
    qid = ev.user_id
    platform_id = get_platform_id(ev)
    user_bind: List[PCRBind] = await pcr_sqla.get_bind(platform_id, qid)

    if not user_bind:
        await bot.send(ev, '您还没有绑定竞技场！')
        return

    pcrid_num = len(user_bind)
    ret: re.Match = ev["match"]
    if not (pcrid_id := ret.group(1)) and pcrid_num != 1:
        await bot.send(ev, '您绑定了多个uid，更改昵称时需要加上序号。')
        return

    pcrid_id = int(pcrid_id) if pcrid_id else 1

    if len(ret.group(2)) > 12:
        await bot.send(ev, '昵称不能超过12个字，换个短一点的昵称吧~')
        return

    if pcrid_id > pcrid_num or not pcrid_num:
        await bot.send(ev, '序号超出范围，请检查您绑定的竞技场列表')
        return

    name = ret.group(2)
    await pcr_sqla.update_bind(platform_id, {"name": name}, qid, user_bind[pcrid_id-1].pcrid)
    await bot.send(ev, '更改成功！')


@sv_tw.on_fullmatch('台在本群推送')
@sv_tw.on_fullmatch('在本群推送')
async def group_set(bot: HoshinoBot, ev: CQEvent):
    await pcr_sqla.update_bind(get_platform_id(ev), {"group": ev.group_id, "private": False}, ev.user_id)
    await bot.send(ev, '设置成功！已为您开启推送。')


@on_command('private_notice', aliases=('换私聊推送', '台换私聊推送'), only_to_me=False)
async def private_notice(session: NoticeSession):
    platform_id = get_platform_id(session.event)
    if len(await pcr_sqla.get_private(platform_id)) >= private_dict[platform_id]:
        await session.send('私聊推送用户已达上限！')
        return
    if session.ctx['message_type'] != 'private':
        await session.send('仅限好友私聊使用！')
        return
    bot = get_bot()
    qid = session.ctx['user_id']
    await pcr_sqla.update_bind(platform_id, {"private": True}, qid)
    await session.send('设置成功！已为您开启推送。已通知管理员！')
    await bot.send_private_msg(user_id=SUPERUSERS[0], message=f'{qid}开启了私聊jjc推送！')


@sv_tw.on_rex(r'^台?竞技场设置 ?(开启|关闭) ?(jjc|pjjc|排名上升|上线提醒) ?(\d)?$')
async def set_noticeType(bot: HoshinoBot, ev: CQEvent):
    qid = ev.user_id
    ret: re.Match = ev["match"]
    turn_on = True if str(ret.group(1)) == '开启'else False
    change = ret.group(2)
    platform_id = get_platform_id(ev)
    user_bind: List[PCRBind] = await pcr_sqla.get_bind(platform_id, qid)

    if not user_bind:
        await bot.send(ev, '您还没有绑定jjc，绑定方式：\n[竞技场绑定 uid] uid在pcr个人简介里')
        return

    pcrid_num = len(user_bind)  # 这个qq号绑定的pcrid个数
    pcrid_id = int(ret.group(3)) if ret.group(
        3) else 1 if pcrid_num == 1 else -1

    if 0 <= pcrid_id <= pcrid_num:  # 设置成功！
        if change == 'jjc':
            change_dict = {"jjc_notice": turn_on}
        elif change == 'pjjc':
            change_dict = {"pjjc_notice": turn_on}
        elif change == '排名上升':
            change_dict = {"up_notice": turn_on}
        elif change == '上线提醒':
            change_dict = {"online_notice": 1 if turn_on else 0}
        reply = '设置成功！'
        await pcr_sqla.update_bind(platform_id, change_dict, qid, user_bind[pcrid_id-1].pcrid if pcrid_id else None)
    else:
        reply = '序号超出范围或者绑定多个没填序号，请检查您绑定的竞技场列表'

    await bot.send(ev, reply)


@sv_tw.on_rex(r'^台?竞技场设置 ?([01]{3}[0123]) ?(\d)?$')
async def set_allType(bot: HoshinoBot, ev: CQEvent):
    qid = ev.user_id
    platform_id = get_platform_id(ev)
    user_bind: List[PCRBind] = await pcr_sqla.get_bind(platform_id, qid)
    if not user_bind:
        await bot.send(ev, '您还没有绑定竞技场！')
        return
    ret: re.Match = ev["match"]
    pcrid_num = len(user_bind)
    change: str = ret.group(1)
    pcrid_id = int(ret.group(2)) if ret.group(
        2) else 1 if pcrid_num == 1 else -1
    if 0 <= pcrid_id <= pcrid_num:
        change_dict = {}
        change_dict["jjc_notice"] = bool(int(change[0]))
        change_dict["pjjc_notice"] = bool(int(change[1]))
        change_dict["up_notice"] = bool(int(change[2]))
        change_dict["online_notice"] = int(change[3])
        reply = '设置成功！'
        await pcr_sqla.update_bind(platform_id, change_dict, qid, user_bind[pcrid_id-1].pcrid if pcrid_id else None)
    else:
        reply = '序号超出范围或者绑定多个没填序号，请检查您绑定的竞技场列表'
    await bot.send(ev, reply)

# ========================================管理员指令========================================


@sv_tw.on_fullmatch('pcrjjc负载查询')
async def load_query(bot: HoshinoBot, ev: CQEvent):
    if not priv.check_priv(ev, priv.SUPERUSER):
        return
    load: LoadBase = await pcr_sqla.query_load()
    msg = f'''pcrjjc负载：
台服：
群聊用户数量：{load.tw_group_user} 群聊绑定的uid：{load.tw_group_pcrid}个
私聊用户数量：{load.tw_private_user} 私聊绑定的uid：{load.tw_private_pcrid}个
昨天推送次数：{load.tw_yesterday_send} 今天推送次数：{load.tw_today_send}'''
    pic = image_draw(msg)
    await bot.send(ev, f'[CQ:image,file={pic}]')


@sv_tw.on_fullmatch('台pcrjjc关闭私聊推送')
@sv_tw.on_fullmatch('pcrjjc关闭私聊推送')
async def no_private(bot: HoshinoBot, ev: CQEvent):
    if not priv.check_priv(ev, priv.SUPERUSER):
        return
    platform_id = get_platform_id(ev)
    await pcr_sqla.update_bind(platform_id, {"private": False})
    await bot.send(ev, '所有设置为私聊推送的用户的推送已关闭！')


@sv_tw.on_rex(r'^台?pcrjjc删除绑定 ?(\d{6,10})')
async def del_binds(bot: HoshinoBot, ev: CQEvent):
    if not priv.check_priv(ev, priv.SUPERUSER):
        return
    ret: re.Match = ev["match"]
    qid = int(ret.group(1))
    platform_id = get_platform_id(ev)
    user_bind: List[PCRBind] = await pcr_sqla.get_bind(platform_id, qid)
    if user_bind:
        await pcr_sqla.delete_bind(qid, platform_id)
        reply = '删除成功！'
    else:
        reply = '绑定列表中找不到这个qq号！'
    await bot.send(ev, reply)

# ========================================头像框========================================

# 头像框配置与图片目录
FRAME_DIR = os.path.join(os.path.dirname(__file__), 'img/img/frame')
FRAME_CONF = os.path.join(os.path.dirname(__file__), 'img/frame.json')

# 头像框设置文件不存在就创建文件，并且默认彩色
if not os.path.exists(FRAME_CONF):
    data = {"default_frame": "color.png", "customize": {}}
    with open(FRAME_CONF, 'w', encoding='UTF-8') as f:
        dump(data, f, indent=4, ensure_ascii=False)


@sv_tw.on_rex(r'^台?详细查询 ?(\d+)?$')
async def on_query_arena_all(bot: HoshinoBot, ev: CQEvent):
    ret: re.Match = ev['match']
    id = ret.group(1)
    if not id:
        await bot.send(ev, '请在详细查询后带上uid或编号', at_sender=True)
        return
    qid = get_qid(ev)
    platform_id = get_platform_id(ev)
    user_bind: List[PCRBind] = await pcr_sqla.get_bind(platform_id, qid)
    if len(id) == 1:
        if not user_bind:
            await bot.send(ev, '您还未绑定竞技场', at_sender=True)
            return
        if len(user_bind) < int(id):
            await bot.send(ev, '输入的序号超出范围，可发送竞技场查询查看你的绑定', at_sender=True)
            return
    bind = PCRBind(platform=platform_id, pcrid=int(id)) if len(
        id) > 1 else user_bind[int(id) - 1]
    await query_all([bind], platform_id, detial_query, {"bot": bot, "ev": ev, "platform":platform_id}, Priority.detial_query.value)


# on_prefix 会剥掉命令头，函数里 extract_plain_text() 拿到的就是 uid 列表
@sv_tw.on_prefix('台深域查询')
@sv_tw.on_prefix('深域查询')
async def on_query_talent(bot: HoshinoBot, ev: CQEvent):
    uid_args = ev.message.extract_plain_text().strip().split()
    if not uid_args or any(not uid.isdigit() for uid in uid_args):
        await bot.send(ev, '格式：深域查询 uid1 uid2 ...')
        return

    uids = list(dict.fromkeys(int(uid) for uid in uid_args))
    platform_id = get_platform_id(ev)
    query_list = [PCRBind(platform=platform_id, pcrid=uid) for uid in uids]
    talent_cache[ev.user_id] = []
    await query_all(
        query_list,
        platform_id,
        talent_query,
        {"bot": bot, "ev": ev, "query_count": len(query_list)},
        Priority.query_talent.value,
    )


# hoshino 的 on_prefix 只接受一个前缀，多个写法只能叠加装饰器，不能写成多个参数
@sv_tw.on_prefix('台竞技场换头像框')
@sv_tw.on_prefix('台更换竞技场头像框')
@sv_tw.on_prefix('台更换头像框')
@sv_tw.on_prefix('竞技场换头像框')
@sv_tw.on_prefix('更换竞技场头像框')
@sv_tw.on_prefix('更换头像框')
async def change_frame(bot: HoshinoBot, ev: CQEvent):
    user_id = str(ev.user_id)
    frame_tmp = ev.message.extract_plain_text().strip()
    frame_list = os.listdir(FRAME_DIR)
    if not frame_list:
        await bot.send(ev, 'img/img/frame/路径下没有任何头像框，请联系维护组检查目录')
        return
    if frame_tmp not in frame_list:
        msg = f'文件名输入错误，命令样例：\n更换头像框 color.png\n目前可选文件有：\n' + \
            '\n'.join(frame_list)
        await bot.send(ev, msg)
        return
    with open(FRAME_CONF, 'r', encoding='UTF-8') as f:
        f_data = load(f)
    f_data.setdefault('customize', {})[user_id] = frame_tmp
    with open(FRAME_CONF, 'w', encoding='UTF-8') as rf:
        dump(f_data, rf, indent=4, ensure_ascii=False)
    await bot.send(ev, f'已成功选择头像框:{frame_tmp}')
    frame_path = os.path.join(FRAME_DIR, frame_tmp)
    msg = MessageSegment.image(f'file:///{os.path.abspath(frame_path)}')
    await bot.send(ev, msg)


@sv_tw.on_fullmatch('台查竞技场头像框')
@sv_tw.on_fullmatch('台查询竞技场头像框')
@sv_tw.on_fullmatch('台查询头像框')
@sv_tw.on_fullmatch('查竞技场头像框')
@sv_tw.on_fullmatch('查询竞技场头像框')
@sv_tw.on_fullmatch('查询头像框')
async def see_a_see_frame(bot: HoshinoBot, ev: CQEvent):
    user_id = str(ev.user_id)
    with open(FRAME_CONF, 'r', encoding='UTF-8') as f:
        f_data = load(f)
    frame_tmp = f_data.get('customize', {}).get(user_id) or f_data['default_frame']
    path = os.path.join(FRAME_DIR, frame_tmp)
    msg = MessageSegment.image(f'file:///{os.path.abspath(path)}')
    await bot.send(ev, msg)

# ========================================AUTO========================================


@on_startup
async def on_arena_schedule():
    # 两步分开 try，任何一步失败都要留下明确日志，而不是让整个启动静默中断
    try:
        count = await refresh_account()
    except Exception:
        count = 0
        logger.error(f"账号表刷新失败：\n{traceback.format_exc()}")
    if not count:
        logger.error("没有读到任何台服账号，自动推送无法启动，请运行 python check_account.py")

    # 等级表缺失不会让插件挂掉，但详细查询的等级栏会变成「未知」，启动时先说清楚
    if read_knight_exp_rank(0) is None:
        logger.error("公主骑士等级表 rank_exp.csv 缺失或损坏，详细查询 / 深域查询里的等级将显示「未知」")

    try:
        await login_all()
    except Exception:
        logger.error(f"账号登录流程异常：\n{traceback.format_exc()}")

    tw1 = bool(queue_dict[Platform.tw_id.value])
    other = bool(queue_dict[Platform.tw_other_id.value])
    logger.info(f"自动推送启动状态：台一队列={'已就绪' if tw1 else '未就绪'}，台其他队列={'已就绪' if other else '未就绪'}")
    if not (tw1 or other):
        logger.error("两个队列都没有起来，所有查询都会被忽略，请检查上面的错误日志")

    # 绑定都记在台服平台id下，由 query_all 按 uid 首段分流到台一 / 台其他队列
    if tw1 or other:
        asyncio.get_event_loop().create_task(query_loop(Platform.tw_id.value))


@sv_tw.on_notice('group_decrease.leave', 'group_decrease.kick')
async def leave_notice(session: NoticeSession):
    uid = session.ctx['user_id']
    gid = session.ctx['group_id']
    if await pcr_sqla.get_bind(user_id=uid, group=gid):
        bot = get_bot()
        await pcr_sqla.delete_bind(uid, group=gid)
        await bot.send_group_msg(group_id=gid, message=f'{uid}退群了，已自动删除其绑定在本群的竞技场订阅推送')
