import httpx
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        print("Headers:", self.headers)
        print("Data:", post_data[:100])
        self.send_response(200)
        self.end_headers()

def run_server():
    server_address = ('', 8080)
    httpd = HTTPServer(server_address, RequestHandler)
    httpd.handle_request()

threading.Thread(target=run_server).start()

import time
time.sleep(1)

with open("/Users/adisu/Documents/Gamio/assets/_bot/managed_bot_pic.png", "rb") as f:
    httpx.post("http://localhost:8080/test", files={"photo": ("managed_bot_pic.png", f, "image/png")})
