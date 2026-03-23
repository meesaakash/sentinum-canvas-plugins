To use this self-hosted livekit scribe overriding the default hyperscribe scribe within the same canvas-hyperscribe plugin, 

cd agent-server and run `docker compose down && docker compose up --build`

you can use `canvas logs --level ERROR` to monitor the logs from canvas for the plugin for debugging while it's running. 

Sometimes, the plugin is weird, when you initially launch the hyperscribe plugin in the Canvas page for a new telehealth phone call or in person encounter with the patient, it won't enable the mic till you pause then re-enable it. This needs to be looked into if its a bug with picking up the event properly on the first turn. 

