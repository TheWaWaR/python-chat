
from gevent import monkey; monkey.patch_all()
from ws4py.websocket import WebSocket # EchoWebSocket
from ws4py.server.geventserver import WSGIServer
from ws4py.server.wsgiutils import WebSocketWSGIApplication

import gevent
from gevent.queue import Queue
import redis

pool = redis.ConnectionPool(unix_socket_path='/tmp/redis.sock')

class ChatWebSocket(WebSocket):
    
    def opened(self):
        print 'Opened!'
        self.tasks = Queue()
        
        rd = redis.StrictRedis(connection_pool=pool)
        self.redis = rd
        gevent.joinall([
            gevent.spawn(self.open_channel, 'room1'),
        ])

    def handle_channels():
        pass
        
    def open_channel(name):
        pass

        
    def closed(self, code, reason=None):
        print 'Closed: code=%s, reason=%s' % (code, reason)

    def ponged(self, pong):
        pass

    def received_message(self, message):
        print 'Message received: %s' % message.data
        self.send(message.data, message.is_binary)


server = WSGIServer(('0.0.0.0', 9000),
                    WebSocketWSGIApplication(handler_cls=ChatWebSocket))
server.serve_forever()
