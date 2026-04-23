const { WebSocketServer } = require('ws')
const wss = new WebSocketServer({ port: 8080 })

wss.on('connection', ws => {
  console.log('✓ Client connecté')
  ws.on('message', raw => {
    const event = JSON.parse(raw)
    console.log('Event reçu:', event)
    wss.clients.forEach(c => {
      if (c !== ws && c.readyState === 1)
        c.send(raw.toString())
    })
  })
  ws.on('close', () => console.log('Client déconnecté'))
})

console.log('Serveur démarré sur ws://localhost:8080')