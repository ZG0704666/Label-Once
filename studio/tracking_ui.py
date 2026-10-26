"""Compact video workflow sharing the image annotation canvas."""
from pathlib import Path
from dataclasses import asdict
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QPushButton,QLabel,
    QComboBox,QSpinBox,QFileDialog,QListWidget,QListWidgetItem,QSplitter,QGroupBox,QScrollArea,QSizePolicy,QToolBar)
from .config import model_paths, CONFIG_ROOT
from .canvas import AnnotationCanvas, RectItem
from .domain import Box,read_json


def action(text,callback):
    b=QPushButton(text);b.clicked.connect(callback);return b


class TrackingWindow(QWidget):
    def __init__(self,parent):
        super().__init__(parent)
        self.parent=parent;self.run=None;self.video_path='';self.current_frame=-1
        self.state='idle';self.next_id=0;self.updating=False;self.preview_frame=-1
        self.session=None;self.pause_frame=None;self.pause_token=None;self.tracking_classes=[];self.frame_drafts={};self.total_frames=0
        v=QVBoxLayout(self);v.setContentsMargins(6,6,6,6);v.setSpacing(6)
        top=QHBoxLayout();v.addLayout(top)
        self.choose=action('选择视频',self.browse_video);top.addWidget(self.choose)
        self.video=QLabel('选择视频后自动显示首帧');self.video.setMinimumWidth(0);self.video.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);top.addWidget(self.video,1)
        self.method=QComboBox();self.method.addItems(['SAM2 自动追踪','直接抽帧']);self.method.setCurrentIndex(1);top.addWidget(self.method)
        self.settings_button=action('设置',self.toggle_settings);top.addWidget(self.settings_button)
        self.settings_panel=QWidget();settings_layout=QVBoxLayout(self.settings_panel);settings_layout.setContentsMargins(0,0,0,0)
        basic=QHBoxLayout();settings_layout.addLayout(basic)
        basic.addWidget(QLabel('模型'));self.model=QComboBox()
        for path in model_paths(True):self.model.addItem(Path(path).name,path)
        self.model.setMinimumContentsLength(10);self.model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon);basic.addWidget(self.model,1)
        basic.addWidget(action('选择权重',self.browse_model))
        advanced=QGroupBox('高级设置');advanced.setCheckable(True);advanced.setChecked(False);settings_layout.addWidget(advanced)
        av=QVBoxLayout(advanced);self.advanced_content=QWidget();form=QFormLayout(self.advanced_content);av.addWidget(self.advanced_content)
        self.imgsz=QSpinBox();self.imgsz.setRange(32,4096);self.imgsz.setSingleStep(32);self.imgsz.setValue(1024);form.addRow('输入尺寸',self.imgsz)
        self.device=QComboBox();self.device.setEditable(True);self.device.addItems(['0','cpu']);form.addRow('设备',self.device)
        form.addRow(action('恢复追踪任务',self.restore),action('导入已有视频结果',self.browse_import))
        self.advanced_content.hide();advanced.toggled.connect(self.advanced_content.setVisible)
        self.settings_scroll=QScrollArea(self);self.settings_scroll.setWindowFlags(Qt.Popup);self.settings_scroll.setWidgetResizable(True);self.settings_scroll.setWidget(self.settings_panel);self.settings_scroll.resize(440,260);self.settings_scroll.hide()
        self.annotation_toolbar=toolbar=QToolBar();v.addWidget(toolbar);toolbar.setMinimumWidth(0)
        self.cls=QComboBox();self.cls.setMinimumWidth(90);toolbar.addWidget(QLabel('类别'));toolbar.addWidget(self.cls);toolbar.addWidget(action('管理类别',self.edit_classes))
        self.cls.currentIndexChanged.connect(lambda i:setattr(self.canvas,'class_id',max(0,i)))
        toolbar.addWidget(action('画框 W',self.draw));toolbar.addWidget(action('选择 Esc',lambda:setattr(self.canvas,'mode','select')))
        toolbar.addWidget(action('删除 Del',self.delete));toolbar.addWidget(action('撤销',lambda:self.canvas.history_step(-1)));toolbar.addWidget(action('重做',lambda:self.canvas.history_step(1)))
        toolbar.addSeparator();toolbar.addWidget(action('适应 R',lambda:self.canvas.fit()))
        self.targets_button=action('目标列表',lambda:self.events.setVisible(not self.events.isVisible()));toolbar.addWidget(self.targets_button)
        split=QSplitter();v.addWidget(split,1)
        self.canvas=AnnotationCanvas();self.canvas.setMinimumSize(100,100);split.addWidget(self.canvas)
        self.events=QListWidget();self.events.setMinimumWidth(100);self.events.setMaximumWidth(220);split.addWidget(self.events)
        split.setStretchFactor(0,1);split.setSizes([900,190])
        self.canvas.navigate.connect(self.navigate_frame)
        self.canvas.changed.connect(self.sync_targets);self.canvas.scene().selectionChanged.connect(self.select_from_canvas)
        self.events.itemSelectionChanged.connect(self.select_from_list)
        self.canvas.mode_changed.connect(self.update_hint)
        self.hint=QLabel();self.hint.setWordWrap(True);self.hint.setMinimumWidth(0);v.addWidget(self.hint)
        bottom=QToolBar();bottom.setMinimumWidth(0);v.addWidget(bottom)
        self.previous_frame=action('上一帧 A',lambda:self.navigate_frame(-1));bottom.addWidget(self.previous_frame)
        self.next_frame_button=action('下一帧 D',lambda:self.navigate_frame(1));bottom.addWidget(self.next_frame_button)
        for control in (self.previous_frame,self.next_frame_button):control.setAutoRepeat(True);control.setAutoRepeatDelay(300);control.setAutoRepeatInterval(100)
        bottom.addWidget(QLabel('帧间隔'));self.interval=QComboBox();self.interval.addItems(['5','10','15','20','30']);self.interval.setCurrentText('10');bottom.addWidget(self.interval)
        self.start_button=action('开始追踪',self.primary);bottom.addWidget(self.start_button)
        self.finish_review_button=action('结束并复核',self.finish_review);bottom.addWidget(self.finish_review_button)
        self.stop_button=action('停止',self.stop);self.stop_action=bottom.addWidget(self.stop_button)
        self.import_button=action('导入项目并复审',self.open_annotations);self.import_action=bottom.addWidget(self.import_button)
        self.state_label=QLabel('就绪');self.state_label.setMinimumWidth(0);self.state_label.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);bottom.addWidget(self.state_label)
        self.method.currentIndexChanged.connect(self.update_controls)
        self.update_controls()

    def toggle_settings(self):
        if self.settings_scroll.isVisible():self.settings_scroll.hide();return
        screen=self.screen().availableGeometry();self.settings_scroll.resize(min(440,screen.width()-20),min(280,screen.height()-40))
        pos=self.settings_button.mapToGlobal(self.settings_button.rect().bottomRight());pos.setX(max(screen.left(),min(pos.x()-self.settings_scroll.width(),screen.right()-self.settings_scroll.width())))
        pos.setY(max(screen.top(),min(pos.y(),screen.bottom()-self.settings_scroll.height())))
        self.settings_scroll.move(pos);self.settings_scroll.show()

    @property
    def targets(self):
        return [dict(id=i,cls=b.cls,box=[b.x1,b.y1,b.x2,b.y2]) for i,b in self.canvas.target_boxes()]

    def update_hint(self,*args):
        mode='绘框中：十字光标，松开自动创建目标' if self.canvas.mode=='draw' else '选择：点击框可移动/缩放 · W 画框 · Del 删除 · Ctrl+Z 撤销'
        self.hint.setText('暂停编辑：删除目标将从当前帧起结束追踪；历史标签保留' if self.state=='paused' else mode)

    def update_controls(self,*args):
        busy=self.parent.task.busy
        for control in (self.previous_frame,self.next_frame_button):control.setEnabled(not busy and bool(self.video_path))
        self.annotation_toolbar.setVisible(self.method.currentIndex()==0)
        self.settings_button.setVisible(self.method.currentIndex()==0)
        self.hint.setVisible(self.method.currentIndex()==0)
        self.stop_button.setVisible(busy)
        self.import_button.setVisible(bool(self.run) and not busy)
        self.stop_action.setVisible(busy)
        self.import_action.setVisible(bool(self.run) and not busy)
        if self.method.currentIndex()==1:self.events.hide()
        self.start_button.setText({'tracking':'暂停','waiting':'等待确认…','paused':'继续','starting':'正在启动…'}.get(self.state,'开始抽帧' if self.method.currentIndex() else '开始追踪'))
        enabled=(self.state in ('tracking','paused') or (not busy and bool(self.video_path) and (self.method.currentIndex()==1 or bool(self.targets))))
        self.start_button.setEnabled(enabled and self.state not in ('waiting','starting'))
        self.stop_button.setEnabled(busy and self.run==str(self.parent.task.run))
        self.finish_review_button.setVisible(self.state=='paused')
        self.finish_review_button.setEnabled(self.state=='paused' and busy)
        self.stop_button.setVisible(busy)
        self.import_button.setEnabled(not busy and bool(self.run))
        for control in (self.choose,self.method,self.interval,self.model,self.imgsz,self.device):control.setEnabled(not busy)
        self.canvas.set_read_only(busy and self.state!='paused')
        self.state_label.setText({'idle':'就绪','tracking':'追踪中','paused':'已暂停，可编辑','waiting':'等待工作进程确认','starting':'加载模型中','completed':'结果可导入复审','failed':'任务失败，可重试或导入已有输出'}.get(self.state,self.state))
        self.update_hint()

    def sync_project(self,reset=False):
        previous=self.cls.currentText();self.cls.blockSignals(True);self.cls.clear()
        if self.parent.project:self.cls.addItems(self.tracking_classes if not reset and self.state in ('starting','tracking','waiting','paused') else self.parent.project.labels.classes)
        if previous:self.cls.setCurrentText(previous)
        self.cls.blockSignals(False);self.canvas.class_id=max(0,self.cls.currentIndex())
        if reset:
            self.run=None;self.video_path='';self.state='idle';self.next_id=0;self.session=None
            self.canvas.scene().clear();self.canvas.image_path=None;self.canvas.history=[];self.canvas.history_index=-1
            self.events.clear();self.video.setText('选择视频后自动显示首帧')
        self.update_controls()

    def browse_model(self):
        path,_=QFileDialog.getOpenFileName(self,'选择 SAM2 权重','','Weights (*.pt)')
        if path:self.model.addItem(Path(path).name,path);self.model.setCurrentIndex(self.model.count()-1)

    def browse_video(self):
        self.parent.guard()
        path,_=QFileDialog.getOpenFileName(self,'视频','','Videos (*.mp4 *.avi *.mov *.mkv)')
        if path:self.load_video(path)

    def load_video(self,path):
        import cv2
        self.parent.guard();cap=cv2.VideoCapture(str(path));self.total_frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));ok,frame=cap.read();cap.release();self.frame_drafts={}
        if not ok:raise ValueError('无法打开视频')
        self.video_path=str(path);self.video.setText(Path(path).name);self.video.setToolTip(str(path))
        self.run=None;self.state='idle';self.next_id=0;self.current_frame=0;self.preview_frame=0
        CONFIG_ROOT.mkdir(parents=True,exist_ok=True);preview=CONFIG_ROOT/'video_prompt.jpg'
        cv2.imencode('.jpg',frame)[1].tofile(preview)
        self.canvas.auto_fit=True;self.canvas.load(preview,[],self.parent.project.labels.classes);self.sync_targets();self.update_controls()

    def draw(self):
        if self.canvas.read_only:return
        if not self.canvas.image_path:raise ValueError('请先选择视频')
        if not self.cls.count():raise ValueError('请点击管理类别，添加本项目的类别')
        self.canvas.mode='draw';self.canvas.setFocus()

    def edit_classes(self):
        self.parent.label_store=self.parent.project.labels
        self.parent.edit_classes();self.sync_project()
        self.canvas.names=self.parent.project.labels.classes

    def delete(self):self.canvas.delete_selected()

    def sync_targets(self):
        if self.updating:return
        self.updating=True
        selected={i.target_id for i in self.canvas.scene().selectedItems() if isinstance(i,RectItem)}
        self.events.clear()
        for target_id,box in self.canvas.target_boxes():
            name=self.cls.itemText(box.cls) or f'class_{box.cls}'
            item=QListWidgetItem(f'目标 {target_id} · {name}');item.setData(Qt.UserRole,target_id);self.events.addItem(item);item.setSelected(target_id in selected)
        self.next_id=max(self.next_id,self.canvas.next_target_id);self.canvas.next_target_id=self.next_id
        self.updating=False;self.update_controls()

    def select_from_canvas(self):
        if self.updating:return
        self.updating=True
        ids={i.target_id for i in self.canvas.scene().selectedItems() if isinstance(i,RectItem)}
        for n in range(self.events.count()):self.events.item(n).setSelected(self.events.item(n).data(Qt.UserRole) in ids)
        self.updating=False

    def select_from_list(self):
        if self.updating:return
        self.updating=True;ids={i.data(Qt.UserRole) for i in self.events.selectedItems()}
        for item in self.canvas.scene().items():
            if isinstance(item,RectItem):item.setSelected(item.target_id in ids)
        self.updating=False

    def navigate_frame(self,step):
        if not self.video_path or self.parent.task.busy:return
        import cv2
        index=max(0,min(self.total_frames-1,self.current_frame+step))
        if index==self.current_frame:return
        cap=cv2.VideoCapture(self.video_path);cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,frame=cap.read();cap.release()
        if not ok:raise ValueError(f'无法读取视频第 {index+1} 帧')
        self.frame_drafts[self.current_frame]=self.canvas.target_boxes()
        preview=CONFIG_ROOT/'video_prompt.jpg';cv2.imencode('.jpg',frame)[1].tofile(preview)
        pairs=self.frame_drafts.get(index,[]);self.current_frame=self.preview_frame=index
        self.updating=True
        self.canvas.load(preview,[b for _,b in pairs],self.parent.project.labels.classes,[i for i,_ in pairs]);self.updating=False
        self.sync_targets();self.state_label.setText(f'第 {index+1}/{self.total_frames} 帧 · A/D 长按连续切换')

    def primary(self):
        if self.state=='tracking':
            self.state='waiting';self.parent.task.control(dict(action='pause'));self.update_controls();return
        if self.state=='paused':
            if self.next_id>32:raise ValueError('最多 32 个终身目标 ID，请新建任务')
            self.parent.task.control(dict(action='commit',pause_token=self.pause_token,frame=self.current_frame,targets=self.targets,next_id=self.next_id))
            self.state='waiting';self.update_controls();return
        self.start()

    def finish_review(self):
        if self.state!='paused' or not self.parent.task.busy:return
        if self.next_id>32:raise ValueError('最多 32 个终身目标 ID，请新建任务')
        self.parent.task.control(dict(action='finish_review',pause_token=self.pause_token,frame=self.current_frame,targets=self.targets,next_id=self.next_id))
        self.state='waiting';self.update_controls()

    def start(self):
        import uuid
        self.parent.guard()
        if not Path(self.video_path).is_file():raise ValueError('请选择视频')
        kind='extract' if self.method.currentIndex() else 'tracking'
        kwargs=dict(video=self.video_path,frame_step=int(self.interval.currentText()))
        if kind=='tracking':
            if not self.targets:raise ValueError('请先画出目标框')
            if self.next_id>32:raise ValueError('最多 32 个目标，请重新选择视频')
            if self.imgsz.value()%32:raise ValueError('输入尺寸须为 32 的倍数')
            self.tracking_classes=self.parent.project.labels.classes
            kwargs.update(start_frame=max(0,self.current_frame),model=self.model.currentData(),imgsz=self.imgsz.value(),device=self.device.currentText(),classes=self.parent.project.labels.classes,targets=self.targets,next_id=self.next_id)
        self.session=uuid.uuid4().hex;self.run=str(self.parent.project.new_run(kind));self.current_frame=-1;self.preview_frame=-1;self.pause_frame=None
        self.parent.start_task(kind,run=self.run,session=self.session,**kwargs)
        self.state='starting';self.update_controls()

    def restore(self):
        import uuid
        self.parent.guard();path=QFileDialog.getExistingDirectory(self,'选择追踪任务目录')
        if not path:return
        task=read_json(Path(path)/'task.json',{})
        if task.get('kind')!='tracking':raise ValueError('该目录不是追踪任务')
        task.pop('kind');task.pop('project',None);task['run']=path;task['session']=uuid.uuid4().hex
        self.run=path;self.session=task['session'];self.video_path=task['video'];self.video.setText(Path(self.video_path).name)
        self.tracking_classes=task['classes'];self.cls.clear();self.cls.addItems(self.tracking_classes)
        self.current_frame=self.preview_frame=-1;self.pause_frame=None;self.next_id=read_json(Path(path)/'frame_manifest.json',{}).get('next_id',0)
        self.parent.start_task('tracking',**task);self.state='starting';self.update_controls()

    def browse_import(self):
        self.parent.guard();path=QFileDialog.getExistingDirectory(self,'选择追踪或抽帧任务目录')
        if path:self.parent.import_video_run(path)

    def open_annotations(self):
        if self.run:self.parent.import_video_run(self.run)

    def stop(self):
        self.parent.task.cancel();self.state='waiting';self.update_controls()

    def finished(self,ok):
        self.state='completed' if ok else 'failed'
        self.update_controls()

    def on_event(self,event):
        if event.get('session')!=self.session or event.get('run')!=self.run:return
        frame=event.get('frame',-1)
        if frame<self.current_frame:return
        if event['event']=='tracking_frame':
            if self.state=='paused' and frame<=self.preview_frame:return
            boxes=event.get('boxes',{})
            self.updating=True
            self.canvas.load(event['path'],[Box(**b) for b in boxes.values()],self.tracking_classes or self.parent.project.labels.classes,[int(i) for i in boxes])
            self.updating=False;self.preview_frame=frame;self.current_frame=frame
            self.next_id=max(self.next_id,event.get('next_id',0));self.sync_targets()
        elif event['event']=='tracking_state':
            self.current_frame=frame;self.next_id=max(self.next_id,event.get('next_id',0))
            state=event['state']
            if state=='paused' and (self.preview_frame!=frame or not event.get('pause_token')):
                self.state='waiting';self.update_controls();return
            if state=='paused':self.pause_token=event['pause_token']
            elif state=='tracking':self.pause_token=None
            self.state=state
            if state=='paused':
                # The pause snapshot includes missing targets, so they can be corrected.
                boxes=event.get('targets',{})
                self.updating=True
                for item in list(self.canvas.scene().items()):
                    if isinstance(item,RectItem):self.canvas.scene().removeItem(item)
                for i,t in boxes.items():self.canvas.add_box(Box(t['cls'],*t['box'],'AI'),int(i))
                self.canvas.history=[];self.canvas.history_index=-1;self.canvas.record_history()
                self.updating=False;self.sync_targets()
                failures=event.get('failures',{})
                for n in range(self.events.count()):
                    item=self.events.item(n);reason=failures.get(str(item.data(Qt.UserRole)),failures.get(item.data(Qt.UserRole)))
                    if reason:item.setText(item.text()+' ⚠ '+reason);item.setSelected(True)
            self.update_controls()
