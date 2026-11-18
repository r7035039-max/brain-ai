import sys,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import App
from main import make_server
from test_brain import FakeModel
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright
with tempfile.TemporaryDirectory() as tmp:
 model=ThreadingHTTPServer(('127.0.0.1',0),FakeModel);threading.Thread(target=model.serve_forever,daemon=True).start()
 app=App(tmp);app.dispatch('settings',{'endpoint':f'http://127.0.0.1:{model.server_port}/v1'})
 server=make_server(app);threading.Thread(target=server.serve_forever,daemon=True).start()
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox']);page=browser.new_page(viewport={'width':1280,'height':850});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f'http://127.0.0.1:{server.server_port}');page.wait_for_selector('.dot.online')
  page.screenshot(path='preview.png')
  page.locator('#prompt').fill('Привет');page.locator('#send').click();page.wait_for_function("document.querySelector('#status').textContent==='Готово'");page.wait_for_timeout(200)
  assert 'AST' in page.locator('#thread').inner_text()
  page.locator('#pinBtn').click();page.wait_for_timeout(100);assert page.locator('#pinBtn').inner_text()=='★'
  page.locator('#addProject').click();page.locator('#pname').fill('Моя игра');page.locator('#pinst').fill('Пиши на Python');page.locator('#saveModal').click();page.locator('#projects .item').click();page.wait_for_timeout(200)
  page.locator('#fileInput').set_input_files({'name':'rules.txt','mimeType':'text/plain','buffer':b'20 points to win'});page.wait_for_selector('#files button')
  page.locator('#mode').select_option('agents');page.on('dialog',lambda d:d.accept());page.locator('#prompt').fill('Сделай игру');page.locator('#send').click();page.wait_for_function("document.querySelector('#status').textContent==='Готово'");page.wait_for_timeout(500)
  assert page.locator('details').count()==1
  page.get_by_role('button',name='▶ Открыть').click();frame=page.frame_locator('iframe');frame.get_by_role('button',name='Старт').click();assert frame.get_by_role('button',name='42').count()==1
  page.locator('#cancelModal').click();page.locator('#settingsBtn').click();page.locator('#theme').select_option('light');page.locator('#saveModal').click();page.wait_for_timeout(200)
  page.screenshot(path='ui-chat.png');assert not errors,errors
  browser.close()
 server.shutdown();server.server_close();model.shutdown();model.server_close()
print('UI OK: send, pin, projects, file upload, four-stage agents, HTML click, theme; zero JS errors')
