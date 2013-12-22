from geventwebsocket.handler import WebSocketHandler
from geventwebsocket.exceptions import WebSocketError
from gevent.pywsgi import WSGIServer

from datetime import datetime
import cgi
from flask import Flask, request, render_template, session
from random import Random

app = Flask(__name__)
app.secret_key = 'public'

HISTORY = []
HISTORY_LIMIT = 20
WS_DICT = {}
rand = Random()


@app.route('/')
def index():
    cid = session.get('cid', None)
    if cid is None:
        session['cid'] = rand.randint(2**29, 2**30)
    return render_template('index.html', cid=cid)


@app.route('/api')
def api():
    global HISTORY
    # Get client id
    cid = session.get('cid', None)
    if cid is None:
        raise ValueError('cid is None')
        
    if request.environ.get('wsgi.websocket'):
            
        ws = request.environ['wsgi.websocket']
        ws_id = id(ws)
        print 'New connect: %r --> %r' % (cid, ws_id)
        
        ws_lst = WS_DICT.get(cid, [])
        ws_lst.append(ws)
        WS_DICT[cid] = ws_lst

        # Send history to connect socket
        for _msg in HISTORY: ws.send(_msg)
            
        def close_client(e=None):
            ws_lst.remove(ws)
            print u'[%r, %r]: {Closed}' % (cid, ws_id)
            if e is not None: print type(e)
            return ''
            
        while True:
            try:
                message = ws.receive()
                now = datetime.now().strftime("%m-%d %H:%M")
                if message is not None:
                    message = unicode(cgi.escape(message), encoding='utf-8')
                    print u'[%r, %r]: %s' % (cid, ws_id, message)
                    message = u'%r@[%s]:  %s' % (cid, now, message)
                else:
                    return close_client()
            except WebSocketError, e:
                return close_client(e)

            HISTORY.append(message)
            if len(HISTORY) > HISTORY_LIMIT+5: HISTORY = HISTORY[-HISTORY_LIMIT:]
            
            for member_lst in WS_DICT.values():
                for member in member_lst:
                    member.send(message)


if __name__ == '__main__':
    import sys
    port = int(sys.argv[1])
    http_server = WSGIServer(('0.0.0.0', port), app, handler_class=WebSocketHandler)
    print 'Server started at: 0.0.0.0:{0}'.format(port)
    http_server.serve_forever()
