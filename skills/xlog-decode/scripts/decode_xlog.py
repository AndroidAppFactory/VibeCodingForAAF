#!/usr/bin/env python3
"""Mars xlog 解密脚本（Python3 版）。

将腾讯 mars xlog 加密日志解密为明文文本。
私钥从环境变量 XLOG_PRIV_KEY 读取，可用 --priv-key 覆盖以适配其他项目。

用法:
  python3 decode_xlog.py <输入.xlog 或目录> [-o 输出] [--priv-key 私钥hex]
"""
import sys
import os
import glob
import zlib
import struct
import argparse
from pathlib import Path

# 复用 bootstrap.load_env（读 .env + secrets.env 到 os.environ），
# 向上找 scripts/ 或 fallback ~/.zixiekit/scripts；不可用则密钥走 --priv-key 覆盖。
for _p in Path(__file__).resolve().parents:
    if (_p / "scripts").is_dir():
        sys.path.insert(0, str(_p / "scripts"))
        break
sys.path.insert(1, str(Path.home() / ".zixiekit" / "scripts"))
try:
    from bootstrap import load_env
    load_env()
except ImportError:
    pass

# secp256k1 曲线参数（纯标准库实现 ECDH，零外部依赖）
SECP256K1_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
SECP256K1_A = 0

MAGIC_NO_COMPRESS_START = 0x03
MAGIC_NO_COMPRESS_START1 = 0x06
MAGIC_NO_COMPRESS_NO_CRYPT_START = 0x08
MAGIC_COMPRESS_START = 0x04
MAGIC_COMPRESS_START1 = 0x05
MAGIC_COMPRESS_START2 = 0x07
MAGIC_COMPRESS_NO_CRYPT_START = 0x09
MAGIC_END = 0x00

# 私钥从环境变量读取（不硬编码，避免提交 git 泄露）
PRIV_KEY_ENV = 'XLOG_PRIV_KEY'

_PRIV_KEY = None
_lastseq = 0


def load_env_var(key):
    """读取环境变量（bootstrap 已把 .env + secrets.env 加载到 os.environ）"""
    return os.environ.get(key) or None


def _point_add(p1, p2):
    """secp256k1 仿射坐标点加。None 表示无穷远点。"""
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % SECP256K1_P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1 + SECP256K1_A) * pow(2 * y1, SECP256K1_P - 2, SECP256K1_P) % SECP256K1_P
    else:
        lam = (y2 - y1) * pow(x2 - x1, SECP256K1_P - 2, SECP256K1_P) % SECP256K1_P
    x3 = (lam * lam - x1 - x2) % SECP256K1_P
    y3 = (lam * (x1 - x3) - y1) % SECP256K1_P
    return (x3, y3)


def _point_mul(k, p):
    """标量乘（double-and-add）。"""
    result = None
    addend = p
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def ecdh_shared_x(client_x, client_y):
    d = int(_PRIV_KEY, 16)
    q = (int.from_bytes(client_x, 'big'), int.from_bytes(client_y, 'big'))
    s = _point_mul(d, q)
    if s is None:
        raise ValueError('ECDH 计算得到无穷远点（密钥不符）')
    return s[0].to_bytes(32, 'big')


def tea_decipher(v, k):
    op = 0xffffffff
    v0, v1 = struct.unpack('=LL', v[0:8])
    k1, k2, k3, k4 = struct.unpack('=LLLL', k[0:16])
    delta = 0x9E3779B9
    s = (delta << 4) & op
    for _ in range(16):
        v1 = (v1 - (((v0 << 4) + k3) ^ (v0 + s) ^ ((v0 >> 5) + k4))) & op
        v0 = (v0 - (((v1 << 4) + k1) ^ (v1 + s) ^ ((v1 >> 5) + k2))) & op
        s = (s - delta) & op
    return struct.pack('=LL', v0, v1)


def tea_decrypt(v, k):
    num = len(v) // 8 * 8
    ret = b''
    for i in range(0, num, 8):
        ret += tea_decipher(v[i:i + 8], k)
    ret += v[num:]
    return ret


def is_good_log_buffer(buf, offset, count):
    if offset == len(buf):
        return (True, '')
    magic_start = buf[offset]
    if magic_start in (MAGIC_NO_COMPRESS_START, MAGIC_COMPRESS_START, MAGIC_COMPRESS_START1):
        crypt_key_len = 4
    elif magic_start in (MAGIC_COMPRESS_START2, MAGIC_NO_COMPRESS_START1,
                         MAGIC_NO_COMPRESS_NO_CRYPT_START, MAGIC_COMPRESS_NO_CRYPT_START):
        crypt_key_len = 64
    else:
        return (False, '_buffer[%d]:%d != MAGIC_NUM_START' % (offset, buf[offset]))

    header_len = 1 + 2 + 1 + 1 + 4 + crypt_key_len
    if offset + header_len + 1 + 1 > len(buf):
        return (False, 'offset:%d > len(buffer):%d' % (offset, len(buf)))
    length = struct.unpack_from("I", buf, offset + header_len - 4 - crypt_key_len)[0]
    if offset + header_len + length + 1 > len(buf):
        return (False, 'log length:%d, end pos %d > len(buffer):%d' % (length, offset + header_len + length + 1, len(buf)))
    if MAGIC_END != buf[offset + header_len + length]:
        return (False, 'log length:%d, buffer[%d]:%d != MAGIC_END' % (length, offset + header_len + length, buf[offset + header_len + length]))
    if count >= 2:
        return is_good_log_buffer(buf, offset + header_len + length + 1, count - 1)
    return (True, '')


def get_log_start_pos(buf, count):
    offset = 0
    while offset < len(buf):
        if buf[offset] in (MAGIC_NO_COMPRESS_START, MAGIC_NO_COMPRESS_START1, MAGIC_COMPRESS_START,
                           MAGIC_COMPRESS_START1, MAGIC_COMPRESS_START2, MAGIC_COMPRESS_NO_CRYPT_START,
                           MAGIC_NO_COMPRESS_NO_CRYPT_START):
            if is_good_log_buffer(buf, offset, count)[0]:
                return offset
        offset += 1
    return -1


def decode_buffer(buf, offset, outbuffer):
    global _lastseq
    if offset >= len(buf):
        return -1
    ret = is_good_log_buffer(buf, offset, 1)
    if not ret[0]:
        fixpos = get_log_start_pos(buf[offset:], 1)
        if fixpos == -1:
            return -1
        outbuffer.extend(b"[F]decode error len=%d, result:%s \n" % (fixpos, ret[1].encode()))
        offset += fixpos

    magic_start = buf[offset]
    if magic_start in (MAGIC_NO_COMPRESS_START, MAGIC_COMPRESS_START, MAGIC_COMPRESS_START1):
        crypt_key_len = 4
    elif magic_start in (MAGIC_COMPRESS_START2, MAGIC_NO_COMPRESS_START1,
                         MAGIC_NO_COMPRESS_NO_CRYPT_START, MAGIC_COMPRESS_NO_CRYPT_START):
        crypt_key_len = 64
    else:
        outbuffer.extend(b'in DecodeBuffer _buffer[%d]:%d != MAGIC_NUM_START' % (offset, magic_start))
        return -1

    header_len = 1 + 2 + 1 + 1 + 4 + crypt_key_len
    length = struct.unpack_from("I", buf, offset + header_len - 4 - crypt_key_len)[0]
    tmpbuffer = bytearray(length)
    tmpbuffer[:] = buf[offset + header_len:offset + header_len + length]

    try:
        decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        if MAGIC_NO_COMPRESS_START1 == magic_start:
            pass
        elif MAGIC_COMPRESS_START2 == magic_start:
            client_x = bytes(buf[offset + header_len - crypt_key_len: offset + header_len - crypt_key_len // 2])
            client_y = bytes(buf[offset + header_len - crypt_key_len // 2: offset + header_len])
            tea_key = ecdh_shared_x(client_x, client_y)
            tmpbuffer = tea_decrypt(bytes(tmpbuffer), tea_key)
            tmpbuffer = decompressor.decompress(bytes(tmpbuffer))
        elif magic_start in (MAGIC_COMPRESS_START, MAGIC_COMPRESS_NO_CRYPT_START):
            tmpbuffer = decompressor.decompress(bytes(tmpbuffer))
        elif MAGIC_COMPRESS_START1 == magic_start:
            decompress_data = bytearray()
            while len(tmpbuffer) > 0:
                single_log_len = struct.unpack_from("H", tmpbuffer, 0)[0]
                decompress_data.extend(tmpbuffer[2:single_log_len + 2])
                tmpbuffer[:] = tmpbuffer[single_log_len + 2:]
            tmpbuffer = decompressor.decompress(bytes(decompress_data))
    except Exception as e:
        outbuffer.extend(b"[F]decompress err, " + str(e).encode() + b"\n")
        return offset + header_len + length + 1

    outbuffer.extend(tmpbuffer)
    return offset + header_len + length + 1


def parse_file(infile, outfile):
    """解密单个文件。返回 True 表示成功，False 表示失败（非标准 xlog 或密钥不符）。"""
    global _lastseq
    _lastseq = 0
    with open(infile, "rb") as fp:
        buf = bytearray(os.path.getsize(infile))
        fp.readinto(buf)
    startpos = get_log_start_pos(buf, 2)
    if startpos == -1:
        return False
    outbuffer = bytearray()
    while True:
        startpos = decode_buffer(buf, startpos, outbuffer)
        if startpos == -1:
            break
    if len(outbuffer) == 0:
        return False
    with open(outfile, "wb") as fpout:
        fpout.write(outbuffer)
    return True


def main():
    global _PRIV_KEY
    parser = argparse.ArgumentParser(description='解密 mars xlog 日志')
    parser.add_argument('input', help='输入 .xlog 文件或目录')
    parser.add_argument('-o', '--output', help='输出文件路径（仅单文件输入时有效，默认同目录 .log）')
    parser.add_argument('--priv-key', help='解密私钥（hex），优先于环境变量 %s' % PRIV_KEY_ENV)
    args = parser.parse_args()

    _PRIV_KEY = (args.priv_key or load_env_var(PRIV_KEY_ENV) or '').strip()
    if not _PRIV_KEY:
        print("[xlog-decode] 未提供解密私钥，请在 ~/.zixiekit/secrets.env 配置 %s 或传 --priv-key" % PRIV_KEY_ENV)
        sys.exit(1)

    if os.path.isdir(args.input):
        files = sorted(glob.glob(os.path.join(args.input, '*.xlog')))
        if not files:
            print("[xlog-decode] 目录 %s 下未找到 .xlog 文件" % args.input)
            sys.exit(1)
        for f in files:
            outfile = f + '.log'
            if parse_file(f, outfile):
                print("[xlog-decode] 已解密: %s -> %s" % (f, outfile))
            else:
                print("[xlog-decode] 解密失败（非标准 xlog 或密钥不符）: %s" % f)
    else:
        if not os.path.exists(args.input):
            print("[xlog-decode] 文件不存在: %s" % args.input)
            sys.exit(1)
        outfile = args.output or args.input + '.log'
        if parse_file(args.input, outfile):
            print("[xlog-decode] 已解密: %s -> %s" % (args.input, outfile))
        else:
            print("[xlog-decode] 解密失败（非标准 xlog 或密钥不符）: %s" % args.input)
            sys.exit(1)


if __name__ == "__main__":
    main()
