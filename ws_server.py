
from gevent import monkey; monkey.patch_all()
from ws4py.websocket import WebSocket # EchoWebSocket
from ws4py.server.geventserver import WSGIServer
from ws4py.server.wsgiutils import WebSocketWSGIApplication

import os
import hashlib
import json
from datetime import datetime

import gevent
import redis

pool = redis.ConnectionPool(connection_class=redis.UnixDomainSocketConnection,
                            path='/tmp/redis.sock')



class Session(object):
    K_SESSIONS = 'sessions' # Active sessions
    K_SESSIONS_ID = 'sessions:id'
    
    def __init__(self, rd, oid, channel):
        self.rd = rd
        self.oid = oid
        self.channel = channel
        self.KEY = 'session:%d'%self.oid
        
    @staticmethod
    def create(rd):
        oid = rd.incr(Session.K_SESSIONS_ID)
        channel = 'session-%d'%oid
        session = Session(rd, oid)
        rd.hset(session.KEY, 'oid', oid) 
        rd.hset(session.KEY, 'channel', channel) 
        return session

    def destory(self):
        # remove from users' sessions
#         self.rd.delete(self.KEY)


class User(object):
    K_USERS = 'users' # Active users
    K_USERS_ID = 'users:id'
    
    def __init__(self, rd, oid, name):
        self.rd = rd
        self.oid = oid
        self.name = name
        self.KEY = 'user:%d'%self.oid

    def destory(self):
        self.rd.delete(self.KEY) # Seems won't happen for now

    def online(self):
        self.rd.hset(User.K_USERS, self.oid, True)

    def offline(self):
        self.rd.hdel(User.K_USERS, self.oid)
        
    def join_room(self, rid):
        pass
        
    def leave_room(self, rid):
        pass
        
    @staticmethod
    def create(rd, name):
        oid = rd.incr(User.K_USERS_ID)
        user = User(rd, oid, name)
        rd.hset(user.KEY, 'oid', oid)
        rd.hset(user.KEY, 'name', name)
        return user

    @staticmethod
    def is_online(rd, uid):
        return rd.hexists(User.K_USERS, uid)
        
    @staticmethod
    def online_users(rd):
        return rd.hkeys(User.K_USERS)

        
class Room(object):
    K_ROOMS = 'rooms' # Active rooms
    K_ROOMS_ID = 'rooms:id'
    
    def __init__(self, rd, oid, name, channel):
        self.rd = rd
        self.oid = oid
        self.name = name
        self.channel = channel
        self.KEY = 'room:%d'%self.oid # Object key
        self.KEY_MEMBERS = 'room:%d:members'%self.oid # Member list key

    @staticmethod
    def create(rd, name):
        oid = rd.incr(Room.K_ROOMS_ID)
        channel = 'room-%d' % oid
        room = Room(rd, oid, name, channel)
        rd.hset(room.KEY, 'oid', oid) 
        rd.hset(room.KEY, 'name', name)
        rd.hset(room.KEY, 'channel', channel)
        return room

    def destory(self):
        self.rd.delete(self.KEY)

    @staticmethod
    def members_key(rid):
        return 'room:%d:members'%rid
        
    @staticmethod
    def members(rd, rid):
        return rd.hkeys(Room.members_key(rid))

    @staticmethod
    def push(rd, rid, uid):
        return rd.hset(Room.members_key(rid), uid, True)

    @staticmethod
    def pop(rd, rid, uid):
        return rd.hdel(Room.members_key(rid), uid)
        

class ChatWebSocket(WebSocket):
    keep_channels = ['system', ]

    # ==============================================================================
    #  WebSocket method override
    # ==============================================================================
    def opened(self):
        self.redis = redis.StrictRedis(connection_pool=pool)
        self.greenlets = {}
        self.pubsubs = {}
        self.queues = {}
        self.connected_users = {} # {'id': uid, 'session_id': session_id}
        self.connected_rooms = {} # {'id': rid}
        
        self.uid = None
        # Start global channels
        for name in ChatWebSocket.keep_channels:
            self.subscribe(name)
        
        print 'Opened!'

    def closed(self, code, reason=None):
        print 'Start closing......'
        # 1. Unsubscribe global channels
        print '1. Unsubscribe global channels'
        for g_key in ChatWebSocket.keep_channels:
            self.unsubscribe(g_key)
            
        offline_msg = {
            'path': 'presence',
            'action': 'offline',
            'uid': self.uid
        }
        # 2. Unsubscribe users
        print '2. Unsubscribe users'
        for uid in self.connected_users:
            user_key = 'user-%d'%uid
            self.unsubscribe(user_key)
            self.redis.publish(user_key, json.dumps(offline_msg))

        # 3. Unsubscribe rooms
        print '3. Unsubscribe rooms'
        for rid in self.connected_rooms:
            room_key = 'room-%d'%rid
            self.unsubscribe(room_key)
            self.redis.publish(room_key, json.dumps(offline_msg))

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
            # Common
            'create_client' : self.create_client,
            'online'        : self.online,     # aka: Login 
            'offline'       : self.offline,    # :HOLD:
            'connect'       : self.connect,    # Room or user(session)
            'disconnect'    : self.disconnect, # Room or user(session)
            # Room
            'rooms'         : self.rooms,       # List available rooms
            'create_room'   : self.create_room, # 
            'destory_room'  : self.destory_room, # NOTE: Owner/Admin only
            'members'       : self.members, # Get user list by room id
            # Message
            'history'       : self.history, # Get message history
            'message'       : self.message, # Send message to room or user(session)
            'typing'        : self.typing,
            # 'presence'      : self.presence, # current user online/offline
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

    # ==============================================================================
    #  Gevent stuff
    # ==============================================================================
    def unsubscribe(self, channel):
        pubsub = self.pubsubs.pop(channel)
        greenlet = self.greenlets.pop(channel)
        pubsub.unsubscribe(channel)
        greenlet.join()

    def subscribe(self, channel):
        print 'Start channel:', channel
        pubsub = self.redis.pubsub()
        self.pubsubs[channel] = pubsub
        pubsub.subscribe(channel)
        queue = pubsub.listen()
        queue.next()
        self.queues[channel] = queue

        def channel_processor():
            while True:
                msg = queue.next()
                if msg['type'] == 'unsubscribe':
                    print 'Exit channel:', channel
                    pubsub.close()
                    break
                    
                print 'Received message from redis:', msg
                self.send(msg['data'])
                
        self.greenlets[channel] = gevent.spawn(channel_processor)


    def start_mailbox(self):
        ''' Current user's Mailbox '''
        
        user_key = 'user-%d' % self.uid
        if user_key in self.greenlets:
            print 'Mailbox already started!'
            
        print 'Starting mailbox:', user_key
        pubsub = self.redis.pubsub()
        self.pubsubs[user_key] = pubsub
        pubsub.subscribe(user_key)
        
        queue = pubsub.listen()
        queue.next()
        
        def mailbox_processer():
            while True:
                msg = queue.next()
                if msg['type'] == 'unsubscribe':
                    print 'Exit mail box:', user_key
                    pubsub.close()
                    break
    
                data = json.loads(msg['data'])
                path = data['path']
                if path == 'session':
                    action = data['action']
                    from_id = data['from_id']
                    # Create session
                    if action == 'create':
                        if from_id in self.connected_users:
                            print '%d already connected!' % from_id
                        else:
                            session_id = data['session_id']
                            session_key = 'session-%d'%session_id
                            self.subscribe(session_key)
                            self.connected_users[from_id] = {
                                'id': from_id,
                                'session_id': session_id
                            }
                    # Destory session
                    elif action == 'destory':
                        user = self.connected_users.pop(from_id)
                        session_id = user['session_id']
                        session_key = 'session-%d'%session_id
                        self.unsubscribe(session_key)
                elif path == 'presence':
                    pass
                else:
                    raise ValueError('Mailbox received bad data:' % msg)
                    
                print 'Received message from redis:', msg, type(msg)
                # self.send(msg['data'])
        self.greenlets[user_key] = gevent.spawn(mailbox_processer)

        
    # ==============================================================================
    #  API methods
    # ==============================================================================
    def create_client(self, _):
        token = hashlib.sha1(os.urandom(64)).hexdigest()
        uid = self.redis.incr(K_USERS_ID)
        init_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.redis.set('users:%s'%token, uid)
        self.redis.hset('users:%d'%uid, 'init_at', init_at)
        return {'token': token}

    def online(self, data):
        token = data['token']
        uid = int(self.redis.get('users:%s'%token))
        init_at = self.redis.hget('users:%d'%uid, 'init_at')
        user_key = 'user-%d' % uid
        self.uid = uid
        # Current user's mail box
        self.subscribe(user_key)
        return {
            'uid': str(uid),
            'init_at': init_at
        }
        
    def offline(self, _):
        # Equal to `closed` ???
        pass

    def connect(self, data):
        ''' Connect to room or user '''
        target_type = data['type']
        target_id = int(data['id'])
        
        if target_type == 'room':
            room_key = 'room-%d' % target_id
            self.subscribe(room_key)
            room_online_msg = {
                'path': 'presence',
                'action': 'online',
                'uid': self.uid
            }
            self.redis.publish(room_key, json.dumps(room_online_msg))
            self.connected_rooms[target_id]= {'id': target_id}
            
        elif target_type == 'user':
            target_user_key = 'user-%d' % target_id
            session_id = self.redis.incr(K_SESSIONS_ID)
            session_key = 'session-%d' % session_id
            create_session_msg = {
                'path': 'session',
                'action': 'create', # Create
                'from_id': self.uid,
                'session_id': session_id,
            }
            # Mail to target user new session
            self.redis.publish(target_user_key, json.dumps(create_session_msg))
            self.subscribe(session_key)
            self.connected_users[target_id] = {
                'id': target_id,
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
                    'path': 'session',
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

    def rooms(self, _):
        return {'rooms': [1, 2]} # return room ids
        
    def create_room(self, _): pass
        
    def destory_room(self, _): pass

    def members(self, data):
        pass

    def history(self, data):
        pass
        
    def _message(self, data, msg):
        ''' Send message/typing to room or user(session) '''
        target_type = data['type'] # room, user(session)
        target_id = int(data['id'])

        channel = None
        if target_type == 'room':
            channel = 'room-%d'%(target_type, target_id)
        elif target_type == 'user':
            user = self.connected_users[target_id]
            session_id = user['session_id']
            channel = 'session-%d'%session_id
            
        ret = self.redis.publish(channel, json.dumps(msg))
        return {
            'target': target_type,
            'id': target_id,
            'ret': ret,
            'status': 'success'
        }
        
    def message(self, data):
        msg = {
            'path': data['path'],
            'body': data['body']
        }
        return self._message(data, msg)
        
    def typing(self, data):
        msg = {
            'path': data['path'],
            'typing': data['typing'] # True | False
        }
        return self._message(data, msg)

    ### API methods END ###

server = WSGIServer(('0.0.0.0', 9000),
                    WebSocketWSGIApplication(handler_cls=ChatWebSocket))
server.serve_forever()
