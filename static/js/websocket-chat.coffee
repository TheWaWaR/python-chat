
$(document).ready ()->
    ws = new WebSocket "ws://#{location.host}/api"
    ws.onmessage = (msg) ->
        $('#log').append "<p>#{msg.data}</p>"
        $('#messages-panel').scrollTop $('#messages-panel')[0].scrollHeight
    
    $('form').submit (event) ->
        msg = $('#message-input').val()
        if msg.length > 0
            ws.send msg
            $('#message-input').val ""
        return false
    
    # Required    
    return false
