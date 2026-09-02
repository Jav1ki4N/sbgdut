import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/home/cat/Desktop/SBGDUT/install/rk3576_ws_bridge'
