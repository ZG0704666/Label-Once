"""Render the actual application stylesheet and pages for visual QA."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.app import main
from PyQt5.QtWidgets import QApplication,QMainWindow
from PIL import Image

root=Path(__file__).resolve().parents[1]
def capture():
    app=QApplication.instance()
    window=next(w for w in app.topLevelWidgets() if isinstance(w,QMainWindow))
    window.load_project(root/'acceptance/验证项目')
    for index,name in [(0,'home'),(2,'annotation'),(3,'tracking'),(4,'training'),(5,'testing')]:
        if index==2:window.annotate_selected(window.files.item(0))
        window.nav.setCurrentRow(index);app.processEvents()
        if index==3:
            portrait=root/'acceptance/portrait_preview.png'
            Image.new('RGB',(360,640),'#536777').save(portrait)
            window.tracking_window.canvas.load(portrait,[],['物体']);app.processEvents()
        im=window.grab().toImage().convertToFormat(4);ptr=im.bits();ptr.setsize(im.byteCount())
        Image.frombuffer('RGBA',(im.width(),im.height()),bytes(ptr),'raw','BGRA',im.bytesPerLine(),1).save(root/f'acceptance/interface_{name}.png')
    window.close()
    return 0
QApplication.exec_=staticmethod(capture)
main()
