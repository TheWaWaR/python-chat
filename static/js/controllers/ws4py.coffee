

ws = null
chatApp = angular.module "chatApp", []

chatApp.factory "ChatService", ()->
    service = {}
    
    service.setOnmessage = (callback) ->
        service.onmessage = callback
    service.setOnopen = (callback) ->
        service.onopen = callback
        
    service.connect = () ->
        return if service.ws

        ws = new WebSocket "ws://#{location.hostname}:9000"
        ws.onopen = (event) ->
            service.onopen(event)
        ws.onmessage = (event) ->
            service.onmessage(event)

        service.ws = ws

    return service
    
chatApp.controller "Ctrl", ['$scope', 'ChatService', ($scope, ChatService) ->
    $scope.templateUrl = "/static/partials/ws4py.html"
    $scope.rooms = []
    $scope.users = []

    ChatService.setOnopen () ->
        ws.send (JSON.stringify {path: 'create_client'})
        console.log 'Opened'
        
    ChatService.setOnmessage (event) ->
        data = JSON.parse event.data
        console.log data
        switch data.path
            when 'create_client'
                msg = {path:'online'}
                msg.token = data.token
                ws.send (JSON.stringify msg)
            when 'online'
                msg = {path:'rooms'}
                ws.send (JSON.stringify msg)
            when 'rooms'
                for rid in data.rooms
                    $scope.rooms.push rid
            when 'connect'
                msg = {path:'message'}
                msg.type = data.type
                msg.oid = data.id
                msg.body = "From: #{data.id}"
                ws.send (JSON.stringify msg)
            when 'message'
                console.log 'Message.type:', data.type

        $scope.$apply()
        
    ChatService.connect()
    
    return 'ok'
]

    
$(document).ready ()->
    $('form').submit (event) ->
        msg = $('#message-input').val()
        if msg.length > 0
            ws.send msg
            $('#message-input').val ""
        return false
