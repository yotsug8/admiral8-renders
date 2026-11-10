# Команды в консоль запущенной доты (запуск с -tools -netconport 29001): py -3.11 con.py "команда" ["команда" ...]
# py -3.11 con.py --get fps_max — напечатать ответ консоли (значение настройки).
import socket, sys, time
s = socket.create_connection(("127.0.0.1", 29001), timeout=5)
if sys.argv[1:2] == ["--get"]:
    s.sendall((sys.argv[2] + "\n").encode()); time.sleep(0.8); s.settimeout(0.5); buf = b""
    try:
        while True:
            c = s.recv(65536)
            if not c:
                break
            buf += c
    except OSError:
        pass
    name = sys.argv[2].split()[0]
    print("\n".join(l for l in buf.decode("utf-8", "replace").splitlines() if name in l and "Panorama" not in l))
else:
    for c in sys.argv[1:]:
        s.sendall((c + "\n").encode()); time.sleep(0.3)
s.close()
