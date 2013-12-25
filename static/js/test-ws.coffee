
$(document).ready () ->
    rooms = [];
    ws = new WebSocket "ws://#{location.hostname}:9000"
    ws.onmessage = (message) ->
        data = JSON.parse message.data
        console.log data
        switch data.path
            when 'init_client'
                msg = {path:'online'}
                msg.token = data.token
                ws.send (JSON.stringify msg)
            when 'online'
                msg = {path:'rooms'}
                ws.send (JSON.stringify msg)
            when 'rooms'
                for rid in data.rooms
                    rooms.push rid
                    msg = {path:'connect'}
                    msg.type = 'room'
                    msg.id = rid
                    ws.send (JSON.stringify msg)
            when 'connect'
                msg = {path:'message'}
                msg.type = data.type
                msg.id = data.id
                msg.body = "From: #{data.id}"
                ws.send (JSON.stringify msg)
            when 'message'
                console.log 'Message.type:', data.type

    ws.onopen = () ->
        ws.send (JSON.stringify {path: 'init_client'})
