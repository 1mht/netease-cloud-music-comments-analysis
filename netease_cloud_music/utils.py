import random
import math
from Crypto.Cipher import AES
import base64
import codecs

def generate_random_strs(length):
    """
    生成固定长度的字符串
    :param length: 指定生成的字符串长度
    :return: 返回length长度的字符串
    """
    string = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    i = 0
    random_strs = ""
    while i < length:
        e = random.random() * len(string)
        e = math.floor(e)
        random_strs = random_strs + string[e]
        i = i + 1
    return random_strs

def AESencrypt(msg, key):
    """
    AES加密 (PKCS7 填充)
    """
    # 补齐长度为16的倍数
    pad = 16 - len(msg.encode('utf-8')) % 16
    text = msg + pad * chr(pad)
    
    iv = b"0102030405060708"
    if isinstance(key, str):
        key = key.encode('utf-8')
    
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encryptedbytes = cipher.encrypt(text.encode('utf-8'))
    return base64.b64encode(encryptedbytes).decode('utf-8')

def RSAencrypt(randomstrs,key,f):
    """
    RSA加密
    :param randomstrs:
    :param key:
    :param f:
    :return:
    """
    string = randomstrs[::-1]
    text = bytes(string,'utf-8')
    seckey = int(codecs.encode(text,encoding='hex'),16) ** int(key,16) % int(f,16)
    return format(seckey,'x').zfill(256)

def create_weapi_params(text):
    """
    通用 weapi 加密函数
    :param text: dict or str, 请求负载
    :return: dict, 包含 encText 和 encSecKey
    """
    if isinstance(text, dict):
        import json
        text = json.dumps(text)
    
    key = '0CoJUm6Qyw8W8jud'
    f = '00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7'
    e = '010001'

    enctext = AESencrypt(text, key)
    i = generate_random_strs(16)
    encText = AESencrypt(enctext, i)
    encSecKey = RSAencrypt(i, e, f)
    
    return {
        "params": encText,
        "encSecKey": encSecKey
    }

def get_params(song_id):
    """
    获取加密参数encText,encSecKey（保持向后兼容）
    :params song_id: str
    :return:
    """
    # 用于获取某首歌的评论数据
    msg = {
        "rid": f"R_SO_4_{song_id}",
        "threadId": f"R_SO_4_{song_id}",
        "pageNo": "1",
        "pageSize": "20",
        "cursor": "-1",
        "offset": "0",
        "orderType": "1",
        "csrf_token": ""
    }
    res = create_weapi_params(msg)
    return res["params"], res["encSecKey"]


if __name__ == "__main__":
    #r = generate_random_strs(16)
    #print(r, len(r))
    r = get_params()
    print(len(r[0]),r[0],len(r[1]),r[1])

