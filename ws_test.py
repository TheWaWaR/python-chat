from ws4py.client.threadedclient import WebSocketClient

import time

class DummyClient(WebSocketClient):
    def opened(self):
        def data_provider():
            for i in range(1, 200, 25):
                yield "#" * i

        self.send(data_provider())

        for i in range(0, 200, 25):
            print i
            self.send("*" * i)

    def closed(self, code, reason):
        print "Closed down", code, reason

    def received_message(self, m):
        print "=> %d %s" % (len(m), str(m))
        if len(str(m)) == 175:
            self.close(reason='Bye bye')

if __name__ == '__main__':
    try:
        ws = DummyClient('ws://localhost:9000/')
        ws.connect()
        print 'connected'
        time.sleep(60)
    except KeyboardInterrupt:
        ws.close()

    print 'The END'
