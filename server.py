import socket
import threading
import os
import time
import collections  

HOST = "0.0.0.0"  
PORT = 5000
ENCODING = "utf-8"
BUFFER_SIZE = 4096

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILES_DIR = os.path.join(BASE_DIR, "server_files")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

clients = {}         
rooms = {}            

CONGESTION_MODE = False          
CONGESTION_MAX_QUEUE = 1000      
CONGESTION_SEND_INTERVAL = 3.0   
broadcast_queue = collections.deque()
recent_drops = 0                


def send_line(sock, text: str):
    try:
        sock.sendall((text + "\n").encode(ENCODING))
    except OSError:
        pass


def log_line(room: str, text: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    path = os.path.join(LOGS_DIR, f"{room}.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {text}\n")


def send_history(sock, room: str, max_lines: int = 50):
    path = os.path.join(LOGS_DIR, f"{room}.log")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()[-max_lines:]
    for line in lines:
        line = line.rstrip("\n")
        send_line(sock, f"HIST|{line}")


def broadcast(room: str, text: str, exclude=None):
    """
    Broadcast a line to everyone in the room.

    If CONGESTION_MODE is OFF:
        - send immediately (normal behavior).
    If CONGESTION_MODE is ON:
        - enqueue the message in a global queue and let a background
          worker send slowly.
    """
    global CONGESTION_MODE, broadcast_queue, recent_drops

    if not CONGESTION_MODE:
        for s in list(rooms.get(room, set())):
            if s is exclude:
                continue
            try:
                send_line(s, text)
            except OSError:
                rooms[room].discard(s)
                clients.pop(s, None)
                s.close()
        return

    if len(broadcast_queue) >= CONGESTION_MAX_QUEUE:

        recent_drops += 1
        log_line(room, f"[CONGESTION] DROPPED message in room {room}: {text}")
        print(f"[CONGESTION] DROP - queue_len={len(broadcast_queue)}, drops={recent_drops}")
        return

    broadcast_queue.append((room, text, exclude))
    print(f"[CONGESTION] ENQUEUE room={room}, queue_len={len(broadcast_queue)}")


def room_state_line(room: str) -> str:
    users = [clients[s]["name"] for s in rooms.get(room, set()) if s in clients]
    listing = ",".join(users)
    return f"ROOM_STATE|{room}|{listing}"


def broadcast_room_state(room: str):
    line = room_state_line(room)
    broadcast(room, line)


def handle_switch_room(sock, new_room: str):
    """Move a user from one room to another (used for breakout rooms etc.)."""
    info = clients.get(sock)
    if not info:
        send_line(sock, "ERROR|Not logged in")
        return
    old_room = info["room"]
    name = info["name"]

    new_room = new_room.strip()
    if not new_room:
        send_line(sock, "ERROR|Room name cannot be empty")
        return
    if new_room == old_room:
        send_line(sock, f"INFO|Already in room #{new_room}")
        return

    if old_room in rooms:
        rooms[old_room].discard(sock)
        broadcast(old_room, f"INFO|{name} left the room.")
        broadcast_room_state(old_room)
        log_line(old_room, f"{name} left the room")

    clients[sock]["room"] = new_room
    rooms.setdefault(new_room, set()).add(sock)

    send_line(sock, f"INFO|Switched to room #{new_room}")
    send_line(sock, f"CURRENT_ROOM|{new_room}")
    send_history(sock, new_room)
    broadcast(new_room, f"INFO|{name} joined the room.", exclude=sock)
    broadcast_room_state(new_room)
    log_line(new_room, f"{name} joined the room")


def congestion_worker():
    """
    Background worker that slowly drains the broadcast_queue
    when congestion mode is ON. This simulates a slow, congested link.
    """
    global CONGESTION_MODE, broadcast_queue
    while True:
        if broadcast_queue:
            room, text, exclude = broadcast_queue.popleft()

            for s in list(rooms.get(room, set())):
                if s is exclude:
                    continue
                try:
                    send_line(s, text)
                except OSError:
                    rooms[room].discard(s)
                    clients.pop(s, None)
                    s.close()

            print(f"[CONGESTION] SEND room={room}, remaining_queue={len(broadcast_queue)}")

            if CONGESTION_MODE:
                time.sleep(CONGESTION_SEND_INTERVAL)
            else:
                time.sleep(0.01)
        else:
            time.sleep(0.05)


def handle_client(sock: socket.socket, addr):
    global CONGESTION_MODE, broadcast_queue, recent_drops

    buffer = b""
    name = None
    room = None

    send_line(sock, "INFO|Connected. GUI will handle LOGIN automatically.")
    send_line(sock, "INFO|Commands: STATS, ROOM_LIST, ROOM_USERS, SWITCH_ROOM via GUI.")
    send_line(sock, "INFO|Congestion commands: CONGESTION_ON, CONGESTION_OFF, CONGESTION_STATS")

    try:
        while True:
            data = sock.recv(BUFFER_SIZE)
            if not data:
                break
            buffer += data

            while True:
                if b"\n" not in buffer:
                    break
                line_bytes, buffer = buffer.split(b"\n", 1)
                line = line_bytes.decode(ENCODING).strip()
                if not line:
                    continue

                if name is None and line.startswith("LOGIN|"):
                    parts = line.split("|", 2)
                    if len(parts) != 3:
                        send_line(sock, "ERROR|Bad LOGIN format")
                        continue
                    _, name_raw, room_raw = parts
                    name = name_raw.strip() or f"user_{addr[1]}"
                    room = room_raw.strip() or "general"

                    clients[sock] = {"name": name, "room": room}
                    rooms.setdefault(room, set()).add(sock)

                    send_line(sock, f"INFO|Welcome {name}! You joined room #{room}.")
                    total_users = len(clients)
                    total_rooms = len([r for r in rooms if rooms[r]])
                    send_line(sock, f"STATS|rooms={total_rooms}|users={total_users}")
                    send_line(sock, f"CURRENT_ROOM|{room}")
                    send_history(sock, room)
                    broadcast(room, f"INFO|{name} joined the room.", exclude=sock)
                    broadcast_room_state(room)
                    log_line(room, f"{name} joined the room")
                    continue

                if name is None or room is None:
                    send_line(sock, "ERROR|You must LOGIN first")
                    continue

                if line.startswith("MSG|"):
                    msg_text = line[4:].strip()
                    if msg_text:
                        broadcast(room, f"MSG|{name}|{msg_text}")
                        log_line(room, f"{name}: {msg_text}")

                elif line == "FILE_LIST":
                    files = os.listdir(FILES_DIR)
                    listing = ",".join(files)
                    send_line(sock, f"FILE_LIST|{listing}")

                elif line.startswith("FILE_UPLOAD|"):
                    parts = line.split("|", 2)
                    if len(parts) != 3:
                        send_line(sock, "ERROR|Bad FILE_UPLOAD header")
                        continue
                    _, filename, size_str = parts
                    try:
                        total_size = int(size_str)
                    except ValueError:
                        send_line(sock, "ERROR|Bad file size")
                        continue

                    remaining = total_size
                    chunks = []

                    if buffer:
                        take = min(len(buffer), remaining)
                        chunks.append(buffer[:take])
                        buffer = buffer[take:]
                        remaining -= take

                    while remaining > 0:
                        chunk = sock.recv(min(BUFFER_SIZE, remaining))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)

                    if remaining != 0:
                        send_line(sock, "ERROR|File upload interrupted")
                        continue

                    save_path = os.path.join(FILES_DIR, os.path.basename(filename))
                    with open(save_path, "wb") as f:
                        for c in chunks:
                            f.write(c)

                    send_line(sock, f"INFO|File {filename} uploaded successfully.")
                    broadcast(room, f"INFO|{name} shared file: {filename}", exclude=sock)
                    log_line(room, f"{name} uploaded file {filename}")

                elif line.startswith("FILE_DOWNLOAD|"):
            
                    parts = line.split("|", 1)
                    if len(parts) != 2:
                        send_line(sock, "ERROR|Bad FILE_DOWNLOAD header")
                        continue
                    _, filename = parts
                    path = os.path.join(FILES_DIR, os.path.basename(filename))
                    if not os.path.exists(path):
                        send_line(sock, "ERROR|File not found")
                        continue
                    size = os.path.getsize(path)
                    send_line(sock, f"FILE_DATA|{filename}|{size}")
                    with open(path, "rb") as f:
                        while True:
                            chunk = f.read(BUFFER_SIZE)
                            if not chunk:
                                break
                            sock.sendall(chunk)

                elif line == "ROOM_USERS":
                    current_room = clients.get(sock, {}).get("room", room)
                    send_line(sock, room_state_line(current_room))

                elif line == "ROOM_LIST":
                    active_rooms = [r for r in rooms if rooms[r]]
                    listing = ",".join(sorted(active_rooms))
                    send_line(sock, f"ROOM_LIST|{listing}")

                elif line == "STATS":
                    total_users = len(clients)
                    total_rooms = len([r for r in rooms if rooms[r]])
                    send_line(sock, f"STATS|rooms={total_rooms}|users={total_users}")

                elif line.startswith("SWITCH_ROOM|"):
                    new_room = line.split("|", 1)[1]
                    handle_switch_room(sock, new_room)
                    room = clients.get(sock, {}).get("room", room)

                elif line == "CONGESTION_ON":
                    CONGESTION_MODE = True
                    send_line(sock, "INFO|Server congestion simulation: ON")
                    print("[CONGESTION] MODE ON")

                elif line == "CONGESTION_OFF":
                    CONGESTION_MODE = False
                    send_line(sock, "INFO|Server congestion simulation: OFF")
                    print("[CONGESTION] MODE OFF")

                elif line == "CONGESTION_STATS":
                    qlen = len(broadcast_queue)
                    send_line(
                        sock,
                        f"CONGESTION|mode={'ON' if CONGESTION_MODE else 'OFF'}"
                        f"|queue_len={qlen}|max_queue={CONGESTION_MAX_QUEUE}"
                        f"|send_interval={CONGESTION_SEND_INTERVAL}"
                        f"|drops={recent_drops}"
                    )

                else:
                    send_line(sock, "ERROR|Unknown command")

    except ConnectionResetError:
        pass
    finally:
        info = clients.pop(sock, None)
        if info:
            name = info["name"]
            room = info["room"]
            if room in rooms:
                rooms[room].discard(sock)
            broadcast(room, f"INFO|{name} left the room.")
            broadcast_room_state(room)
            log_line(room, f"{name} left the room")
        sock.close()


def start_server():
    print(f"Server listening on {HOST}:{PORT}")

    threading.Thread(target=congestion_worker, daemon=True).start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        while True:
            client_sock, addr = s.accept()
            t = threading.Thread(target=handle_client, args=(client_sock, addr), daemon=True)
            t.start()


if __name__ == "__main__":
    start_server()
