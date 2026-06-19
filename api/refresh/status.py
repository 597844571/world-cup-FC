from http.server import BaseHTTPRequestHandler

from app.vercel_state import refresh_status_response, write_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        write_json(self, refresh_status_response())

    def do_POST(self):
        write_json(self, refresh_status_response())
