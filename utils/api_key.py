import secrets

import bcrypt

def hash_api_key(api_key: str) -> tuple[str, str]:
    """使用 bcrypt 对 API Key 进行哈希化"""
    salt = bcrypt.gensalt()  # 生成盐
    hashed_key = bcrypt.hashpw(api_key.encode('utf-8'), salt)
    return hashed_key.decode('utf-8'), salt.decode('utf-8')

def verify_api_key(api_key: str, hashed_key: str) -> bool:
    """验证提供的 API Key 是否与存储的哈希值匹配"""
    return bcrypt.checkpw(api_key.encode('utf-8'), hashed_key.encode('utf-8'))

def generate_api_key() -> str:
    """生成一个随机的 API Key"""
    return secrets.token_hex(32)