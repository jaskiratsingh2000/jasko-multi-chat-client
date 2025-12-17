import socket
import threading
import queue
import os
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox, simpledialog

ENCODING = "utf-8"
BUFFER_SIZE = 4096

SERVER_PORT = 5000  

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

incoming = queue.Queue()
sock = None
connected = False
my_username = ""
current_room = ""
main_room = ""


def append_text(widget, msg: str, tag=None):
    widget.configure(state="normal")
    if tag:
        widget.insert(tk.END, msg + "\n", tag)
    else:
        widget.insert(tk.END, msg + "\n")
    widget.configure(state="disabled")
    widget.see(tk.END)

def update_user_list(listbox, users):
    listbox.delete(0, tk.END)
    for u in users:
        if u:
            listbox.insert(tk.END, u)

def poll_incoming(chat_box, user_listbox, status_var, room_label_var):
    global current_room
    while True:
        try:
            item = incoming.get_nowait()
        except queue.Empty:
            break

        kind = item[0]

        if kind == "CHAT":
            _, name, msg = item
            tag = "self" if name == my_username else "other"
            append_text(chat_box, f"[{name}] {msg}", tag=tag)

        elif kind == "INFO":
            _, text = item
            append_text(chat_box, f"(info) {text}", tag="info")

        elif kind == "HIST":
            _, text = item
            append_text(chat_box, f"(history) {text}", tag="history")

        elif kind == "ERROR":
            _, text = item
            append_text(chat_box, f"(error) {text}", tag="error")

        elif kind == "STATS":
            _, text = item
            append_text(chat_box, f"(stats) {text}", tag="stats")

        elif kind == "ROOM_STATE":
            _, room, users = item
            append_text(
                chat_box,
                f"(room #{room} members: {', '.join([u for u in users if u])})",
                tag="info",
            )
            update_user_list(user_listbox, users)

        elif kind == "STATUS":
            _, status_msg = item
            status_var.set(status_msg)

        elif kind == "CURRENT_ROOM":
            _, room = item
            current_room = room
            room_label_var.set(f"Room: {room}")
            append_text(chat_box, f"(info) You are now in room #{room}", tag="info")

        elif kind == "TEXT":
            _, text = item
            append_text(chat_box, text)

    chat_box.after(100, poll_incoming, chat_box, user_listbox, status_var, room_label_var)


def recv_loop():
    global sock, connected
    buffer = b""
    try:
        while connected:
            data = sock.recv(BUFFER_SIZE)
            if not data:
                incoming.put(("TEXT", "**Disconnected from server**"))
                incoming.put(("STATUS", "Disconnected"))
                break
            buffer += data

            while True:
                if b"\n" not in buffer:
                    break
                line_bytes, buffer = buffer.split(b"\n", 1)
                line = line_bytes.decode(ENCODING).strip()
                if not line:
                    continue

                if line.startswith("MSG|"):
                    _, name, msg = line.split("|", 2)
                    incoming.put(("CHAT", name, msg))

                elif line.startswith("INFO|"):
                    incoming.put(("INFO", line[5:]))

                elif line.startswith("HIST|"):
                    incoming.put(("HIST", line[5:]))

                elif line.startswith("FILE_LIST|"):
                    listing = line[len("FILE_LIST|"):]
                    files = listing.split(",") if listing else []
                    if not files or files == [""]:
                        incoming.put(("INFO", "Files on server: (none)"))
                    else:
                        incoming.put(("INFO", "Files on server:"))
                        for f in files:
                            if f:
                                incoming.put(("INFO", f"  - {f}"))

                elif line.startswith("FILE_DATA|"):
                    _, filename, size_str = line.split("|", 2)
                    try:
                        total_size = int(size_str)
                    except ValueError:
                        incoming.put(("ERROR", "Bad FILE_DATA header from server."))
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
                        incoming.put(("ERROR", "File download interrupted."))
                        continue

                    path = os.path.join(DOWNLOAD_DIR, os.path.basename(filename))
                    with open(path, "wb") as f:
                        for c in chunks:
                            f.write(c)
                    incoming.put(("INFO", f"Downloaded file to {path}"))

                elif line.startswith("ERROR|"):
                    incoming.put(("ERROR", line[6:]))

                elif line.startswith("ROOM_STATE|"):
                    _, room, users_str = line.split("|", 2)
                    users = users_str.split(",") if users_str else []
                    incoming.put(("ROOM_STATE", room, users))

                elif line.startswith("STATS|"):
                    incoming.put(("STATS", line[6:]))

                elif line.startswith("ROOM_LIST|"):
                    listing = line[len("ROOM_LIST|"):]
                    rooms = listing.split(",") if listing else []
                    if not rooms or rooms == [""]:
                        incoming.put(("INFO", "Active rooms: (none yet, only you)"))
                    else:
                        incoming.put(("INFO", "Active rooms:"))
                        for r in rooms:
                            if r:
                                incoming.put(("INFO", f"  - {r}"))

                elif line.startswith("CURRENT_ROOM|"):
                    _, room = line.split("|", 1)
                    incoming.put(("CURRENT_ROOM", room))

                elif line.startswith("CONGESTION|"):
                    incoming.put(("INFO", f"Congestion status: {line[len('CONGESTION|'):] }"))

                else:
                    incoming.put(("TEXT", line))
    except OSError:
        pass
    finally:
        connected = False
        sock = None
        incoming.put(("STATUS", "Disconnected"))


def connect_server(server_entry, username_entry, room_entry, status_var):
    global sock, connected, my_username, current_room, main_room
    if connected:
        messagebox.showinfo("Info", "Already connected.")
        return

    server_host = server_entry.get().strip() or "127.0.0.1"
    username = username_entry.get().strip()
    room = room_entry.get().strip() or "general"

    if not username:
        messagebox.showerror("Error", "Please enter a username.")
        return

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((server_host, SERVER_PORT))
    except OSError as e:
        messagebox.showerror("Error", f"Could not connect: {e}")
        return

    sock = s
    connected = True
    my_username = username
    current_room = room
    main_room = room
    status_var.set(f"Connected to {server_host}:{SERVER_PORT} as {username} (room: {room})")

    login_line = f"LOGIN|{username}|{room}\n"
    sock.sendall(login_line.encode(ENCODING))

    threading.Thread(target=recv_loop, daemon=True).start()
    incoming.put(("INFO", f"Connected as {username} in room #{room}"))


def send_message(message_entry):
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return
    text = message_entry.get().strip()
    if not text:
        return
    line = f"MSG|{text}\n"
    try:
        sock.sendall(line.encode(ENCODING))
    except OSError:
        messagebox.showerror("Error", "Failed to send message.")
        return
    message_entry.delete(0, tk.END)


def upload_file():
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return
    path = filedialog.askopenfilename(title="Select file to upload")
    if not path:
        return
    size = os.path.getsize(path)
    filename = os.path.basename(path)
    header = f"FILE_UPLOAD|{filename}|{size}\n"
    try:
        sock.sendall(header.encode(ENCODING))
        with open(path, "rb") as f:
            while True:
                chunk = f.read(BUFFER_SIZE)
                if not chunk:
                    break
                sock.sendall(chunk)
        incoming.put(("INFO", f"Uploaded {filename}"))
    except OSError as e:
        messagebox.showerror("Error", f"Upload failed: {e}")


def list_files():
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return
    try:
        sock.sendall(b"FILE_LIST\n")
    except OSError as e:
        messagebox.showerror("Error", f"Request failed: {e}")


def download_file():
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return
    filename = simpledialog.askstring("Download", "Enter filename to download:")
    if not filename:
        return
    line = f"FILE_DOWNLOAD|{filename}\n"
    try:
        sock.sendall(line.encode(ENCODING))
    except OSError as e:
        messagebox.showerror("Error", f"Request failed: {e}")


def request_room_users():
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return
    try:
        sock.sendall(b"ROOM_USERS\n")
    except OSError as e:
        messagebox.showerror("Error", f"Request failed: {e}")


def request_stats():
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return
    try:
        sock.sendall(b"STATS\n")
    except OSError as e:
        messagebox.showerror("Error", f"Request failed: {e}")


def request_room_list():
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return
    try:
        sock.sendall(b"ROOM_LIST\n")
    except OSError as e:
        messagebox.showerror("Error", f"Request failed: {e}")


def switch_room(new_room: str):
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return
    new_room = new_room.strip()
    if not new_room:
        return
    line = f"SWITCH_ROOM|{new_room}\n"
    try:
        sock.sendall(line.encode(ENCODING))
    except OSError as e:
        messagebox.showerror("Error", f"Switch failed: {e}")


def create_breakout_room():
    global current_room, main_room
    if not connected:
        messagebox.showerror("Error", "Connect first to create a breakout room.")
        return
    name = simpledialog.askstring("Create Breakout Room", "Enter breakout name:")
    if not name:
        return
    parent = main_room or current_room or "general"
    breakout_room = f"{parent}-BO-{name}"
    switch_room(breakout_room)


def back_to_main_room():
    global main_room
    if not connected:
        messagebox.showerror("Error", "Not connected.")
        return
    if not main_room:
        messagebox.showinfo("Info", "No main room recorded.")
        return
    switch_room(main_room)

def congestion_on():
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return
    try:
        sock.sendall(b"CONGESTION_ON\n")
    except OSError as e:
        messagebox.showerror("Error", f"Request failed: {e}")


def congestion_off():
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return
    try:
        sock.sendall(b"CONGESTION_OFF\n")
    except OSError as e:
        messagebox.showerror("Error", f"Request failed: {e}")


def congestion_stats():
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return
    try:
        sock.sendall(b"CONGESTION_STATS\n")
    except OSError as e:
        messagebox.showerror("Error", f"Request failed: {e}")


def flood_chat():
    """Send many messages quickly to trigger congestion."""
    global sock, connected
    if not connected or sock is None:
        messagebox.showerror("Error", "Not connected to server.")
        return

    count = simpledialog.askinteger("Flood Chat", "How many messages to send?", minvalue=10, maxvalue=500)
    if not count:
        return

    try:
        for i in range(count):
            line = f"MSG|flood_msg_{i}\n"
            sock.sendall(line.encode(ENCODING))
        incoming.put(("INFO", f"Sent {count} flood messages"))
    except OSError as e:
        messagebox.showerror("Error", f"Flood failed: {e}")


def on_close(root):
    global sock, connected
    connected = False    
    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass
        sock = None
    root.destroy()


def build_gui():
    root = tk.Tk()
    root.title("Jasko Relay Chat")

    BG_MAIN = "#0f172a"     
    BG_PANEL = "#111827"
    BG_CHAT = "#020617"
    FG_TEXT = "#e5e7eb"
    ACCENT = "#2563eb"
    ACCENT2 = "#22c55e"

    root.configure(bg=BG_MAIN)

    status_var = tk.StringVar(value="Disconnected")
    room_label_var = tk.StringVar(value="Room: -")

    top = tk.Frame(root, bg=BG_MAIN)
    top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

    tk.Label(top, text="Server:", bg=BG_MAIN, fg=FG_TEXT).pack(side=tk.LEFT)
    server_entry = tk.Entry(top, width=15)
    server_entry.pack(side=tk.LEFT, padx=4)
    server_entry.insert(0, "127.0.0.1")  

    tk.Label(top, text="Username:", bg=BG_MAIN, fg=FG_TEXT).pack(side=tk.LEFT)
    username_entry = tk.Entry(top, width=12)
    username_entry.pack(side=tk.LEFT, padx=4)
    username_entry.insert(0, "student")

    tk.Label(top, text="Main Room:", bg=BG_MAIN, fg=FG_TEXT).pack(side=tk.LEFT, padx=(12, 0))
    room_entry = tk.Entry(top, width=12)
    room_entry.pack(side=tk.LEFT, padx=4)
    room_entry.insert(0, "classroom")

    connect_btn = tk.Button(
        top,
        text="Connect",
        bg=ACCENT,
        fg="white",
        activebackground="#1d4ed8",
        command=lambda: connect_server(server_entry, username_entry, room_entry, status_var),
    )
    connect_btn.pack(side=tk.LEFT, padx=6)

    room_label = tk.Label(
        top,
        textvariable=room_label_var,
        bg=BG_MAIN,
        fg=ACCENT2,
        font=("Helvetica", 10, "bold"),
    )
    room_label.pack(side=tk.RIGHT)

    main_frame = tk.Frame(root, bg=BG_MAIN)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

    chat_box = scrolledtext.ScrolledText(
        main_frame,
        state="disabled",
        width=70,
        height=20,
        bg=BG_CHAT,
        fg=FG_TEXT,
        insertbackground=FG_TEXT,
        relief=tk.FLAT,
        wrap=tk.WORD,
    )
    chat_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    chat_box.tag_config("self", foreground="#22c55e")     
    chat_box.tag_config("other", foreground="#60a5fa")    
    chat_box.tag_config("info", foreground="#9ca3af")
    chat_box.tag_config("history", foreground="#6b7280", font=("Helvetica", 9, "italic"))
    chat_box.tag_config("error", foreground="#f97373", font=("Helvetica", 10, "bold"))
    chat_box.tag_config("stats", foreground="#eab308")

    side_frame = tk.Frame(main_frame, bg=BG_PANEL)
    side_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))

    tk.Label(side_frame, text="Users in room:", bg=BG_PANEL, fg=FG_TEXT).pack(anchor="nw", pady=(4, 0))
    user_listbox = tk.Listbox(
        side_frame,
        height=12,
        width=20,
        bg="#020617",
        fg=FG_TEXT,
        highlightbackground=BG_PANEL,
    )
    user_listbox.pack(fill=tk.Y, expand=False, padx=4, pady=(0, 4))

    info_frame = tk.LabelFrame(side_frame, text="Room & Server", bg=BG_PANEL, fg=FG_TEXT)
    info_frame.pack(fill=tk.X, padx=4, pady=4)

    tk.Button(info_frame, text="Refresh Users", command=request_room_users, bg="#1f2937", fg=FG_TEXT).pack(
        fill=tk.X, pady=1
    )
    tk.Button(info_frame, text="Server Stats", command=request_stats, bg="#1f2937", fg=FG_TEXT).pack(
        fill=tk.X, pady=1
    )
    tk.Button(info_frame, text="Rooms List", command=request_room_list, bg="#1f2937", fg=FG_TEXT).pack(
        fill=tk.X, pady=1
    )

    tk.Button(info_frame, text="Cong ON", command=congestion_on, bg="#7f1d1d", fg=FG_TEXT).pack(
        fill=tk.X, pady=1
    )
    tk.Button(info_frame, text="Cong OFF", command=congestion_off, bg="#166534", fg=FG_TEXT).pack(
        fill=tk.X, pady=1
    )
    tk.Button(info_frame, text="Cong Stats", command=congestion_stats, bg="#1f2937", fg=FG_TEXT).pack(
        fill=tk.X, pady=1
    )
    tk.Button(info_frame, text="Flood Chat", command=flood_chat, bg="#92400e", fg=FG_TEXT).pack(
        fill=tk.X, pady=1
    )

    breakout_frame = tk.LabelFrame(side_frame, text="Breakouts", bg=BG_PANEL, fg=FG_TEXT)
    breakout_frame.pack(fill=tk.X, padx=4, pady=4)

    tk.Button(
        breakout_frame,
        text="Create Breakout",
        command=create_breakout_room,
        bg="#064e3b",
        fg=FG_TEXT,
    ).pack(fill=tk.X, pady=1)
    tk.Button(
        breakout_frame,
        text="Back to Main",
        command=back_to_main_room,
        bg="#4b5563",
        fg=FG_TEXT,
    ).pack(fill=tk.X, pady=1)

    bottom = tk.Frame(root, bg=BG_MAIN)
    bottom.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

    message_entry = tk.Entry(bottom, bg="#020617", fg=FG_TEXT, insertbackground=FG_TEXT)
    message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

    send_btn = tk.Button(bottom, text="Send", bg=ACCENT2, fg="black",
                         command=lambda: send_message(message_entry))
    send_btn.pack(side=tk.LEFT, padx=4)

    file_frame = tk.Frame(root, bg=BG_MAIN)
    file_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0, 6))

    tk.Button(file_frame, text="Upload File", command=upload_file, bg="#1f2937", fg=FG_TEXT).pack(
        side=tk.LEFT, padx=4
    )
    tk.Button(file_frame, text="List Files", command=list_files, bg="#1f2937", fg=FG_TEXT).pack(
        side=tk.LEFT, padx=4
    )
    tk.Button(file_frame, text="Download File", command=download_file, bg="#1f2937", fg=FG_TEXT).pack(
        side=tk.LEFT, padx=4
    )

    status_bar = tk.Label(
        root,
        textvariable=status_var,
        bd=1,
        relief=tk.SUNKEN,
        anchor="w",
        bg="#020617",
        fg="#9ca3af",
    )
    status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # Start polling queue
    poll_incoming(chat_box, user_listbox, status_var, room_label_var)

    root.protocol("WM_DELETE_WINDOW", lambda: on_close(root))
    return root


if __name__ == "__main__":
    app = build_gui()
    app.mainloop()
