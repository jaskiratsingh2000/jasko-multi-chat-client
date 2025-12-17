# jasko-multi-chat-client

This application implements a TCP based multi client chatroom that is designed to study congestion behaviour. The system supports real time emssaging, file uploads, breakout rooms, congestion simulator and message flooding mechanism. The server was deployed on microsoft azure and multiple GUI based clients can connect remotely.


1) System Requirements: 

   Client Machine

   -Python 3.8 or higher

   -Network access to VM

   Server Machine

   -TCP port 5000


2) Instructions to execute the server:

   Step 1: Obtain the server IP and log into the server VM
   -ssh username@public_ip


   Step 2: Clone the repository and start the server ith an unbuffered output, it is essential to      confirm whether the server is listening.

   -git clone https://github.com/username/jasko-multi-client-chat.git

   -cd jasko-multi-client-chat

   -nohup python3 -u server.py > server.out 2>&1 &

   -sudo ss -lntp | grep 5000

   (listening socket on 0.0.0.0:5000)


  Step 3: Background Execution: nohup python3 -u server.py > server.out 2>&1 &

   Run the client: python client_gui.py

   Azure public IP: 4.186.28.124


3) Features:
   
    -TCP socket based communication

    -Multi client support threads

    -Breakout rooms for isolated discussions

    -File upload and download

    -Congestion simulation

   -Message flooding for load testing

   -Azure cloud deployment


4) Reproducing Experimental Results:

    Experiment 1: Function of Load under Congestion

    -Connect a single client

    -Enable congestion mode using the Cong ON button

    -Use Flood Chat to send 10, 25, 50, and 100 messages

    -Measure total delivery time from flood initiation to receipt of the final message

    -Compute average latency per message


  Experiment 2: Throughput with and without Congestion

   -Connect one client

   -Flood 100 messages with congestion OFF

   -Record total delivery time

   -Enable congestion

   -Flood 100 messages again


5) Architecture:

    Server- Python TCP server handling

    Client: Python GUI client

    Congestion control: Centralized queue with transmission interval


6) Technologies Used:

    Python 

    TCP sockets

    Threading

    Tkinter

    Azure VM


7) Congestion Simulation:

    Cong ON: Enables delayed message transmission

    Cong OFF: Normal high throughput mode

    Flood Chat: Sends burst messages to simulate load

