"""Exercise the real GUI and worker import loop and capture styled workspaces."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import config
from studio.app import main
from studio.domain import Box,unique_id
from studio.review import ReviewStore
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication,QMainWindow,QInputDialog
from PIL import Image
root=Path(__file__).resolve().parents[1];out=root/'acceptance/workspace_redesign'
config.CONFIG_ROOT=out/'qa_settings'
original=QApplication.exec_

def run():
 app=QApplication.instance();w=next(x for x in app.topLevelWidgets() if isinstance(x,QMainWindow))
 w.load_project(out/('流程验证_'+unique_id()));w.project.labels.set_classes(['人物'])
 w.resize(1280,720);app.processEvents()
 state={'stage':'extract','frozen':getattr(sys,'frozen',False)}
 def capture(name):
  app.processEvents();app.processEvents()
  im=w.grab().toImage().convertToFormat(4);ptr=im.bits();ptr.setsize(im.byteCount())
  Image.frombuffer('RGBA',(im.width(),im.height()),bytes(ptr),'raw','BGRA',im.bytesPerLine(),1).save(out/(name+'.png'))
 def finish(ok):
  if not ok:fail('worker failed');return
  QTimer.singleShot(150,advance)
 def fail(error):
  state.update(ok=False,error=str(error));(out/'gui_workflow.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');app.quit()
 def advance():
  try:
   if w.task.busy or w.task.last_task['kind']=='extract':return
   assert len(w.images)==6 and w.data_stack.currentIndex()==1
   assert all(ReviewStore(w.project).status(p.name)=='pending' for p in w.images)
   w.canvas.add_box(Box(0,.1,.1,.5,.8));w.annotation_changed();first=w.current_image
   w.confirm_next();assert ReviewStore(w.project).status(first.name)=='confirmed'
   assert w.current_image!=first and not w.canvas.boxes()
   w.navigate_image(-1);assert len(w.canvas.boxes())==1
   capture('annotation');w.route(1);capture('library')
   original_categories=QInputDialog.getMultiLineText;QInputDialog.getMultiLineText=lambda *a,**k:('人物\n新增类别',True)
   w.tracking_window.edit_classes();QInputDialog.getMultiLineText=original_categories
   assert w.tracking_window.canvas.names==['人物','新增类别']
   w.route(3);capture('video');w.tracking_window.method.setCurrentIndex(0);capture('sam2')
   w.route(4);capture('train');w.route(5);capture('model')
   state.update(ok=True,extracted=len(w.images),labels_visible=True,completed=True,project=str(w.project.root))
   (out/'gui_workflow.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
   app.quit()
  except Exception as e:fail(e)
 w.task.finished.connect(finish)
 w.route(3);w.tracking_window.load_video(root/'acceptance/sam/pair.mp4');w.tracking_window.method.setCurrentIndex(1);w.tracking_window.interval.setValue(.2)
 QTimer.singleShot(0,w.tracking_window.start);QTimer.singleShot(90000,lambda:fail('timeout'))
 return original()
QApplication.exec_=staticmethod(run)
main()
