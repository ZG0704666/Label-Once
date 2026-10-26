import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.app import main
from studio import config
from PyQt5.QtWidgets import QApplication,QMainWindow
from PIL import Image
root=Path(__file__).resolve().parents[1];out=root/'acceptance/workspace_redesign'
config.CONFIG_ROOT=out/'layout_settings'
width,height,scale=int(sys.argv[1]),int(sys.argv[2]),float(sys.argv[3])
def check():
 app=QApplication.instance();w=next(x for x in app.topLevelWidgets() if isinstance(x,QMainWindow))
 w.load_project(out/'演示项目');w.resize(int(width/scale),int(height/scale)-28)
 w.tracking_window.load_video(root/'acceptance/sam/pair.mp4')
 observations=[]
 for index in (1,2,3,4,5):
  w.route(index);app.processEvents();app.processEvents()
  observations.append(dict(page=index,size=[w.width(),w.height()]))
  assert w.width()<=int(width/scale),(index,w.width(),width/scale)
  assert w.height()<=int(height/scale)-28,(index,w.height(),height/scale)
  if index==3:
   t=w.tracking_window;shown=t.canvas.transform().mapRect(t.canvas.sceneRect())
   assert shown.width()<=t.canvas.viewport().width() and shown.height()<=t.canvas.viewport().height()
   im=w.grab().toImage().convertToFormat(4);ptr=im.bits();ptr.setsize(im.byteCount())
   Image.frombuffer('RGBA',(im.width(),im.height()),bytes(ptr),'raw','BGRA',im.bytesPerLine(),1).save(out/f'layout_{width}_{height}_{scale}.png')
 (out/f'layout_{width}_{height}_{scale}.json').write_text(json.dumps(observations),encoding='utf-8')
 w.close();return 0
QApplication.exec_=staticmethod(check);main()
