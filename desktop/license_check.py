"""desktop/license_check.py — 软件管家 License 校验。

权威依据：《软件管家-客户端需求功能.docx》第四节"启动客户端"（注册表/接口/返回值均按文档）。
校验在桌面壳启动时执行（iss 安装器不校验），流程：
  1. 读注册表 HKLM\\SOFTWARE\\WOW6432Node\\Tuojie\\TJHouseKeeper 的 Path → 软件管家安装目录
  2. 调 "<管家>\\software_center.exe" "1" "A5300" "<license.dat 路径>"（激活助手，无论
     本地是否已有 license.dat——校验/在线下拉认证文件都是它的职责）
  3. 按退出码分流（文档规定，勿用客户端自解析 license.dat 分流）：
       0 = 校验通过（试用），继续启动
       1 = 失败，弹窗退出
       2 = 正式版 → 客户端自行 SuperDog 加密狗校验（SuperDog_x64.dll 置于壳同级）
  4. 失败 → 返回失败，壳弹窗退出

开发态（非 frozen）跳过校验。
"""
from __future__ import annotations

import ctypes
import struct
import winreg
from ctypes import wintypes
from pathlib import Path

PRODUCT_CODE = "A5300"          # 产品编号（软件管家定版）
_LICENSE_KEY = b"gn9xswy"       # license.dat RC4 密钥（与云侠一致）
_FIELD_OFFSET = 1024            # 有效字段起始偏移

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
    """读注册表定位软件管家安装目录（文档路径 WOW6432Node → 32 位视图优先）。"""
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
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


_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_INFINITE = 0xFFFFFFFF


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HANDLE), ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HANDLE),
        ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def _run_software_center(exe: Path, license_path: Path) -> int:
    """调起激活助手（software_center.exe 需管理员权限 → ShellExecute 'runas' 触发 UAC），
    等待退出码。用户拒绝 UAC → OSError。"""
    sei = _ShellExecuteInfo()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = _SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = str(exe)
    sei.lpParameters = f'1 {PRODUCT_CODE} "{license_path}"'
    sei.nShow = 1  # SW_SHOWNORMAL：激活助手 UI 本就要给用户看（激活/输码）
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        err = ctypes.windll.kernel32.GetLastError()
        if err == 1223:  # ERROR_CANCELLED：用户拒绝 UAC
            raise OSError("许可校验需要管理员授权（UAC 被取消）")
        raise OSError(f"调起软件管家失败（WinError {err}）")
    if not sei.hProcess:
        raise OSError("无法获取激活助手进程句柄")
    ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, _INFINITE)
    code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    return code.value


def verify_license(root: Path, log=None) -> tuple[bool, str, dict]:
    """启动校验入口。返回 (是否通过, 失败提示, license 字段 dict)。

    按文档：无论本地有无 license.dat 都调激活助手（校验/在线下拉认证文件是它的职责），
    由退出码分流（0=试用通过 / 1=失败 / 2=正式版转客户端自校验狗）。
    """
    license_path = root / "license.dat"
    housekeeper = read_tj_housekeeper()
    if not housekeeper:
        return False, "未检测到拓界软件管家，请安装后再试！", {}
    software_center = Path(housekeeper) / "software_center.exe"
    if not software_center.exists():
        return False, "软件管家组件缺失（software_center.exe），请重装软件管家", {}

    try:
        rc = _run_software_center(software_center, license_path)
    except Exception as e:
        return False, f"许可校验执行失败（{e}）", {}
    if rc == 0:
        return True, "", get_license_data(license_path)
    if rc == 2:
        # 正式版：客户端自行 SuperDog 加密狗校验（SuperDog_x64.dll 与壳同级）
        data = get_license_data(license_path)
        dll = root / "SuperDog_x64.dll"
        if not dll.exists():
            return False, "正式版校验组件缺失（SuperDog_x64.dll），请联系管理员", data
        try:
            _verify_super_dog(data, dll)
            return True, "", data
        except Exception as e:
            return False, f"检测许可环境失败（{e}）", data
    return False, "检测许可环境失败！", data


def expired_date(data: dict) -> str:
    """许可有效期（显示用）。"""
    y, m, d = data.get("expired_year"), data.get("expired_month"), data.get("expired_day")
    if not (y and m and d):
        return ""
    return f"{y}-{m}-{d}"
