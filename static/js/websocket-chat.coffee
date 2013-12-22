
$(document).ready ()->
    ws = new WebSocket "ws://#{location.host}/api"
    ws.onmessage = (event) ->
        msgs = JSON.parse event.data
        console.log msgs
        for msg in msgs
            $('#log').append "<p class=\"msg\"><span>[#{msg.datetime}]</span> <img src=\"http://www.gravatar.com/avatar/#{msg.cid}?s=15&d=identicon&f=y\" /> <span>:</span>#{msg.body}</p>"
        $('#messages-panel').animate {scrollTop: $('#messages-panel')[0].scrollHeight}, "300", "swing"
    
    $('form').submit (event) ->
        msg = $('#message-input').val()
        if msg.length > 0
            ws.send msg
            $('#message-input').val ""
        return false
    
    # Required    
    return false
