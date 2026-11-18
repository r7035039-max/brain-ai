import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import App,pack
from main import make_server

class FakeModel(BaseHTTPRequestHandler):
    requests=[]
    def log_message(self,*a):pass
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b'{"data":[{"id":"test"}]}')
    def do_POST(self):
        d=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append(d)
        system=d['messages'][0]['content']
        if 'project manager' in system: text='План: создать один HTML-файл с кнопкой.'
        elif 'Review the supplied' in system: text='Код не запускался. Проверь управление.'
        elif 'software engineer' in system or 'final complete' in system: text='```html\n<h1>Игра</h1><button onclick="this.textContent=42">Старт</button>\n```'
        elif 'slow' in d['messages'][-1]['content']: text='Ответ '*50
        else: text='Привет, Рома!\n```python\nprint("hello")\n```'
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        try:
            for i in range(0,len(text),5):
                self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':text[i:i+5]}}]},ensure_ascii=False)+'\n\n').encode());self.wfile.flush();time.sleep(.005)
            self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        except (BrokenPipeError,ConnectionResetError):pass

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=ThreadingHTTPServer(('127.0.0.1',0),FakeModel);threading.Thread(target=cls.model.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.model.shutdown();cls.model.server_close()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=App(self.temp.name)
        self.app.dispatch('settings',{'endpoint':f'http://127.0.0.1:{self.model.server_port}/v1'})
        self.chat=self.app.dispatch('new',{})['id']
    def tearDown(self):self.temp.cleanup()
    def wait(self,j):
        for _ in range(500):
            state=self.app.dispatch('poll',j)
            if state['done']: return state
            time.sleep(.01)
        self.fail('Timeout')
    def test_chat_and_persistence(self):
        self.assertTrue(self.app.dispatch('health',{})['ok'])
        j=self.app.dispatch('send',{'id':self.chat,'content':'Привет'})
        result=self.wait(j);self.assertEqual(result['error'],'');self.assertIn('AST',result['text'])
        restored=App(self.temp.name).dispatch('chat',{'id':self.chat})
        self.assertEqual(len(restored['messages']),2)
    def test_roles_and_followup(self):
        result=self.wait(self.app.dispatch('send',{'id':self.chat,'content':'Сделай игру','agents':True}))
        self.assertEqual(result['error'],'');self.assertEqual(len(result['stages']),3)
        result=self.wait(self.app.dispatch('send',{'id':self.chat,'content':'Спасибо'}));self.assertEqual(result['error'],'')
        self.assertTrue(all(m['role'] in ('system','user','assistant') for m in FakeModel.requests[-1]['messages']))
    def test_project_context(self):
        p=self.app.dispatch('project',{'name':'Test','instructions':'Use red buttons'})['id']
        a=self.app.dispatch('new',{'project_id':p})['id'];b=self.app.dispatch('new',{'project_id':p})['id']
        self.app.dispatch('attach',{'id':a,'name':'note.txt','content':'Game rules: score 20'})
        self.assertEqual(len(self.app.dispatch('chat',{'id':b})['files']),1)
        result=self.wait(self.app.dispatch('send',{'id':b,'content':'Game rules?'}));self.assertEqual(result['error'],'')
        self.assertIn('score 20',FakeModel.requests[-1]['messages'][0]['content'])
    def test_stop_and_single_job(self):
        j=self.app.dispatch('send',{'id':self.chat,'content':'slow'})
        with self.assertRaises(ValueError):self.app.dispatch('send',{'id':self.chat,'content':'hi'})
        time.sleep(.05);self.app.dispatch('stop',j);result=self.wait(j)
        self.assertEqual(result['status'],'Остановлено')
    def test_context_and_endpoint(self):
        with self.assertRaises(ValueError):pack('system',[{'role':'user','content':'я'*10000}],4096,1400)
        with self.assertRaises(ValueError):self.app.dispatch('settings',{'endpoint':'https://example.com/v1'})
    def test_failure_is_visible(self):
        self.app.dispatch('settings',{'endpoint':'http://127.0.0.1:1/v1'})
        result=self.wait(self.app.dispatch('send',{'id':self.chat,'content':'hello'}));self.assertTrue(result['error'])
    def test_http_auth(self):
        import urllib.request,urllib.error
        server=make_server(self.app);threading.Thread(target=server.serve_forever,daemon=True).start()
        url=f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(url) as r:self.assertIn(b'TOKEN',r.read())
            with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(urllib.request.Request(url+'/api/state',data=b'{}'))
            self.assertEqual(err.exception.code,403)
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
