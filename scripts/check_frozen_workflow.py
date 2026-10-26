"""Packaged GUI import -> visible labels -> manual extraction -> review."""
import json,sys
from pathlib import Path
from studio.app import main
from studio.domain import read_json,Project,unique_id
from studio.review import ReviewStore
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication,QMainWindow
root=Path(__file__).resolve().parents[1];original=QApplication.exec_;report=root/'acceptance/frozen/workflow_gui.json'
def check():
 app=QApplication.instance();w=next(x for x in app.topLevelWidgets() if isinstance(x,QMainWindow));w.load_project(root/'acceptance/frozen'/('复审_'+unique_id()))
 evidence=read_json(root/'acceptance/workflow/integration.json');run=str(Path(evidence['tracking']['manifest']).parent)
 state={'stage':'import','frozen':getattr(sys,'frozen',False)}
 def fail(error):
  state.update(ok=False,error=str(error));report.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');app.quit()
 def done(ok):
  if not ok:fail('worker failed');return
  QTimer.singleShot(100,advance)
 def advance():
  try:
   if state['stage']=='import':
    assert w.nav.currentRow()==2 and len(w.canvas.boxes())==2
    state['labels_visible']=True;w.confirm_next();state['confirmed']=ReviewStore(w.project).status(w.images[0].name)=='confirmed'
    state['stage']='extract';w.tracking_window.load_video(root/'acceptance/sam/pair.mp4');w.tracking_window.method.setCurrentIndex(1);w.tracking_window.interval.setValue(.2);w.tracking_window.start()
   elif state['stage']=='extract':
    if w.task.busy or w.task.last_task['kind']=='extract':return
    assert w.nav.currentRow()==2 and len(w.images)==6 and not w.canvas.boxes()
    assert all(ReviewStore(w.project).status(p.name)=='pending' for p in w.images)
    state.update(ok=True,manual_pending=True);report.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');app.quit()
  except Exception as e:fail(e)
 w.task.finished.connect(done);QTimer.singleShot(0,lambda:w.import_video_run(run));QTimer.singleShot(90000,lambda:fail('timeout'))
 return original()
QApplication.exec_=staticmethod(check);main()
