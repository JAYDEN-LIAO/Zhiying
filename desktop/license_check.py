"""desktop/license_check.py — 软件管家 License 校验（照抄云侠 license.ts 逻辑，移植 Python）。

校验在桌面壳启动时执行（iss 安装器不校验），流程：
  1. 读注册表 HKLM\\Software\\TuoJie\\TJHouseKeeper 的 Path → 软件管家安装目录
  2. 解析 exe 同级 license.dat：RC4（密钥 gn9xswy）→ 跳过 1024 字节 → 定长字段
     （licenseType: 0=试用 / 1=正式；含过期年月日与加密狗名/密码）
  3. 试用版 → 调 "<管家>\\software_center.exe" 1 A5300 "<license.dat>"，退出码 0 = 通过
     正式版 → SuperDog 加密狗验证（SuperDog_x64.dll 置于壳同级；DLL 未就位时报错退出）
  4. 找不到软件管家 / 校验失败 → 返回失败，壳弹窗退出

开发态（非 frozen）跳过校验，同云侠 isDev 分支。
"""
from __future__ import annotations

import ctypes
import struct
import subprocess
import winreg
from pathlib import Path

PRODUCT_CODE = "A5300"          # 产品编号（软件管家定版）
_LICENSE_KEY = b"gn9xswy"       # license.dat RC4 密钥（与云侠一致）
_FIELD_OFFSET = 1024            # 有效字段起始偏移
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# SuperDog 厂商码（与云侠 license.ts VENDOR_CODE 一致，照抄）
_VENDOR_CODE = (
    "8un/J8BOJmQ9zjVFe9rdDTRmepVm0JkgEQUl2ddD3PuTLjwICWSriOpIyWXPnz2FUaWZWR3BuIXi1bvT/"
    "dEBfTMpDkBVkWqfIUYQCOOE47fjPl+gEIopZhkVaF2ECxsfnCa4PC1g7TqSMMt7oVqATRmyZc7Jxn3oer"
    "/TKz9JDoDHSYvsfUHDQG7urYx5i9xs2SvGrXhLERY5bie2mlrEzd05i10D7/TXrCCP1qyOnJESMY35T+r"
    "UtvVm/wmHg7LQ2Tr3fhwYCUzsJx6AOf3Btd+fnPCiakvPXHTqdrpL8zukzZPejYW/pL8BiKU5cCchHJs1"
    "TTkXs4u1nbc85830w/+w5JqO6nFhhgO9mtuWinuMp3dOaVq9/Mbv3yMc1V4OjBFxoHKw/BhYN/7H/6dqp"
    "l7U5tv+VXp3/n3qWenOE3uWFO2eIQVOAxNF9ZlZmVesKcX7ZmGf2VhX3uR3egOsdVj2ahSBrYB8TdmqIx"
    "kgy6OD+a4L0WAjpeWoLTo0mG0z+gZ0H3FRgs8s9IbJQpTpckkSQ+tohDBi7zHu9ZDnI08IG1qy94Le67Y"
    "EPa1IJbPPlcLtBm/qomXjb3atqcRIsdVqRGKHoaE9zJ3JQHw01p9m0SKkfYH/4JPbdR3aBawy/X3GYLDV"
    "6JDq1oGTvTJ1HquY2nMNtsYwjjeqCkP1WOiHkXTo0nHMMtwUoh1bu/tbq7y6xGUohHFe7oeXQUQpUi6MW"
    "IvDRL3qY+EOv04PE/PZytBhz98M/S+np5vOy7Yxe394SFvItInKTFD5iLIVbgtQ1mo4Sj49sKvPtSv5kD"
    "SbGk0tko+LUX6qt5OylQYkOyWXmdnhEf5S6e5EOw3/+TGaboPYVvfYNcxPK7LXSpzk7Gm3R+cDqmg2Yb/"
    "AsOgIPTjRG1r5ekYdk9HWyhfK3VIzrVRqMec6Sw6i+VwD1eY2++/BMir/IKawyJAMfP9WYu8jY8IrXkhp"
    "t7C+iYsv2w=="
)

# 字段布局（与云侠 getLicenseData 逐字段一致）
_LICENSE_FMT = "<ii128s128siiiii64s64si16s"
_LICENSE_FIELDS = (
    "license_magic", "data_key", "guid", "user", "license_type",
    "expired_year", "expired_month", "expired_day",
    "dog_type", "dog_name", "dog_pass", "is_check_disk", "md5_hash",
)


def read_tj_housekeeper() -> str | None:
    """读注册表定位软件管家安装目录；两个注册表视图都试（software_center 可能 32 位）。"""
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"Software\TuoJie\TJHouseKeeper", 0,
                                winreg.KEY_READ | view) as key:
                val, _ = winreg.QueryValueEx(key, "Path")
                return val
        except OSError:
            continue
    return None


def _rc4(data: bytes, key: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for b in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(b ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def _clean(b: bytes) -> str:
    return b.decode("utf-8", "replace").replace("\0", "").strip()


def get_license_data(license_path: Path) -> dict:
    """解析 license.dat → 字段 dict；文件缺失/损坏返回 {}。"""
    try:
        raw = _rc4(Path(license_path).read_bytes(), _LICENSE_KEY)
        size = struct.calcsize(_LICENSE_FMT)
        if len(raw) < _FIELD_OFFSET + size:
            return {}
        values = struct.unpack_from(_LICENSE_FMT, raw, _FIELD_OFFSET)
        data = dict(zip(_LICENSE_FIELDS, values))
        for k in ("guid", "user", "dog_name", "dog_pass", "md5_hash"):
            data[k] = _clean(data[k])
        return data
    except Exception:
        return {}


def _verify_super_dog(license_data: dict, dll_path: Path) -> None:
    """正式版：SuperDog 加密狗验证。失败抛异常（调用方转失败退出）。"""
    lib = ctypes.CDLL(str(dll_path))
    handle = ctypes.c_int(0)
    if lib.dog_login(0, _VENDOR_CODE.encode(), ctypes.byref(handle)) != 0:
        raise RuntimeError("软件狗连接失败（Login Failed）")
    h = handle.value
    try:
        size = ctypes.c_int(0)
        if lib.dog_get_size(h, 0xFFF4, ctypes.byref(size)) != 0 or size.value < 128:
            raise RuntimeError("软件狗数据读取失败")
        name_buf = ctypes.create_string_buffer(64)
        pass_buf = ctypes.create_string_buffer(64)
        if lib.dog_read(h, 0xFFF4, 0, 64, name_buf) != 0:
            raise RuntimeError("软件狗数据读取失败")
        if lib.dog_read(h, 0xFFF4, 64, 64, pass_buf) != 0:
            raise RuntimeError("软件狗数据读取失败")
        dog_name = name_buf.value.decode("utf-8", "replace").strip()
        dog_pass = pass_buf.value.decode("utf-8", "replace").strip()
        if dog_name != license_data.get("dog_name") or dog_pass != license_data.get("dog_pass"):
            raise RuntimeError("加密狗与许可不匹配")
    finally:
        lib.dog_logout(h)


def verify_license(root: Path, log=None) -> tuple[bool, str, dict]:
    """启动校验入口。返回 (是否通过, 失败提示, license 字段 dict)。"""
    license_path = root / "license.dat"
    data = get_license_data(license_path)
    license_type = data.get("license_type")
    housekeeper = read_tj_housekeeper()

    if license_type == 1:
        # 正式版：SuperDog 加密狗（SuperDog_x64.dll 与壳同级）
        dll = root / "SuperDog_x64.dll"
        if not dll.exists():
            return False, "正式版校验组件缺失（SuperDog_x64.dll），请联系管理员", data
        try:
            _verify_super_dog(data, dll)
            return True, "", data
        except Exception as e:
            return False, f"检测许可环境失败（{e}）", data

    # 试用版：软件管家命令行校验（退出码 0 = 通过）
    if not housekeeper:
        return False, "未检测到拓界软件管家，请安装后再试！", data
    software_center = Path(housekeeper) / "software_center.exe"
    if not license_path.exists():
        return False, "未找到许可文件 license.dat，请联系管理员获取", data
    try:
        proc = subprocess.run(
            [str(software_center), "1", PRODUCT_CODE, str(license_path)],
            creationflags=_NO_WINDOW, timeout=120,
        )
    except Exception as e:
        return False, f"许可校验执行失败（{e}）", data
    if proc.returncode == 0:
        return True, "", data
    return False, "检测许可环境失败！", data


def expired_date(data: dict) -> str:
    """许可有效期（显示用）。"""
    y, m, d = data.get("expired_year"), data.get("expired_month"), data.get("expired_day")
    if not (y and m and d):
        return ""
    return f"{y}-{m}-{d}"
