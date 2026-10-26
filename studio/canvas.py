from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView
from .domain import Box


class RectItem(QGraphicsRectItem):
    def __init__(self, box, width, height, canvas):
        super().__init__(QRectF(box.x1*width,box.y1*height,(box.x2-box.x1)*width,(box.y2-box.y1)*height))
        self.box, self.canvas = box, canvas
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.handle = None
        self.update_pen()

    def hoverMoveEvent(self,event):
        if self.canvas.read_only:
            self.setCursor(Qt.ArrowCursor);return
        tolerance=8/max(self.canvas.transform().m11(),.01)
        cursors=[Qt.SizeFDiagCursor,Qt.SizeVerCursor,Qt.SizeBDiagCursor,Qt.SizeHorCursor,
                 Qt.SizeFDiagCursor,Qt.SizeVerCursor,Qt.SizeBDiagCursor,Qt.SizeHorCursor]
        cursor=Qt.SizeAllCursor
        if self.isSelected():
            for i,p in enumerate(self.points()):
                if (p-event.pos()).manhattanLength()<tolerance:cursor=cursors[i];break
        self.setCursor(Qt.CrossCursor if self.canvas.mode=='draw' else cursor)
        super().hoverMoveEvent(event)

    def update_pen(self):
        pen = QPen(QColor('#f59e0b' if self.box.origin=='AI' else '#22d3ee'),2)
        pen.setCosmetic(True)
        pen.setStyle(Qt.DashLine if self.box.origin=='AI' else Qt.SolidLine)
        self.setPen(pen)

    def points(self):
        r=self.rect()
        return [r.topLeft(),QPointF(r.center().x(),r.top()),r.topRight(),QPointF(r.right(),r.center().y()),r.bottomRight(),QPointF(r.center().x(),r.bottom()),r.bottomLeft(),QPointF(r.left(),r.center().y())]

    def paint(self,painter,option,widget=None):
        if self.box.polygons:
            painter.save();painter.setPen(self.pen());painter.setBrush(QColor(245,158,11,48))
            r=self.rect();b=self.box
            for polygon in b.polygons:
                painter.drawPolygon(QPolygonF([QPointF(r.left()+(x-b.x1)/max(b.x2-b.x1,1e-9)*r.width(),r.top()+(y-b.y1)/max(b.y2-b.y1,1e-9)*r.height()) for x,y in polygon]))
            painter.restore()
        if not self.box.polygons or self.isSelected():super().paint(painter,option,widget)
        painter.setPen(self.pen())
        name=self.canvas.names[self.box.cls] if self.box.cls<len(self.canvas.names) else f'class_{self.box.cls}'
        painter.drawText(self.rect().topLeft()+QPointF(3,-4),name)
        if self.isSelected():
            size=4/max(self.canvas.transform().m11(),.01)
            painter.setBrush(QColor('#ffffff'))
            for p in self.points():
                painter.drawRect(QRectF(p.x()-size,p.y()-size,size*2,size*2))

    def current_box(self):
        r=self.mapRectToScene(self.rect());b=self.box
        x1,y1,x2,y2=r.left()/self.canvas.width_px,r.top()/self.canvas.height_px,r.right()/self.canvas.width_px,r.bottom()/self.canvas.height_px
        polygons=[[[max(0,min(1,x1+(x-b.x1)/max(b.x2-b.x1,1e-9)*(x2-x1))),max(0,min(1,y1+(y-b.y1)/max(b.y2-b.y1,1e-9)*(y2-y1)))] for x,y in polygon] for polygon in b.polygons] if b.polygons else None
        return Box(b.cls,x1,y1,x2,y2,b.origin,b.score,polygons).clipped()

    def mousePressEvent(self,event):
        tolerance=10/max(self.canvas.transform().m11(),.01)
        self.handle=None
        if self.isSelected():
            for i,p in enumerate(self.points()):
                if (p-event.pos()).manhattanLength()<tolerance:
                    self.handle=i
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.handle is not None:
            r=self.rect()
            p=event.pos()
            if self.handle in (0,6,7):r.setLeft(p.x())
            if self.handle in (2,3,4):r.setRight(p.x())
            if self.handle in (0,1,2):r.setTop(p.y())
            if self.handle in (4,5,6):r.setBottom(p.y())
            self.setRect(r.normalized())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        self.handle=None
        self.box.origin='人工'
        self.update_pen()
        self.canvas.changed.emit()


class AnnotationCanvas(QGraphicsView):
    changed=pyqtSignal()
    mode_changed=pyqtSignal(str)
    prompt=pyqtSignal(dict)
    navigate=pyqtSignal(int)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor('#111827'))
        self.width_px=self.height_px=1
        self.names=[]
        self.class_id=0
        self._mode='select'
        self.read_only=False
        self.next_target_id=0
        self.history=[];self.history_index=-1;self.restoring=False
        self.changed.connect(self.record_history)
        self.drawing=None
        self.clipboard=None
        self.panning=False
        self.space=False
        self.image_path=None
        self.auto_fit=True
        self.setFocusPolicy(Qt.StrongFocus)
        self.navigation_key=None
        self.navigation_timer=QTimer(self);self.navigation_timer.timeout.connect(self.repeat_navigation)
        self.setToolTip('A / D：上一张（帧）/ 下一张（帧），长按连续切换；R：适应画布')

    @property
    def mode(self):return self._mode

    @mode.setter
    def mode(self,value):
        self._mode=value
        self.setCursor(Qt.CrossCursor if value in ('draw','sam_point','sam_box') else Qt.ArrowCursor)
        self.mode_changed.emit(value)

    def set_read_only(self,value):
        self.read_only=value
        if value:self.stop_navigation();self.mode='select'

    def target_boxes(self):
        result=[]
        for item in reversed(self.scene().items()):
            if isinstance(item,RectItem):
                r=item.mapRectToScene(item.rect())
                b=item.current_box()
                result.append((item.target_id,b))
        return result

    def record_history(self):
        if self.restoring:return
        snapshot=self.target_boxes()
        if self.history_index>=0 and snapshot==self.history[self.history_index]:return
        self.history=self.history[:self.history_index+1]+[snapshot]
        self.history=self.history[-100:];self.history_index=len(self.history)-1

    def history_step(self,delta):
        index=self.history_index+delta
        if self.read_only or not 0<=index<len(self.history):return
        self.restoring=True
        for item in list(self.scene().items()):
            if isinstance(item,RectItem):self.scene().removeItem(item)
        for target_id,b in self.history[index]:self.add_box(b,target_id)
        self.history_index=index;self.changed.emit();self.restoring=False

    def delete_selected(self):
        if self.read_only:return
        for item in list(self.scene().selectedItems()):
            if isinstance(item,RectItem):self.scene().removeItem(item)
        self.changed.emit()

    def load(self,path,boxes,names,target_ids=None):
        pix=QPixmap(str(path))
        if pix.isNull():
            raise ValueError(f'无法读取图片：{path}')
        self.scene().clear();self.drawing=None
        self.image_path=str(path)
        self.width_px,self.height_px=pix.width(),pix.height()
        self.names=names
        self.scene().addPixmap(pix).setZValue(-10)
        self.setSceneRect(QRectF(0,0,pix.width(),pix.height()))
        self.next_target_id=0
        for i,box in enumerate(boxes):self.add_box(box,target_ids[i] if target_ids is not None else None)
        self.history=[];self.history_index=-1;self.record_history()
        if self.auto_fit:self.fit()

    def fit(self):
        self.auto_fit=True
        if not self.image_path:return
        self.resetTransform()
        self.fitInView(self.sceneRect(),Qt.KeepAspectRatio)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.auto_fit:QTimer.singleShot(0,self._fit_if_enabled)

    def showEvent(self,event):
        super().showEvent(event)
        if self.auto_fit:QTimer.singleShot(0,self._fit_if_enabled)

    def _fit_if_enabled(self):
        if self.auto_fit:self.fit()

    def add_box(self,box,target_id=None):
        item=RectItem(box.clipped(),self.width_px,self.height_px,self)
        item.target_id=self.next_target_id if target_id is None else target_id
        self.next_target_id=max(self.next_target_id,item.target_id+1)
        self.scene().addItem(item)

    def boxes(self):
        result=[]
        for item in reversed(self.scene().items()):
            if isinstance(item,RectItem):
                r=item.mapRectToScene(item.rect())
                result.append(item.current_box())
        return result

    def wheelEvent(self,event):
        self.auto_fit=False
        factor=1.2 if event.angleDelta().y()>0 else 1/1.2
        scale=self.transform().m11()*factor
        if .01<scale<50:self.scale(factor,factor)

    def mousePressEvent(self,event):
        if event.button()==Qt.MiddleButton or (event.button()==Qt.LeftButton and self.space):
            self.panning=True
            self.pan_start=event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if self.read_only:event.accept();return
        p=self.mapToScene(event.pos())
        if event.button()==Qt.LeftButton and self.mode=='sam_point':
            self.prompt.emit({'point':[p.x(),p.y()]})
            return
        if event.button()==Qt.LeftButton and self.mode in ('draw','sam_box'):
            self.origin=p
            self.drawing=QGraphicsRectItem(QRectF(p,p))
            self.drawing.setPen(QPen(QColor('#a78bfa'),2))
            self.scene().addItem(self.drawing)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.panning:
            delta=event.pos()-self.pan_start
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-delta.y())
            self.pan_start=event.pos()
            return
        if self.read_only:return
        if self.drawing:
            self.drawing.setRect(QRectF(self.origin,self.mapToScene(event.pos())).normalized())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if self.panning:
            self.panning=False
            self.mode=self.mode
            return
        if self.drawing:
            rect=QRectF(self.origin,self.mapToScene(event.pos())).normalized().intersected(self.sceneRect())
            self.scene().removeItem(self.drawing)
            self.drawing=None
            if rect.width()>1 and rect.height()>1:
                if self.mode=='sam_box':
                    self.prompt.emit({'bbox':[rect.left(),rect.top(),rect.right(),rect.bottom()]})
                else:
                    self.add_box(Box(self.class_id,rect.left()/self.width_px,rect.top()/self.height_px,rect.right()/self.width_px,rect.bottom()/self.height_px))
                    self.changed.emit()
                    self.mode='select'
            return
        if self.read_only:return
        super().mouseReleaseEvent(event)

    def repeat_navigation(self):
        if self.navigation_key is not None and self.hasFocus() and not self.read_only:
            self.navigation_timer.setInterval(100)
            self.navigate.emit(-1 if self.navigation_key==Qt.Key_A else 1)
        else:self.stop_navigation()

    def stop_navigation(self):
        self.navigation_timer.stop();self.navigation_key=None

    def focusOutEvent(self,event):
        self.stop_navigation();super().focusOutEvent(event)

    def hideEvent(self,event):
        self.stop_navigation();super().hideEvent(event)

    def keyPressEvent(self,event):
        key=event.key()
        if key==Qt.Key_Space:self.space=True;return
        if key==Qt.Key_Escape:
            if self.drawing:self.scene().removeItem(self.drawing);self.drawing=None
            self.mode='select';return
        if key==Qt.Key_R:self.fit();return
        if self.read_only:return
        if event.modifiers()&Qt.ControlModifier:
            if key==Qt.Key_Z:self.history_step(1 if event.modifiers()&Qt.ShiftModifier else -1);return
            if key==Qt.Key_Y:self.history_step(1);return
        if key in (Qt.Key_A,Qt.Key_D) and event.modifiers()==Qt.NoModifier:
            if not event.isAutoRepeat():
                self.navigation_key=key;self.navigate.emit(-1 if key==Qt.Key_A else 1);self.navigation_timer.start(300)
            event.accept();return
        if key==Qt.Key_W:self.mode='draw';return
        if key==Qt.Key_R:self.fit();return
        selected=[i for i in self.scene().selectedItems() if isinstance(i,RectItem)]
        if key==Qt.Key_Delete:
            self.delete_selected();return
        if key==Qt.Key_C and event.modifiers()&Qt.ControlModifier and selected:
            item=selected[0];r=item.mapRectToScene(item.rect())
            self.clipboard=item.current_box()
            return
        if key==Qt.Key_V and event.modifiers()&Qt.ControlModifier and self.clipboard:
            b=self.clipboard;dx,dy=20/self.width_px,20/self.height_px
            self.add_box(Box(b.cls,b.x1+dx,b.y1+dy,b.x2+dx,b.y2+dy,polygons=[[[x+dx,y+dy] for x,y in polygon] for polygon in b.polygons] if b.polygons else None));self.changed.emit();return
        if key in (Qt.Key_Left,Qt.Key_Right,Qt.Key_Up,Qt.Key_Down):
            dx={Qt.Key_Left:-1,Qt.Key_Right:1}.get(key,0);dy={Qt.Key_Up:-1,Qt.Key_Down:1}.get(key,0)
            for item in selected:item.moveBy(dx,dy);item.box.origin='人工';item.update_pen()
            self.changed.emit();return
        super().keyPressEvent(event)

    def keyReleaseEvent(self,event):
        if event.key()==self.navigation_key and not event.isAutoRepeat():self.stop_navigation();event.accept();return
        if event.key()==Qt.Key_Space:self.space=False
        super().keyReleaseEvent(event)
