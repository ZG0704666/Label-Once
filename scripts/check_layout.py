"""Capture and assert video workflow at physical screen/scale combinations."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.app import main
from PyQt5.QtWidgets import QApplication,QMainWindow
from PyQt5.QtCore import QPoint
from PIL import Image
root=Path(__file__).resolve().parents[1]
w,h,scale=int(sys.argv[1]),int(sys.argv[2]),float(sys.argv[3])
from studio import config
config.CONFIG_ROOT=root/'acceptance/workflow'/f'settings_{w}_{h}_{scale}'
def check():
 app=QApplication.instance();window=next(w for w in app.topLevelWidgets() if isinstance(w,QMainWindow))
 window.load_project(root/'acceptance/验证项目');window.nav.setCurrentRow(3)
 window.resize(int(w/scale),int(h/scale)-28);app.processEvents();app.processEvents()
 t=window.tracking_window;t.canvas.auto_fit=True;t.canvas.load(root/'acceptance/portrait_preview.png',[],['person']);app.processEvents();app.processEvents()
 assert window.width()<=int(w/scale),(window.width(),w/scale)
 assert window.height()<=int(h/scale)-28,(window.height(),h/scale)
 shown=t.canvas.transform().mapRect(t.canvas.sceneRect())
 assert shown.height()<=t.canvas.viewport().height() and shown.width()<=t.canvas.viewport().width()
 for button in (t.choose,t.start_button,t.stop_button,t.import_button):
  position=button.mapTo(window,QPoint(0,0));assert button.isVisible() and position.x()+button.width()<=window.width(),button.text()
 out=root/'acceptance/workflow';out.mkdir(exist_ok=True)
 for path in (root/'acceptance/portrait_preview.png',root/'acceptance/验证项目/Main/测试_00.jpg'):
  t.canvas.auto_fit=True;t.canvas.load(path,[],['person']);app.processEvents()
  shown=t.canvas.transform().mapRect(t.canvas.sceneRect())
  assert shown.height()<=t.canvas.viewport().height() and shown.width()<=t.canvas.viewport().width()
 t.settings_scroll.show();app.processEvents()
 assert window.height()<=int(h/scale)-28
 t.settings_scroll.hide();app.processEvents()
 im=window.grab().toImage().convertToFormat(4);ptr=im.bits();ptr.setsize(im.byteCount())
 Image.frombuffer('RGBA',(im.width(),im.height()),bytes(ptr),'raw','BGRA',im.bytesPerLine(),1).save(out/f'layout_{w}_{h}_{scale}.png')
 print(json.dumps(dict(screen=[w,h],scale=scale,window=[window.width(),window.height()],canvas=[t.canvas.width(),t.canvas.height()])))
 window.close();return 0
QApplication.exec_=staticmethod(check)
main()
