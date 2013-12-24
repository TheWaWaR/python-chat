from gevent import monkey; monkey.patch_all()              # !!! This is required...
import gevent
from gevent.queue import Queue

import redis

r = redis.StrictRedis(unix_socket_path='/tmp/redis.sock')
tasks = Queue()

def handler(n):                 # The handler
    print n, 'Started'
    while True:
        msg = tasks.get()
        print('Worker %s got message %s' % (n, msg))

    print('Quitting time!')

def channel(sender):               # Multiple boss
    print 'channel', sender, 'started!'
    ps = r.pubsub()
    ps.subscribe(sender)
    c = ps.listen()
    c.next()
    listenning = True
    while listenning:
        msg = c.next()
        print 'Send by:', sender
        tasks.put_nowait(msg)

gevent.joinall([
    gevent.spawn(channel, 'room1'),
    gevent.spawn(channel, 'room2'),
    gevent.spawn(channel, 'user1'),
    gevent.spawn(handler, 'handler')
])
