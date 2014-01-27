#!/usr/bin/env python
#coding: utf-8

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


class Message(object):
    messages = {}
    
    @staticmethod
    def history(rid):
        return Message.messages.get(rid, [])

    @staticmethod
    def save(from_type, from_id, to_type, to_id, body):
        msg = {
            'from_type': from_type,
            'from_id': from_id,
            'to_type': to_type,
            'to_id': to_id,
            'body': body,
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        if to_id in Message.messages:
            Message.messages[to_id].append(msg)
        else:
            Message.messages[to_id] = [msg]   # just for room
        # print 'Message.messages >>> ', Message.messages
        return msg['created_at']
    

class Visitor(object):
    K_VISITORS = 'visitors' # Active visitors
    K_VISITORS_ID = 'visitors:id'
    K_VISITORS_TOKEN = 'visitors:token' # Hash table: token ==> vid
    
    def __init__(self, rd, oid, name):
        oid = int(oid)
        self.rd = rd
        self.oid = oid          # hget return a `str`
        self.name = name
        self.KEY = Visitor.key(oid)

    def destory(self):
        self.rd.delete(self.KEY) # Seems won't happen for now

    def online(self):
        self.rd.hincrby(Visitor.K_VISITORS, self.oid, 1)

    def offline(self):
        current = self.rd.hincrby(Visitor.K_VISITORS, self.oid, -1)
        if not current:
            self.rd.hdel(Visitor.K_VISITORS, self.oid)
        return current

    @staticmethod
    def key(vid): return 'visitor:%d'%vid
    
    @staticmethod
    def create(rd, name):
        oid = rd.incr(Visitor.K_VISITORS_ID)
        oid = int(oid)
        # init_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        visitor = Visitor(rd, oid, name)
        rd.hset(visitor.KEY, 'oid', oid)
        rd.hset(visitor.KEY, 'name', name)
        # rd.hset(visitor.KEY, 'init_at', init_at)

        token = hashlib.sha1(os.urandom(64)).hexdigest()
        rd.hset(Visitor.K_VISITORS_TOKEN, token, oid)
        return token

    @staticmethod
    def load_by_id(rd, vid):
        ''' Only for get other visitor's information '''
        data = rd.hgetall(Visitor.key(vid))
        return Visitor(rd, data['oid'], data['name'])

    @staticmethod
    def load_by_token(rd, token):
        ''' Must called by current visitor '''
        vid = rd.hget(Visitor.K_VISITORS_TOKEN, token)
        return None if vid is None else Visitor.load_by_id(rd, int(vid)) 
    
    @staticmethod
    def is_online(rd, vid):
        return rd.hexists(Visitor.K_VISITORS, vid)
        
    @staticmethod
    def online_vids(rd):
        return rd.hkeys(Visitor.K_VISITORS)
        
    @staticmethod
    def online_visitors(rd):
        vids = Visitor.online_vids(rd)
        return [Visitor.load_by_id(vid) for vid in vids]


class User(object):
    K_USERS = 'users' # Active users
    K_USERS_ID = 'users:id'
    K_USERS_TOKEN = 'users:token' # Hash table: token ==> uid
    
    def __init__(self, rd, oid, name):
        oid = int(oid)
        self.rd = rd
        self.oid = oid          # hget return a `str`
        self.name = name
        self.KEY = User.key(oid)

    def destory(self):
        self.rd.delete(self.KEY) # Seems won't happen for now

    def online(self):
        self.rd.hincrby(User.K_USERS, self.oid, 1)

    def offline(self):
        current = self.rd.hincrby(User.K_USERS, self.oid, -1)
        if not current:
            self.rd.hdel(User.K_USERS, self.oid)
        return current
            
    @staticmethod
    def key(uid): return 'user:%d'%uid
    
    @staticmethod
    def create(rd, name):
        oid = rd.incr(User.K_USERS_ID)
        oid = int(oid)
        # init_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        user = User(rd, oid, name)
        rd.hset(user.KEY, 'oid', oid)
        rd.hset(user.KEY, 'name', name)
        # rd.hset(user.KEY, 'init_at', init_at)

        token = hashlib.sha1(os.urandom(64)).hexdigest()
        rd.hset(User.K_USERS_TOKEN, token, oid)
        
        return token

    @staticmethod
    def load_by_id(rd, uid):
        ''' Only for get other user's information '''
        data = rd.hgetall(User.key(uid))
        return User(rd, data['oid'], data['name'])

    @staticmethod
    def load_by_token(rd, token):
        ''' Must called by current user '''
        uid = rd.hget(User.K_USERS_TOKEN, token)
        return None if uid is None else User.load_by_id(rd, int(uid)) 
    
    @staticmethod
    def is_online(rd, uid):
        return rd.hexists(User.K_USERS, uid)
        
    @staticmethod
    def online_uids(rd):
        return rd.hkeys(User.K_USERS)
        
    @staticmethod
    def online_users(rd):
        uids = User.online_uids(rd)
        return [User.load_by_id(uid) for uid in uids]


class Group(object):
    pass

class Room(object):
    K_ROOMS = 'rooms' # Active rooms
    K_ROOMS_ID = 'rooms:id' # Int: next room id
    
    def __init__(self, rd, oid, name, channel):
        oid = int(oid)
        self.rd = rd
        self.oid = oid
        self.name = name
        self.channel = channel
        self.KEY = Room.key(oid) # Object key
        self.KEY_MEMBERS = Room.key_members # Member list key

    @staticmethod
    def create(rd, name):
        oid = rd.incr(Room.K_ROOMS_ID)
        oid = int(oid)
        rd.lpush(Room.K_ROOMS, oid)
        channel = 'room-%d' % oid
        room = Room(rd, oid, name, channel)
        rd.hset(room.KEY, 'oid', oid) 
        rd.hset(room.KEY, 'name', name)
        rd.hset(room.KEY, 'channel', channel)
        return room

    def destory(self):
        ''' unused for now '''
        self.rd.delete(self.KEY)

    @staticmethod
    def key(rid): return 'room:%d'%rid # Hash table: field ==> value
        
    @staticmethod
    def key_members(rid): return 'room:%d:members'%rid # Hash table: uid ==> True

    @staticmethod
    def load_by_id(rd, rid):
        data = rd.hgetall(Room.key(rid))
        return Room(rd, data['oid'], data['name'], data['channel'])
        
    @staticmethod
    def ids(rd):
        return rd.lrange(Room.K_ROOMS, 0, -1)
    
    @staticmethod
    def members(rd, rid):
        return rd.hkeys(Room.key_members(rid))

    @staticmethod
    def has_member(rd, rid, uid):
        return rd.hexists(Room.key_members(rid), uid)

    @staticmethod
    def push(rd, rid, uid):
        return rd.hset(Room.key_members(rid), uid, True)

    @staticmethod
    def pop(rd, rid, uid):
        return rd.hdel(Room.key_members(rid), uid)
        

rd = redis.StrictRedis(connection_pool=pool)
for name in ('USA', 'China', 'Japan'):
    print 'Create room:', name
    Room.create(rd, name)

class ChatWebSocket(WebSocket):
    keep_channels = ['system', ]
    cls_dict = {
        'user': User,
        'visitor': Visitor
    }

    # ==============================================================================
    #  WebSocket method override
    # ==============================================================================
    def opened(self):
        self.redis = redis.StrictRedis(connection_pool=pool)
        self.greenlets = {}
        self.pubsubs = {}
        self.queues = {}
        
        self.connected_visitors = {} # {'id': uid}
        self.connected_users = {} # {'id': uid}
        self.connected_rooms = {} # {'id': rid}
        
        # Start global channels
        for name in ChatWebSocket.keep_channels:
            self.subscribe(name, 0)
        
        print 'Opened!'

    def closed(self, code, reason=None):
        
        print 'Start closing......'
        # 1. Unsubscribe global channels
        print '1. Unsubscribe global channels'
        for g_key in ChatWebSocket.keep_channels:
            self.unsubscribe(g_key, 0)

        # 2. Unsubscribe users
        print '2. Unsubscribe users'
        for uid in self.connected_users:
            self.unsubscribe('user', uid)

        # 3. Unsubscribe rooms
        print '3. Unsubscribe rooms'
        for rid in self.connected_rooms:
            self.unsubscribe('room', rid)

        # 4. Unsubscribe current user's mailbox
        print '4. Unsubscribe current user/visitor\'s mailbox'
        if hasattr(self, 'obj'):
            self.unsubscribe(self.user_type, self.obj.oid)

        # 5. Notify all rooms/groups/users
        current_cnt = self.obj.offline()
        print 'current_cnt:', current_cnt
        if hasattr(self, 'obj') and current_cnt == 0:
            print 'Real offline'
            offline_msg = {
                'path': 'presence',
                'action': 'offline',
                'oid': self.obj.oid
            }
            for uid in self.connected_users:
                user_key = 'user-%d'%uid
                self.redis.publish(user_key, json.dumps(offline_msg))
            for rid in self.connected_rooms:
                self.leave({'oid': rid})
                room_key = 'room-%d'%rid
                self.redis.publish(room_key, json.dumps(offline_msg))
                
        assert len(self.greenlets.keys()) == 0, 'Unclosed greenlets: %r' % self.greenlets
        assert len(self.pubsubs.keys()) == 0, 'Unclosed pubsubs: %r' % self.pubsubs
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
            'users'         : self.users,
            'visitors'      : self.visitors,
            # Room
            'rooms'         : self.rooms,       # List available rooms
            'create_room'   : self.create_room, # 
            'destory_room'  : self.destory_room, # NOTE: Owner/Admin only
            'members'       : self.members, # Get user list by room id
            'join'          : self.join,    # Join room
            'leave'         : self.leave,   # Leave room
            # Message
            'history'       : self.history, # Get message history
            'message'       : self.message, # Send message to room or user(mailbox)
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
    def unsubscribe(self, target_type, target_id):
        channel = '%s-%d' % (target_type, target_id)
        
        pubsub = self.pubsubs.pop(channel)
        greenlet = self.greenlets.pop(channel)
        pubsub.unsubscribe(channel)
        greenlet.join()


    def subscribe(self, target_type, target_id):
        channel = '%s-%d' % (target_type, target_id)

        if target_type in ('room', 'group') and not Room.has_member(self.redis, target_id, self.user.oid):
            join_msg = {
                'path': 'presence',
                'action': 'join',
                'type': target_type,
                'oid': target_id,
                'member': { 'oid': self.user.oid, 'name': self.user.name }
            }
            self.redis.publish(channel, json.dumps(join_msg))
        
        print 'Subscribe channel:', channel
        pubsub = self.redis.pubsub()
        self.pubsubs[channel] = pubsub
        pubsub.subscribe(channel)
        queue = pubsub.listen()
        queue.next()
        self.queues[channel] = queue

        def channel_processor():
            while True:
                msg = queue.next()
                msg_type = msg['type']
                
                if msg_type == 'subscribe':
                    print 'subscribe to mailbox', self.obj.oid
                    continue
                if msg_type  == 'unsubscribe':
                    print 'Exit channel:', channel
                    pubsub.close()
                    break

                print 'Received message from redis(channel):', msg
                data = json.loads(msg['data'])
                data['to_type'] = target_type
                data['to_id'] = target_id
                self.send(json.dumps(data))
                
        self.greenlets[channel] = gevent.spawn(channel_processor)


    def start_mailbox(self):
        ''' Current user/visitor's Mailbox '''
        
        channel = '%s-%d' % (self.user_type, self.obj.oid)
        if channel in self.greenlets:
            print 'Mailbox already started!'
            
        print 'Starting mailbox:', channel
        pubsub = self.redis.pubsub()
        self.pubsubs[channel] = pubsub
        pubsub.subscribe(channel)
        
        queue = pubsub.listen()
        queue.next()
        
        def mailbox_processer():
            while True:
                msg = queue.next()
                msg_type = msg['type']
                if msg_type == 'subscribe':
                    print 'subscribe to mailbox:', self.obj.oid
                    continue
                if msg_type == 'unsubscribe':
                    print 'Exit mail box:', channel
                    pubsub.close()
                    break
    
                data = json.loads(msg['data'])
                path = data['path']
                if path == 'message':
                    pass
                elif path == 'presence':
                    pass
                else:
                    raise ValueError('Mailbox received bad data:' % msg)
                    
                print 'Received message from redis(mailbox):', msg, type(msg)
                self.send(msg['data'])
        self.greenlets[channel] = gevent.spawn(mailbox_processer)

        
    # ==============================================================================
    #  API methods
    # ==============================================================================
    def create_client(self, data):
        name = '%s-%s' % (data['type'].upper(), (hashlib.sha1(os.urandom(64)).hexdigest())[:6])
        Cls = ChatWebSocket.cls_dict[data['type']]
        token = Cls.create(self.redis, name)
        return {'token': token}

    def online(self, data):
        token = data['token']
        Cls = ChatWebSocket.cls_dict[data['type']]
        obj = Cls.load_by_token(self.redis, token)
        if obj is None:
            return {'reset': True}
        else:
            if data['type'] in ('user', 'visitor'):
                setattr(self, data['type'], obj)
                self.user_type = data['type']
            else:
                return {'status': 'error', 'message': 'Invalid user type:%s' % data['type']}
            self.obj = obj
            self.obj.online()
            # Current user's mail box
            self.start_mailbox()
            print 'Onlined'
            return {'oid': self.obj.oid, 'name': self.obj.name }
        
    def offline(self, _):
        # Equal to `closed` ???
        self.user.offline()

    def users(self, data):
        objs = []
        if self.user_type == 'user':
            objs = []           # friends
        elif self.user_type == 'visitor':
            objs = User.online_users(self.redis)
        return {'users': objs}


    def visitors(self, data):
        return {}
        
    def join(self, data):
        ''' Join to room '''
        rid = int(data['oid'])
        print 'join(%d)' % rid
        Room.push(self.redis, rid, self.user.oid)
        self.subscribe('room', rid)
        self.connected_rooms[rid] =  None
        return { 'status' : 'success', 'oid': rid }
        
    def leave(self, data):
        ''' Leave a room '''
        rid = int(data['oid'])
        print 'leave(%d)' % rid
        Room.pop(self.redis, rid, self.user.oid)

        channel = '%s-%d' % ('room', rid)
        leave_msg = {
            'path': 'presence',
            'action': 'leave',
            'type': 'room',
            'oid': rid,
            'member': {'oid': self.obj.oid }
        }
        self.redis.publish(channel, json.dumps(leave_msg))
        
        return { 'status' : 'success' }

    def rooms(self, _):
        rids = Room.ids(self.redis)
        records = [self.redis.hgetall(Room.key(int(rid))) for rid in rids]
        return {'rooms': records } # return rooms
        
    def create_room(self, _): pass
        
    def destory_room(self, _): pass

    def members(self, data):
        rid = int(data['oid'])
        uids = Room.members(self.redis, rid)
        users = [self.redis.hgetall(User.key(int(uid))) for uid in uids]
        return {'members': users, 'oid': rid}

    def history(self, data):
        oid = data['oid']
        return { 'oid': oid, 'messages': Message.history(oid) }
        
        
    def _message(self, data, msg):
        ''' Send message/typing to room or user(session) '''
        to_type = data['type'] # room, user(session)
        to_id = int(data['oid'])

        channel = '%s-%d' % (to_type, to_id)
        
        from_type = self.user_type
        from_id = self.obj.oid
        msg['path'] = data['path']
        msg['from_type'] = from_type
        msg['from_id'] = from_id
        if 'body' in msg:
            created_at = Message.save(from_type, from_id, to_type, to_id, msg['body'])
            msg['created_at'] = created_at
        ret = self.redis.publish(channel, json.dumps(msg))
        return {'status': 'ok'}
        
    def message(self, data):
        print 'message.data:', data
        msg = { 'body': data['body'] }
        return self._message(data, msg)
        
    def typing(self, data):
        msg = { 'typing': data['typing'] } # True | False
        return self._message(data, msg)
        

    ### API methods END ###

server = WSGIServer(('0.0.0.0', 9000),
                    WebSocketWSGIApplication(handler_cls=ChatWebSocket))
server.serve_forever()
