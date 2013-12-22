from geventwebsocket.handler import WebSocketHandler
from geventwebsocket.exceptions import WebSocketError
from gevent.pywsgi import WSGIServer

from datetime import datetime
import cgi
import json
from flask import Flask, request, render_template, session
from random import Random
from collections import OrderedDict

app = Flask(__name__)
app.secret_key = 'public'
app.debug = True

HISTORY = []
HISTORY_LIMIT = 80
MEMBERS = OrderedDict()
WS_DICT = {}
rand = Random()


@app.route('/')
def index():
    cid = session.get('cid', None)
    if cid is None:
        cid = rand.randint(2**29, 2**30)
        session['cid'] = cid
    return render_template('index.html', cid=cid)


@app.route('/api')
def api():
    global HISTORY
    # Get client id
    cid = session.get('cid', None)
    if cid is None:
        raise ValueError('cid is None')
        
    if request.environ.get('wsgi.websocket'):
        def boardcast(msg_type, messages):
            for member_lst in WS_DICT.values():
                for member in member_lst:
                    member.send(json.dumps({
                        'type': msg_type,
                        'messages': messages
                    }))

        ws = request.environ['wsgi.websocket']
        ws_id = id(ws)
        print 'New connect: %r --> %r' % (cid, ws_id)
        
        ws_lst = WS_DICT.get(cid, [])
        if len(ws_lst) == 0:
            now = datetime.now().strftime("%m-%d %H:%M:%S")            
            message = {
                'cid': cid,
                'datetime': now,
                'body': '>>> {online}'
            }
            boardcast('online', [message])
            MEMBERS[cid] = message
        ws_lst.append(ws)
        WS_DICT[cid] = ws_lst

        # Send history to connect socket
        ws.send(json.dumps({
            'type': 'message',
            'messages': HISTORY
        }))
        ws.send(json.dumps({
            'type': 'online',
            'messages': MEMBERS.values()
        }))

        def close_client(e=None):
            ws_lst.remove(ws)
            if len(ws_lst) == 0:
                now = datetime.now().strftime("%m-%d %H:%M:%S")
                message = {
                    'cid': cid,
                    'datetime': now,
                    'body': '>>> {offline}'
                }
                boardcast('offline', [message])
                MEMBERS.pop(cid)
                
            print u'[%r, %r]: {Closed}' % (cid, ws_id)
            if e is not None: print type(e)
            return ''
            
        while True:
            try:
                body = ws.receive()
                if body is None: return close_client()
            except WebSocketError, e:
                return close_client(e)
                
            now = datetime.now().strftime("%m-%d %H:%M:%S")
            body = unicode(cgi.escape(body), encoding='utf-8')
            print u'[%r, %r]: %s' % (cid, ws_id, body)
            message = {
                'cid': cid,
                'type': 'message',
                'datetime': now,
                'body': body
            }
            HISTORY.append(message)
            if len(HISTORY) > HISTORY_LIMIT+5: HISTORY = HISTORY[-HISTORY_LIMIT:]
            boardcast('message', [message])


if __name__ == '__main__':
    import sys
    port = int(sys.argv[1])
    http_server = WSGIServer(('0.0.0.0', port), app, handler_class=WebSocketHandler)
    print 'Server started at: 0.0.0.0:{0}'.format(port)
    http_server.serve_forever()
