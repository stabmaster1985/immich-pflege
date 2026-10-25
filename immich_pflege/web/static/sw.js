// Service Worker nur fürs Installieren als App: alles geht direkt ans Netz, nichts wird zwischengespeichert
// (die Daten sollen immer aktuell sein, und API-Antworten gehören nicht in einen Cache).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
