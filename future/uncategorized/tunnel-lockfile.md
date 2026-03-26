# Tunnel: guard against simultaneous instances

The tunnel client uses outbound WebSocket connections, so there's no port-binding collision to prevent duplicates. Running two tunnels for the same subdomain would cause undefined behavior — request metadata might go to one client while body chunks go to the other. Needs a PID lockfile or similar mechanism.
