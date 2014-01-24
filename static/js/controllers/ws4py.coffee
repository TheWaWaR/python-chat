

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
    $scope.members = {}
    $scope.users = {}
    $scope.visitors = {}

    $scope.send = (type, id) ->
        # body = $('#message-input-'+id).val()
        body = this.text
        if body.length > 0
            msg = {path:'message', type:type, id: id, body: body}
            console.log 'send:', msg
            ws.send (JSON.stringify msg)
            # $('#message-input-'+id).val ""
            this.text = ""

    ChatService.setOnopen () ->
        ws.send (JSON.stringify {path: 'create_client'})
        console.log 'Opened'
        
    ChatService.setOnmessage (event) ->
        data = JSON.parse event.data
        console.log '<<DATA>>:', data
        switch data.path
            when 'create_client'
                msg = {path:'online'}
                msg.token = data.token
                ws.send (JSON.stringify msg)
            when 'online'
                msg = {path:'rooms'}
                ws.send (JSON.stringify msg)
            when 'rooms'
                $scope.rooms = data.rooms
                for room in data.rooms
                    msg = {path: 'join', id: room.oid}
                    ws.send (JSON.stringify msg)
                console.log 'rooms:', $scope.rooms
            when 'join'
                msg = {path: 'members', id: data.id}
                ws.send (JSON.stringify msg)
                console.log 'Joined:', data
            when 'members'
                $scope.members[data.id] = {}
                for member in data.members
                    $scope.members[data.id][member.oid] = member
                console.log 'Get members:', $scope.members, data.members
            when 'presence'
                switch data.type
                    when 'room'
                        switch data.action
                            when 'join'
                                $scope.members[data.id][data.member.oid] = data.member
                            when 'leave'
                                delete $scope.members[data.id][data.member.oid]
            when 'message'
                switch data.type
                    when 'room'
                        console.log 'received message:', data
                        $('#room-'+data.id).append "#{data.from}: #{data.body}<br />"
                console.log 'Message.type:', data.type

        $scope.$apply()
        
    ChatService.connect()
    
    return 'ok'
]
