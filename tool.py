from pathlib import Path

from nonebot import logger

from .database.dal import pcr_sqla
from .client.playerpref import decryptxml

account_path = Path(__file__).parent / "account"

# playerprefs 里必须能解析出的字段，缺任意一个都说明这个 xml 没被正确识别
# 值是对应的字段别名，兼容 lowBits 与不带后缀两种命名
FIELD_ALIASES = {
    "VIEWER_ID_lowBits": ("VIEWER_ID_lowBits", "VIEWER_ID"),
    "UDID": ("UDID",),
    "SHORT_UDID_lowBits": ("SHORT_UDID_lowBits", "SHORT_UDID"),
}
REQUIRED_KEYS = tuple(FIELD_ALIASES)

# viewer_id 首位决定区服：1=台一，2/3/4=台二/三/四
TW_AREA = {1: "美食殿堂", 2: "真步真步王国", 3: "破晓之星", 4: "小小甜心"}


def find_xml_files() -> list:
    """递归扫描 account 目录，扩展名不区分大小写（兼容 .xml / .XML）"""
    return sorted(
        p for p in account_path.rglob("*")
        if p.is_file() and p.suffix.lower() == ".xml"
    )


def pick(data: dict, *names):
    """按顺序取第一个非空字段，兼容 lowBits / 不带后缀两种命名"""
    for name in names:
        if data.get(name):
            return data[name]
    return None


def parse_accounts() -> list:
    """解析 account 目录下的 playerprefs xml，任何异常都只跳过单个文件并说明原因"""
    if not account_path.is_dir():
        logger.error(
            f"账号目录不存在：{account_path}。"
            "请创建该目录并放入 playerprefs xml 后重启 bot。"
        )
        return []

    files = find_xml_files()

    if not files:
        logger.error(
            f"未在 {account_path} 找到任何 .xml 账号文件，自动推送无法登录，"
            "所有查询/绑定都会被忽略。请把 tw.sonet.princessconnect.v2.playerprefs.xml "
            "复制到该目录后重启 bot。"
        )
        return []

    accounts: list = []
    used = {}  # viewer_id -> 文件名，用于提示重复

    for xml_file in files:
        try:
            data = decryptxml(str(xml_file))
        except Exception as e:
            logger.error(f"读取账号文件失败：{xml_file.name}（{type(e).__name__}: {e}）")
            continue

        fields = {k: pick(data, *FIELD_ALIASES[k]) for k in REQUIRED_KEYS}
        missing = [k for k, v in fields.items() if not v]
        if missing:
            logger.error(
                f"账号文件 {xml_file.name} 解析不出 {missing}，已跳过。"
                "常见原因：不是 playerprefs.xml、文件被截断/编码损坏，或是旧版格式。"
            )
            continue

        viewer_id = str(fields["VIEWER_ID_lowBits"]).strip()
        udid = fields["UDID"]
        short_udid = fields["SHORT_UDID_lowBits"]

        if not viewer_id.isdigit():
            logger.error(
                f"账号文件 {xml_file.name} 解析出的 VIEWER_ID 不是数字：{viewer_id!r}，已跳过"
            )
            continue
        if viewer_id in used:
            logger.warning(
                f"账号文件 {xml_file.name} 与 {used[viewer_id]} 的 viewer_id 重复"
                f"（{viewer_id}），已忽略后者"
            )
            continue

        used[viewer_id] = xml_file.name
        accounts.append({
            "viewer_id": viewer_id,
            "account": udid,
            "password": short_udid,
            "platform": 2,
        })

    if not accounts:
        logger.error(
            f"{account_path} 下有 {len(files)} 个 xml，但没有一个解析成有效账号，"
            "自动推送将不可用。可运行 python check_account.py 查看具体原因。"
        )
        return accounts

    has_tw1 = has_other = False
    for acc in accounts:
        area = int(acc["viewer_id"]) // 1000000000
        area_name = TW_AREA.get(area, f"未知区({area})")
        logger.info(
            f"读取台服账号：viewer_id={acc['viewer_id']}"
            f"（{area_name}）← {used[acc['viewer_id']]}"
        )
        if area not in TW_AREA:
            logger.warning(
                f"viewer_id={acc['viewer_id']} 首段不是 1-4，"
                "会被当成台二/三/四处理，可能查不到对应区的玩家，请确认是不是复制错了文件"
            )
        if area == 1:
            has_tw1 = True
        else:
            has_other = True

    # 这两条正好对应运行时「未绑定 XX 服务器的查询账户」的警告来源
    if not has_tw1:
        logger.warning(
            "没有台一（美食殿堂）的登录账号：台一的 uid 查询与推送都会被忽略"
        )
    if not has_other:
        logger.warning(
            "没有台二/三/四的登录账号：这些区的 uid 查询与推送都会被忽略"
            "（即『未绑定台其他服务器的查询账户』）"
        )

    return accounts


async def refresh_account():
    """启动时重建账号表；每次都重新扫描目录，避免 import 时目录还空着"""
    acinfo = parse_accounts()
    await pcr_sqla._create_all()
    await pcr_sqla.delete_all_account()
    if acinfo:
        await pcr_sqla.insert_account(acinfo)
    logger.info(f"账号表刷新完成，共 {len(acinfo)} 个台服登录账号")
    return len(acinfo)
