"""账号文件自检脚本（不依赖 nonebot / sqlalchemy，可单独运行）

用法：
    python check_account.py                # 检查插件目录下的 account/
    python check_account.py D:\\some\\dir    # 检查指定目录

它会列出：扫描到哪些 xml、每个文件能否解析、解析出的 viewer_id 属于哪个区，
以及是否存在「某一区没有账号」导致查询被忽略的问题。
"""
import sys
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIELD_ALIASES = {
    "VIEWER_ID_lowBits": ("VIEWER_ID_lowBits", "VIEWER_ID"),
    "UDID": ("UDID",),
    "SHORT_UDID_lowBits": ("SHORT_UDID_lowBits", "SHORT_UDID"),
}
TW_AREA = {1: "台一·美食殿堂", 2: "台二·真步真步王国", 3: "台三·破晓之星", 4: "台四·小小甜心"}


def pick(data: dict, *names):
    for name in names:
        if data.get(name):
            return data[name]
    return None


def load_decryptxml():
    """直接按路径加载 playerpref.py，绕开包导入（避免依赖 nonebot）"""
    spec = importlib.util.spec_from_file_location(
        "_playerpref", HERE / "client" / "playerpref.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.decryptxml


def mask(text: str) -> str:
    text = str(text)
    return text if len(text) <= 10 else f"{text[:4]}...{text[-4:]}"


def main() -> int:
    target = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else HERE / "account"
    target = target.resolve()

    print(f"账号目录：{target}")
    if not target.is_dir():
        print("  [×] 目录不存在。请确认路径，或先创建该目录再放入 xml。")
        return 1

    all_files = [p for p in target.rglob("*") if p.is_file()]
    xml_files = sorted(p for p in all_files if p.suffix.lower() == ".xml")

    if not xml_files:
        print(f"  [×] 没有找到 .xml 文件（该目录下有 {len(all_files)} 个文件）")
        for p in all_files:
            print(f"      - {p.name}  ← 扩展名不是 .xml，不会被读取")
        print("\n请把 tw.sonet.princessconnect.v2.playerprefs.xml 复制到上面的目录。")
        return 1

    print(f"  找到 {len(xml_files)} 个 xml：\n")
    decryptxml = load_decryptxml()
    ok, used = [], {}

    for f in xml_files:
        print(f"  · {f.relative_to(target)}")
        try:
            data = decryptxml(str(f))
        except Exception as e:
            print(f"      [×] 读取失败：{type(e).__name__}: {e}")
            continue

        fields = {k: pick(data, *FIELD_ALIASES[k]) for k in FIELD_ALIASES}
        missing = [k for k, v in fields.items() if not v]
        if missing:
            parsed = ", ".join(sorted(data)) or "（什么都没解析出来）"
            print(f"      [×] 缺少字段 {missing}")
            print(f"          实际解析到的字段：{parsed}")
            print("          常见原因：文件不是 playerprefs、被截断，或是旧版格式")
            continue

        viewer_id = str(fields["VIEWER_ID_lowBits"]).strip()
        if not viewer_id.isdigit():
            print(f"      [×] viewer_id 不是数字：{viewer_id!r}")
            continue
        if viewer_id in used:
            print(f"      [×] viewer_id 与 {used[viewer_id]} 重复：{viewer_id}")
            continue

        used[viewer_id] = f.name
        area = int(viewer_id) // 1000000000
        area_name = TW_AREA.get(area, f"未知区({area})")
        print(f"      [√] viewer_id = {viewer_id}   区服：{area_name}")
        if area not in TW_AREA:
            print("          [!] 首段不是 1-4，通常是 uid 位数不对（台服应为 10 位），请确认文件是否正确")
        print(f"          UDID = {mask(fields['UDID'])}   SHORT_UDID = {mask(fields['SHORT_UDID_lowBits'])}")
        ok.append((viewer_id, area, f.name))

    if not ok:
        print("\n结果：没有任何一个账号可用，自动推送会全部失效。")
        return 1

    has_tw1 = any(area == 1 for _, area, _ in ok)
    has_other = any(area != 1 for _, area, _ in ok)

    print(f"\n结果：{len(ok)} 个账号可用")
    for viewer_id, area, name in ok:
        print(f"  - {viewer_id}  {TW_AREA.get(area, f'未知区({area})')}  ← {name}")
    if not has_tw1:
        print("  [!] 没有台一账号 → 台一 uid 的查询会被忽略")
    if not has_other:
        print("  [!] 没有台二/三/四账号 → 这些区的查询会被忽略"
              "（运行时会提示『未绑定台其他服务器的查询账户』）")
    if has_tw1 and has_other:
        print("  台一与台其他都有账号，配置完整。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
