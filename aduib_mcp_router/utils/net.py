import socket


def get_local_ip():
    try:
        # 创建一个 UDP 套接字
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('www.baidu.com', 80))  # 连接到一个外部服务器
        # 获取本地 IP 地址
        local_ip = s.getsockname()[0]
    finally:
        s.close()
    return local_ip