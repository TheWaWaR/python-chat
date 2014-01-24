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

'''
   暂不支持Group
'''
class Visitor(object):
    pass

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
        self.rd.hset(User.K_USERS, self.oid, True)

    def offline(self):
        self.rd.hdel(User.K_USERS, self.oid)
        
    # def join_room(self, rid):
    #     Room.push(self.rd, rid, self.oid)
        
    # def leave_room(self, rid):
    #     Room.pop(self.rd, rid, self.oid)

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
        return User.load_by_id(rd, int(uid))
    
    @staticmethod
    def is_online(rd, uid):
        return rd.hexists(User.K_USERS, uid)
        
    @staticmethod
    def online_users(rd):
        return rd.hkeys(User.K_USERS)

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
            
        offline_msg = {
            'path': 'presence',
            'action': 'offline',
            'uid': self.user.oid
        }
        # 2. Unsubscribe users
        print '2. Unsubscribe users'
        for uid in self.connected_users:
            user_key = 'user-%d'%uid
            self.unsubscribe('user', uid)
            self.redis.publish(user_key, json.dumps(offline_msg))

        # 3. Unsubscribe rooms
        print '3. Unsubscribe rooms'
        for rid in self.connected_rooms:
            room_key = 'room-%d'%rid
            self.leave({'id': rid})
            self.redis.publish(room_key, json.dumps(offline_msg))

        # 4. Unsubscribe current user's mailbox
        print '4. Unsubscribe current user\'s mailbox'
        self.unsubscribe('user', self.user.oid)

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
        
        if target_type in ('room', 'group'):
            leave_msg = {
                'path': 'presence',
                'action': 'leave',
                'type': target_type,
                'id': target_id,
                'member': {'oid': self.user.oid }
            }
            self.redis.publish(channel, json.dumps(leave_msg))
        
        pubsub = self.pubsubs.pop(channel)
        greenlet = self.greenlets.pop(channel)
        pubsub.unsubscribe(channel)
        greenlet.join()

    def subscribe(self, target_type, target_id):
        channel = '%s-%d' % (target_type, target_id)

        if target_type in ('room', 'group'):
            join_msg = {
                'path': 'presence',
                'action': 'join',
                'type': target_type,
                'id': target_id,
                'member': {'oid': self.user.oid, 'name': self.user.name }
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
                    print 'subscribe to mailbox', self.user.oid
                    continue
                if msg_type  == 'unsubscribe':
                    print 'Exit channel:', channel
                    pubsub.close()
                    break

                print 'Received message from redis(channel):', msg
                data = json.loads(msg['data'])
                data['type'] = target_type
                data['id'] = target_id
                self.send(json.dumps(data))
                
        self.greenlets[channel] = gevent.spawn(channel_processor)


    def start_mailbox(self):
        ''' Current user's Mailbox '''
        
        user_key = 'user-%d' % self.user.oid
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
                msg_type = msg['type']
                if msg_type == 'subscribe':
                    print 'subscribe to mailbox', self.user.oid
                    continue
                if msg_type == 'unsubscribe':
                    print 'Exit mail box:', user_key
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
        self.greenlets[user_key] = gevent.spawn(mailbox_processer)

        
    # ==============================================================================
    #  API methods
    # ==============================================================================
    def create_client(self, _):
        token = User.create(self.redis, 'USER-' + (hashlib.sha1(os.urandom(64)).hexdigest())[:6])
        return {'token': token}

    def online(self, data):
        token = data['token']
        self.user = User.load_by_token(self.redis, token)
        # Current user's mail box
        self.start_mailbox()
        print 'Onlined'
        return { 'uid': self.user.oid }
        
    def offline(self, _):
        # Equal to `closed` ???
        pass

    def join(self, data):
        ''' Join to room '''
        rid = int(data['id'])
        print 'join(%d)' % rid
        Room.push(self.redis, rid, self.user.oid)
        self.subscribe('room', rid)
        self.connected_rooms[rid] =  None
        return { 'status' : 'success', 'id': rid }
        
    def leave(self, data):
        ''' Leave a room '''
        rid = int(data['id'])
        print 'leave(%d)' % rid
        self.unsubscribe('room', rid)
        Room.pop(self.redis, rid, self.user.oid)
        return { 'status' : 'success' }

    def rooms(self, _):
        rids = Room.ids(self.redis)
        records = [self.redis.hgetall(Room.key(int(rid))) for rid in rids]
        return {'rooms': records } # return rooms
        
    def create_room(self, _): pass
        
    def destory_room(self, _): pass

    def members(self, data):
        rid = int(data['id'])
        uids = Room.members(self.redis, rid)
        users = [self.redis.hgetall(User.key(int(uid))) for uid in uids]
        return {'members': users, 'id': rid}

    def history(self, data):
        pass
        
    def _message(self, data, msg):
        ''' Send message/typing to room or user(session) '''
        target_type = data['type'] # room, user(session)
        target_id = int(data['id'])

        channel = '%s-%d' % (target_type, target_id)
        msg['path'] = data['path']
        msg['from'] = self.user.oid
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
