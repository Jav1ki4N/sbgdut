import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/home/i4n/Desktop/GDUT/RK3576/SBGDUT/install/viewer_ws_bridge'
