from msgpack import packb, unpackb
from random import randint
from hashlib import md5, sha1
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad, pad
from base64 import b64encode, b64decode
from random import choice
from datetime import datetime
import requests
import os
import json
from hoshino.aiorequests import post
from nonebot import logger
import re

# 读取代理配置
with open(os.path.join(os.path.dirname(__file__), "proxy.json")) as fp:
    pinfo = json.load(fp)

# ---------------- 台服 APP 版本号（APP-VER） ----------------
PLAY_URL = "https://play.google.com/store/apps/details?id=tw.sonet.princessconnect"
# App Store 台区接口，返回 JSON，不用解析 HTML，最稳
ITUNES_URL = "https://itunes.apple.com/lookup?bundleId=tw.sonet.princessconnect&country=tw"
# 拿到的版本号落盘，下次启动时即便网络不通也能用
VER_CACHE = os.path.join(os.path.dirname(__file__), "tw_ver.txt")
# 所有来源都失败时的兜底值，台服大版本更新后可手动改这里
DEFAULT_APP_VER = "5.9.0"
# 进程内缓存的有效期，超过就重新取（长期运行的 bot 不会一直用旧版本号）
VER_TTL = 6 * 3600

# Play 页面 AF_initDataCallback 里的版本位，形如 ...]]],[[["5.9.0"]],[[[36]]...
# 不依赖页面文案与语言，hl 传什么都不影响
_APP_VER_RE = re.compile(r'\[\[\["(\d+\.\d+\.\d+)"\]\],\[\[\[\d+\]\]')
_VER_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{1,3}$")

_app_ver = ""      # 进程内缓存的版本号
_app_ver_time = 0  # 缓存时间戳


def _valid_ver(ver) -> str:
    """只接受 5.9.0 这种格式，避免把奇怪的东西塞进请求头"""
    if isinstance(ver, str) and _VER_RE.match(ver.strip()):
        return ver.strip()
    return ""


def _read_cache() -> str:
    try:
        with open(VER_CACHE, encoding="utf-8") as fp:
            return _valid_ver(fp.read())
    except OSError:
        return ""


def _write_cache(ver: str):
    try:
        with open(VER_CACHE, "w", encoding="utf-8") as fp:
            fp.write(ver)
    except OSError:
        pass


def _ver_from_itunes() -> str:
    res = requests.get(ITUNES_URL, timeout=10, proxies=pinfo.get("proxy"))
    data = res.json()
    if data.get("resultCount"):
        return _valid_ver(str(data["results"][0].get("version", "")))
    return ""


def _ver_from_play() -> str:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Cache-Control": "max-age=0",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/115.0.0.0 Safari/537.36 Edg/115.0.1901.183",
        "Upgrade-Insecure-Requests": "1",
        "Pragma": "no-cache",
    }
    app_res = requests.get(
        PLAY_URL, headers=headers, timeout=15, proxies=pinfo.get("proxy")
    )
    match = _APP_VER_RE.search(app_res.text)
    return _valid_ver(match.group(1)) if match else ""


def get_ver(force: bool = False) -> str:
    """
    取台服当前 APP 版本（填进请求头 APP-VER）
    取用顺序：进程缓存 -> App Store -> Google Play -> 本地缓存文件 -> 兜底常量
    任何一环失败都不会抛出，保证客户端能构造出来
    """
    global _app_ver, _app_ver_time
    if _app_ver and not force and datetime.now().timestamp() - _app_ver_time < VER_TTL:
        return _app_ver

    for name, fetch in (("App Store", _ver_from_itunes), ("Google Play", _ver_from_play)):
        try:
            if ver := fetch():
                logger.info(f"台服 APP 版本号（来源 {name}）：{ver}")
                _app_ver, _app_ver_time = ver, datetime.now().timestamp()
                _write_cache(ver)
                return ver
            logger.warning(f"{name} 的返回里没解析到版本号")
        except Exception as e:
            logger.warning(f"从 {name} 获取台服版本号失败：{type(e).__name__} {e}")

    if ver := _read_cache():
        logger.warning(f"在线获取版本号失败，改用本地缓存：{ver}")
        _app_ver, _app_ver_time = ver, datetime.now().timestamp()
        return ver

    logger.warning(
        f"台服版本号获取全部失败，使用兜底值 {DEFAULT_APP_VER}，若登录报版本错误请检查网络或手动更新"
    )
    _app_ver, _app_ver_time = DEFAULT_APP_VER, datetime.now().timestamp()
    return DEFAULT_APP_VER


# 获取headers
def get_headers():
    app_ver = get_ver()
    default_headers = {
        "Accept-Encoding": "gzip",
        "User-Agent": "Dalvik/2.1.0 (Linux, U, Android 5.1.1, PCRT00 Build/LMY48Z)",
        "Content-Type": "application/octet-stream",
        "Expect": "100-continue",
        "X-Unity-Version": "2018.4.21f1",
        "APP-VER": app_ver,
        "BATTLE-LOGIC-VERSION": "4",
        "BUNDLE-VER": "",
        "DEVICE": "2",
        "DEVICE-ID": "7b1703a5d9b394e24051d7a5d4818f17",
        "DEVICE-NAME": "OPPO PCRT00",
        "GRAPHICS-DEVICE-NAME": "Adreno (TM) 640",
        "IP-ADDRESS": "10.0.2.15",
        "KEYCHAIN": "",
        "LOCALE": "Jpn",
        "PLATFORM-OS-VERSION": "Android OS 5.1.1 / API-22 (LMY48Z/rel.se.infra.20200612.100533)",
        "REGION-CODE": "",
        "RES-VER": "00017004",
    }
    return default_headers


class ApiException(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class pcrclient:
    @staticmethod
    def _makemd5(str) -> str:
        return md5((str + "r!I@nt8e5i=").encode("utf8")).hexdigest()

    def __init__(self, udid, short_udid, viewer_id, platform):
        platform = str(platform)
        self.viewer_id = viewer_id
        self.short_udid = short_udid
        self.udid = udid
        self.proxy = pinfo["proxy"]
        self.token = pcrclient.createkey()
        self.headers = get_headers().copy()

        self.headers["SID"] = pcrclient._makemd5(viewer_id + udid)
        if platform == "1":
            self.apiroot = f"https://api-pc.so-net.tw"
        else:
            self.apiroot = f"https://api5-pc.so-net.tw"
        self.headers["platform"] = "2"
        self.platform = platform
        self.shouldLogin = False

    @staticmethod
    def createkey() -> bytes:
        return bytes([ord("0123456789abcdef"[randint(0, 15)]) for _ in range(32)])

    def _getiv(self) -> bytes:
        return self.udid.replace("-", "")[:16].encode("utf8")

    def pack(self, data: object, key: bytes) -> tuple:
        aes = AES.new(key, AES.MODE_CBC, self._getiv())
        packed = packb(data, use_bin_type=False)
        return packed, aes.encrypt(pad(packed, 16)) + key

    def encrypt(self, data: str, key: bytes) -> bytes:
        aes = AES.new(key, AES.MODE_CBC, self._getiv())
        return aes.encrypt(pad(data.encode("utf8"), 16)) + key

    def decrypt(self, data: bytes):
        data = b64decode(data.decode("utf8"))
        aes = AES.new(data[-32:], AES.MODE_CBC, self._getiv())
        return aes.decrypt(data[:-32]), data[-32:]

    def unpack(self, data: bytes):
        data = b64decode(data.decode("utf8"))
        aes = AES.new(data[-32:], AES.MODE_CBC, self._getiv())
        dec = unpad(aes.decrypt(data[:-32]), 16)
        return unpackb(dec, strict_map_key=False), data[-32:]

    alphabet = "0123456789"

    @staticmethod
    def _encode(dat: str) -> str:
        return (
            f"{len(dat):0>4x}"
            + "".join(
                [
                    (
                        chr(ord(dat[int(i / 4)]) + 10)
                        if i % 4 == 2
                        else choice(pcrclient.alphabet)
                    )
                    for i in range(0, len(dat) * 4)
                ]
            )
            + pcrclient._ivstring()
        )

    @staticmethod
    def _ivstring() -> str:
        return "".join([choice(pcrclient.alphabet) for _ in range(32)])

    async def callapi(self, apiurl: str, request: dict, noerr: bool = False):
        key = pcrclient.createkey()
        try:
            if self.viewer_id is not None:
                request["viewer_id"] = b64encode(self.encrypt(str(self.viewer_id), key))
                request["tw_server_id"] = str(self.platform)
            packed, crypted = self.pack(request, key)
            self.headers["PARAM"] = sha1(
                (
                    self.udid
                    + apiurl
                    + b64encode(packed).decode("utf8")
                    + str(self.viewer_id)
                ).encode("utf8")
            ).hexdigest()
            self.headers["SHORT-UDID"] = pcrclient._encode(self.short_udid)
            resp = await post(
                self.apiroot + apiurl,
                data=crypted,
                headers=self.headers,
                timeout=5,
                proxies=self.proxy,
                verify=False,
            )
            response = await resp.content

            response = self.unpack(response)[0]
            data_headers = response["data_headers"]
            if "viewer_id" in data_headers:
                self.viewer_id = data_headers["viewer_id"]
            if "required_res_ver" in data_headers:
                self.headers["RES-VER"] = data_headers["required_res_ver"]

            data = response["data"]
            if not noerr and "server_error" in data:
                data = data["server_error"]
                code = data_headers["result_code"]
                print(f"pcrclient: {apiurl} api failed code = {code}, {data}")
                raise ApiException(data["message"], data["status"])
            # print(f'pcrclient: {apiurl} api called')
            # 生成角色信息json文件，用于调试
            # json_data = json.dumps(data, indent=4, ensure_ascii=False)
            # data_path =  Path(__file__).parent / 'res_data.json'
            # data_path.write_text(json_data, encoding="utf-8")
            return data
        except:
            self.shouldLogin = True
            raise

    async def login(self):
        # 重连时顺带刷新 APP-VER，长期运行的 bot 不用重启也能跟上台服更新
        self.headers["APP-VER"] = get_ver()

        await self.callapi("/check/check_agreement", {})
        await self.callapi("/check/game_start", {})
        await self.callapi("/load/index", {"carrier": "Android"})
        self.shouldLogin = False
