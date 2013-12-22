
$(document).ready ()->
    ws = new WebSocket "ws://#{location.host}/api"
    ws.onmessage = (event) ->
        msg = JSON.parse event.data
        $('#log').append "<p class=\"msg\"><span>[#{msg.datetime}]</span> <img src=\"http://www.gravatar.com/avatar/#{msg.cid}?s=15&d=identicon&f=y\" /> <span>:</span>#{msg.body}</p>"
        $('#messages-panel').scrollTop $('#messages-panel')[0].scrollHeight
    
    $('form').submit (event) ->
        msg = $('#message-input').val()
        if msg.length > 0
            ws.send msg
            $('#message-input').val ""
        return false
    
    # Required    
    return false
