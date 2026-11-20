self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(
    (async () => {
      const panel = new URL(self.registration.scope)
      const tabs = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      const open = tabs.find((client) => {
        const url = new URL(client.url)
        return (
          url.origin === panel.origin &&
          (url.pathname === panel.pathname || url.pathname === `${panel.pathname}index.html`)
        )
      })
      await (open ? open.focus() : self.clients.openWindow(panel.href))
    })()
  )
})
