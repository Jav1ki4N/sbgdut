import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/home/i4n/Desktop/GDUT/install/pc_ws_bridge'
