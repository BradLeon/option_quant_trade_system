
from ib_async import IB
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=99, timeout=5)
print(ib.managedAccounts())
ib.disconnect()
