import sys

from vatdisc.config import get_settings
from vatdisc.db import connect
from vatdisc.hmrc import HMRCClient

s = get_settings()
print("base url:", s.hmrc_base_url)
client = HMRCClient(s, connect(":memory:"))
for vrn in sys.argv[1:]:
    print(vrn, "->", client.lookup(vrn))
print("calls made:", client.calls)