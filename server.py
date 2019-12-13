#!/usr/bin/python3

import os
import cgi
import json
import shutil
import logging
import imutils
import argparse
import http.server
import collections

import log
import recdb
import config
import patterns
import recognizer


class FaceRecHandler(http.server.BaseHTTPRequestHandler):

    def __ok_response(self, result):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(bytearray(json.dumps(result), 'utf-8'))

    def __text_response(self, result):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(bytearray(result, 'utf-8'))

    def __bad_request_response(self, err):
        self.send_response(400)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(bytearray(err, 'utf-8'))

    def __not_found_response(self):
        self.send_error(404, 'File Not Found: %s' % self.path)

    def __server_error_response(self, err):
        self.send_error(500, 'Internal Server Error: %s' % err)

    def __file_request(self, path):
        try:
            if path[0] == '/':
                path = path[1:]

            if path.startswith('cache/'):
                fname = os.path.join(self.server.face_cache_path(), path[6:])
            else:
                fname = os.path.join(self.server.web_path(), path)

            ext = os.path.splitext(fname)[1]
            cont = ''
            if ext == '.html':
                cont = 'text/html'
            elif ext == '.js':
                cont = 'text/script'
            elif ext == '.css':
                cont = 'text/css'
            elif ext == '.png':
                cont = 'image/png'
            else:
                cont = 'text/none'
            with open(fname, 'rb') as f:
                self.send_response(200)
                self.send_header('Content-type', cont)
                self.end_headers()
                self.wfile.write(bytearray(f.read()))
        except IOError as ex:
            self.__not_found_response()
            logging.exception(ex)

    def __path_params(self):
        path_params = self.path.split('?')
        if len(path_params) > 1:
            return path_params[0], cgi.parse_qs(path_params[1])
        else:
            return path_params[0], {}

    def __list_cache(self, params):
        cache_path = self.server.face_cache_path()
        image_files = list(imutils.paths.list_images(cache_path))

        result = collections.defaultdict(lambda: [])
        for (i, image_file) in enumerate(image_files):
            name = image_file.split(os.path.sep)[-2]
            result[name].append(os.path.relpath(image_file, cache_path))

        self.__ok_response(result)

    def __get_names(self):
        self.__ok_response(sorted(list(set(self.server.patterns().names()))))

    def __add_to_pattern_request(self, params):
        cache_path = self.server.face_cache_path()
        filename = os.path.join(cache_path, params['file'][0])
        self.server.patterns().add_files(params['name'][0], filename, True)
        self.__ok_response('')

    def __add_images_request(self, params):
        self.server.recognize_folder(params['path'][0])
        self.__ok_response('')

    def __generate_faces_request(self, params):
        self.server.save_faces(params['path'][0])
        self.__ok_response('')

    def do_GET(self):
        logging.debug('do_GET: ' + self.path)
        try:
            path, params = self.__path_params()
            if path == '/list_cache':
                self.__list_cache(params)
                return

            if path == '/get_names':
                self.__get_names()
                return

            if path == '/':
                path = 'index.html'

            if '..' in path:
                logging.warning('".." in path: ' + path)
                self.__not_found_response()
                return

            ext = os.path.splitext(path)[1]
            if ext in ('.html', '.js', '.css', '.png', '.jpg'):
                self.__file_request(path)
                return

            logging.warning('Wrong path: ' + path)
            self.__not_found_response()
        except Exception as ex:
            self.__server_error_response(str(ex))
            logging.exception(ex)

    def do_POST(self):
        logging.debug('do_POST: ' + self.path)
        try:
            path, params = self.__path_params()

            if path == '/add_to_pattern':
                self.__add_to_pattern_request(params)
                return

            if path == '/add_images':
                self.__add_images_request(params)
                return

            if path == '/generate_faces':
                self.__generate_faces_request(params)
                return

        except Exception as ex:
            self.__server_error_response(str(ex))
            logging.exception(ex)


class FaceRecServer(http.server.HTTPServer):
    def __init__(self, cfg):
        self.__cfg = cfg
        self.__patterns = patterns.Patterns(cfg['main']['patterns'])
        self.__patterns.load()
        self.__recognizer = recognizer.Recognizer(
            self.__patterns,
            cfg['main']['model'],
            cfg['main']['num_jitters'],
            cfg['main']['threshold'])

        self.__db = recdb.RecDB(cfg['main']['db'])

        port = int(cfg['server']['port'])
        self.__web_path = cfg['server']['web_path']
        self.__face_cache_path = cfg['server']['face_cache_path']
        super().__init__(('', port), FaceRecHandler)

    def web_path(self):
        return self.__web_path

    def face_cache_path(self):
        return self.__face_cache_path

    def patterns(self):
        return self.__patterns

    def __clean_cache(self):
        if os.path.exists(self.__face_cache_path):
            shutil.rmtree(self.__face_cache_path)

    def recognize_folder(self, path):
        self.__clean_cache()
        self.__recognizer.recognize_folder(
            path, self.__db, self.__face_cache_path)

    def match_unmatched(self):
        self.__clean_cache()
        self.__recognizer.match_unmatched(
            self.__db, self.__face_cache_path)

    def match_all(self):
        self.__clean_cache()
        self.__recognizer.match_all(
            self.__db, self.__face_cache_path)

    def clusterize_unmatched(self):
        self.__clean_cache()
        self.__recognizer.clusterize_unmatched(
            self.__db, self.__face_cache_path)

    def save_faces(self, path):
        self.__clean_cache()
        self.__recognizer.save_faces(
            path, self.__db, self.__face_cache_path)


def args_parse():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', help='Config file')
    parser.add_argument('-l', '--logfile', help='Log file')
    return parser.parse_args()


def main():
    args = args_parse()

    cfg = config.Config(args.config)

    if args.logfile:
        logfile = args.logfile
    else:
        logfile = cfg['server']['log_file']

    log.initLogger(logfile)

    try:
        server = FaceRecServer(cfg)
        logging.info("Face rec server up.")
        server.serve_forever()
    except KeyboardInterrupt:
        server.socket.close()
        logging.info("Face rec server down.")


if __name__ == '__main__':
    main()