
from gevent import monkey; monkey.patch_all()
from ws4py.websocket import WebSocket # EchoWebSocket
from ws4py.server.geventserver import WSGIServer
from ws4py.server.wsgiutils import WebSocketWSGIApplication

import os
import hashlib
from datetime import datetime

import gevent
import json
import redis

pool = redis.ConnectionPool(connection_class=redis.UnixDomainSocketConnection,
                            max_connections=None,
                            path='/tmp/redis.sock')

K_USERS_ID = 'users:id'
K_SESSIONS_ID = 'sessions:id'

class ChatWebSocket(WebSocket):
    keep_channels = ['system', ]
    
    def opened(self):
        self.redis = redis.StrictRedis(connection_pool=pool)
        self.greenlets = {}
        self.pubsubs = {}
        self.connected_users = {}
        self.connected_rooms = {}
        
        self.uid = None
        # Start global channels
        for name in ChatWebSocket.keep_channels:
            self.greenlets[name] = gevent.spawn(self.listen_channel, name)
        
        print 'Opened!'

    def closed(self, code, reason=None):
        print 'Start closing......'
        # 1. Unsubscribe global channels
        print '1. Unsubscribe global channels'
        for g_key in ChatWebSocket.keep_channels:
            self.unsubscribe(g_key)
            
        # 2. Unsubscribe users
        print '2. Unsubscribe users'
        user_destory_msg = {
            'type': 'session',
            'action': 'destory', # Destory
            'from_id': self.uid,
        }
        for uid in self.connected_users:
            user_key = 'user-%d'%uid
            self.unsubscribe(user_key)
            self.redis.publish(user_key, json.dumps(user_destory_msg))

        # 3. Unsubscribe rooms
        print '3. Unsubscribe rooms'
        room_offline_msg = {
            'path': 'message',
            'type': 'offline',
            'uid': self.uid
        }
        for rid in self.connected_rooms:
            room_key = 'room-%d'%rid
            self.unsubscribe(room_key)
            self.redis.publish(room_key, json.dumps(room_offline_msg))

        # 4. Unsubscribe current user's mailbox
        print '4. Unsubscribe current user\'s mailbox'
        self.unsubscribe('user-%d'%self.uid)

        print 'Check:', self.greenlets
        print 'Check:', self.pubsubs
        print 'Closed: code=%s, reason=%s' % (code, reason)
        print '============================================================'


    def ponged(self, pong):
        print 'Ponged:', pong

        
    def received_message(self, message):
        print 'Message received: %s' % message.data

        router = {
            'init_client': self.init_client,
            'rooms'      : self.rooms, # List available rooms
            'add_room'   : self.add_room,
            'remove_room': self.remove_room, # Owner/Admin only
            'online'     : self.online,
            'offline'    : self.offline, # :HOLD:
            'connect'    : self.connect, # Room or user
            'disconnect' : self.disconnect,
            'message'    : self.message,
            # 'history'    : self.history,  # Get message history
            # 'users'      : self.users,  # Get user info by ids
            'typing'     : self.typing,
        }
        try:
            # data = {
            #     'path': 'message | connect | disconnect | inputing...',
            #     'target': 'rid | uid',  ==> type=int
            #     'payload': '...',
            # }
            data = json.loads(message.data)
            path = data['path']
            if path in router:
                processor = router[path]
                ret = processor(data)
                ret['path'] = path
                self.send(json.dumps(ret))
            else:
                raise TypeError(u'Valid message type:%s' % message.data)
            
        except TypeError, e:
            print e


    def unsubscribe(self, channel_name):
        ps = self.pubsubs.pop(channel_name)
        greenlet = self.greenlets.pop(channel_name)
        
        ps.unsubscribe(channel_name)
        greenlet.join()
        

    def listen_channel(self, name):
        print 'Start channel:', name
        ps = self.redis.pubsub()
        self.pubsubs[name] = ps
        ps.subscribe(name)
        
        channel = ps.listen()
        channel.next()
        while True:
            msg = channel.next()
            if msg['type'] == 'unsubscribe':
                print 'Exit channel:', name
                ps.close()
                break
                
            print 'Received message from redis:', msg
            self.send(msg['data'])

    def setup_mailbox(self, user_key):
        ''' Current user's Mailbox '''
        print 'Start mailbox:', user_key
        ps = self.redis.pubsub()
        self.pubsubs[user_key] = ps
        ps.subscribe(user_key)
        
        channel = ps.listen()
        channel.next()
        while True:
            msg = channel.next()
            if msg['type'] == 'unsubscribe':
                print 'Exit mail box:', user_key
                ps.close()
                break

            data = json.loads(msg['data'])
            if data['type'] == 'session':
                action = data['action']
                from_id = data['from_id']
                if action == 'create':
                    if from_id in self.connected_users:
                        print '%d already connected!' % from_id
                    else:
                        session_id = data['session_id']
                        session_key = 'session-%d'%session_id
                        self.greenlets[session_key] = gevent.spawn(self.listen_channel, session_key)
                        self.connected_users[from_id] = {
                            'user_id': from_id,
                            'session_id': session_id
                        }
                elif action == 'destory':
                    user = self.connected_users.pop(from_id)
                    session_id = user['session_id']
                    session_key = 'session-%d'%session_id
                    self.unsubscribe(session_key)
            else:
                raise ValueError('Mailbox received bad data:' % msg)
                
            print 'Received message from redis:', msg, type(msg)
            # self.send(msg['data'])


    ### API methods ###
    def init_client(self, _):
        token = hashlib.sha1(os.urandom(64)).hexdigest()
        uid = self.redis.incr(K_USERS_ID)
        init_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.redis.set('users:%s'%token, uid)
        self.redis.hset('users:%d'%uid, 'init_at', init_at)
        return {'token': token}

    def rooms(self, _):
        return {'rooms': [1, 2]} # return room ids
        
    def add_room(self, _): pass
        
    def remove_room(self, _): pass

    def online(self, data):
        token = data['token']
        uid = int(self.redis.get('users:%s'%token))
        # init_at = self.redis.hget('users:%d'%uid, 'init_at')
        user_key = 'user-%d' % uid
        self.uid = uid
        # Current user's mail box
        self.greenlets[user_key] = gevent.spawn(self.setup_mailbox, user_key)
        return {'uid': str(uid)}

        
    def offline(self, _):
        # Equal to `closed` ???
        pass

    def connect(self, data):
        ''' Connect to room or user '''
        target_type = data['type']
        target_id = int(data['id'])
        
        if target_id in ChatWebSocket.keep_channels:
            raise ValueError('Invalidate target id: %s' % data)
            
        if target_type == 'room':
            room_key = 'room-%d' % target_id
            self.greenlets[room_key] = gevent.spawn(self.listen_channel, room_key)
            room_online_msg = {
                'path': 'message',
                'type': 'online',
                'uid': self.uid
            }
            self.redis.publish(room_key, json.dumps(room_online_msg))
            self.connected_rooms[target_id]= {'id': target_id}
            
        elif target_type == 'user':
            target_user_key = 'user-%d' % target_id
            session_id = self.redis.incr(K_SESSIONS_ID)
            session_key = 'session-%d' % session_id
            create_session_msg = {
                'type': 'session',
                'action': 'create', # Create
                'from_id': self.uid,
                'session_id': session_id,
            }
            # Mail to target user new session
            self.redis.publish(target_user_key, json.dumps(create_session_msg))
            self.greenlets[session_key] = gevent.spawn(self.listen_channel, session_key)
            self.connected_users[target_id] = {
                'user_id': target_id,
                'session_id': session_id
            }
        return {
            'type'   : target_type,
            'id'     : target_id,
            'status' : 'success'
        }
            
        
    def disconnect(self, data):
        ''' Disconnect to room or user '''
        target_type = data['type']
        target_id = int(data['id'])
        
        if target_id in ChatWebSocket.keep_channels:
            raise ValueError('Invalidate target id: %s' % data)

            
        if target_type == 'room':
            if target_id in self.connected_rooms:
                room_key = 'room-%d' % target_id
                self.unsubscribe(room_key)
                self.connected_rooms.pop(target_id)
                print '%s disconnected!' % room_key
            
        elif target_type == 'user':
            if target_id in self.connected_users:
                user = self.connected_users[target_id]
                target_user_key = 'user-%d' % target_id
                session_id = user['session_id']
                session_key = 'session-%d' % session_id
                msg = {
                    'type': 'session',
                    'action': 'destory', # Destory
                    'from_id': self.uid,
                }
                self.redis.publish(target_user_key, json.dumps(msg)) # Mail to target user destory session
                self.unsubscribe(session_key)
                self.connected_users.pop(target_id)
                print '%s,%s disconnected!' % (session_key, target_user_key)
        return {
            'type'   : target_type,
            'id'     : target_id,
            'status' : 'success'
        }
        
    def message(self, data):
        target_type = data['type']
        target_id = int(data['id'])

        msg = {
            'path': 'message',
            'type': 'message',
            'body': data['body']
        }
        ret = self.redis.publish('%s-%d'%(target_type, target_id), json.dumps(msg))
        return {
            'type': 'message',
            'target': target_type,
            'id': target_id,
            'ret': ret,
            'status': 'success'
        }
        
        
    def typing(self, data):
        pass

    ### API methods END ###

server = WSGIServer(('0.0.0.0', 9000),
                    WebSocketWSGIApplication(handler_cls=ChatWebSocket))
server.serve_forever()
