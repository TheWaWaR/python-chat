
$(document).ready ()->
    ws = new WebSocket "ws://#{location.host}/api"
    ws.onmessage = (event) ->
        data = JSON.parse event.data
        console.log data

        switch data.type
            when 'online' then $('#members').append "<p class=\"msg\"><span>[#{data.messages[0].datetime}]</span> <img src=\"http://www.gravatar.com/avatar/#{data.messages[0].cid}?s=15&d=identicon&f=y\" /></p>"
            when 'offline' then console.log data
            when 'message'
                for msg in data.messages
                    $('#logs').append "<p class=\"msg\"><span>[#{msg.datetime}]</span> <img src=\"http://www.gravatar.com/avatar/#{msg.cid}?s=15&d=identicon&f=y\" /> <span>:</span>#{msg.body}</p>"
                $('#logs').animate {scrollTop: $('#logs')[0].scrollHeight}, "300", "swing"
    
    $('form').submit (event) ->
        msg = $('#message-input').val()
        if msg.length > 0
            ws.send msg
            $('#message-input').val ""
        return false
    
    # Required    
    return false
