# Команды в консоль запущенной доты (запуск с -tools -netconport 29001): py -3.11 con.py "команда" ["команда" ...]
import socket, sys, time
s = socket.create_connection(("127.0.0.1", 29001), timeout=5)
for c in sys.argv[1:]:
    s.sendall((c + "\n").encode()); time.sleep(0.3)
s.close()
