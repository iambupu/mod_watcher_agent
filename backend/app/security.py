from ipaddress import ip_address

from fastapi import Request


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def is_local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host in LOCAL_HOSTS:
        return True
    try:
        ip = ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback
