from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QIcon, QPixmap
from PyQt5.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
    QPushButton,QLabel,QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox,QStackedWidget,
    QGridLayout,QListWidget,QSplitter,QPlainTextEdit,QFileDialog,QMessageBox,QInputDialog,QProgressBar,
    QTableWidget,QTableWidgetItem,QDialog,QDialogButtonBox,QAbstractItemView,QGroupBox,QScrollArea,QSizePolicy,QShortcut)

from .canvas import AnnotationCanvas
from .config import ADVANCED,AUGMENTS,APP_ROOT,bundled_logo,model_paths,save_settings,settings
from .dataset import DatasetStore
from .domain import Box,IMAGE_EXTENSIONS,Labels,Project,atomic_write,read_json,save_json,unique_id
from .qt_tasks import TaskManager
from .review import ReviewStore


def button(text,callback):
    b=QPushButton(text);b.clicked.connect(callback);return b


def weight(combo):
    return combo.currentData() if combo.currentData() and combo.currentIndex()>=0 and combo.currentText()==combo.itemText(combo.currentIndex()) else combo.currentText()


def field(value='',placeholder=''):
    w=QLineEdit(str(value));w.setPlaceholderText(placeholder);return w


def number(value,low,high,decimals=0):
    w=QDoubleSpinBox() if decimals else QSpinBox()
    w.setRange(low,high)
    if decimals:w.setDecimals(decimals);w.setSingleStep(.05)
    w.setValue(value);return w


def row(*widgets):
    w=QWidget();layout=QHBoxLayout(w);layout.setContentsMargins(0,0,0,0)
    for item in widgets:
        if isinstance(item,QPushButton):item.setSizePolicy(QSizePolicy.Maximum,QSizePolicy.Preferred)
        layout.addWidget(item)
    layout.addStretch(1)
    return w


def json_dialog(parent,title,value):
    dialog=QDialog(parent);dialog.setWindowTitle(title);dialog.resize(680,650)
    layout=QVBoxLayout(dialog);edit=QPlainTextEdit(json.dumps(value,ensure_ascii=False,indent=2));layout.addWidget(edit)
    buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);layout.addWidget(buttons)
    buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
    if dialog.exec_()==QDialog.Accepted:return json.loads(edit.toPlainText())
    return None


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config=settings();self.project=None;self.current_image=None;self.images=[];self.image_index=0;self.sam_request=None
        self.label_store=None;self.tracking_window=None;self.pending_model_info=None;self.clipboard_files=[];self.cut_files=False;self.review_batch=None;self.annotation_dirty=False
        configured_logo=self.config.get('logo','')
        self.setWindowIcon(QIcon(configured_logo or str(bundled_logo())))
        self.task=TaskManager(self);self.task.message.connect(self.on_event);self.task.log.connect(self.append_log);self.task.finished.connect(self.task_finished)
        self.setWindowTitle(self.config.get('brand','YoloTrain Studio'));self.resize(1200,780);self.setAcceptDrops(True)
        central=QWidget();self.setCentralWidget(central);layout=QVBoxLayout(central);layout.setContentsMargins(5,5,5,5);layout.setSpacing(4)
        self.project_title=QLabel('打开或创建项目，开始本地工作流');self.project_title.setObjectName('projectTitle')
        self.project_title.setMinimumWidth(0);self.project_title.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        header=QHBoxLayout();header.addWidget(button('导航',lambda:self.nav.setVisible(not self.nav.isVisible())));header.addWidget(self.project_title,1);header.addWidget(button('新建项目',self.new_project));header.addWidget(button('打开项目',self.open_project));layout.addLayout(header)
        body=QHBoxLayout();layout.addLayout(body,1)
        self.nav=QListWidget();self.nav.addItems(['概览','数据管理','图像标注','视频追踪标注','训练与数据集','测试与导出','设置']);self.nav.setFixedWidth(155);body.addWidget(self.nav)
        self.pages=QStackedWidget();body.addWidget(self.pages,1)
        self.build_home();self.build_data();self.build_annotation();self.build_tracking();self.build_train();self.build_test();self.build_settings()
        self.nav.setCurrentRow(0)
        self.progress=QProgressBar();self.progress.setRange(0,1000)
        self.status=QLabel('就绪');self.status.setMaximumWidth(180);self.progress.setMinimumWidth(20);self.stop_task_button=button('停止任务',self.task.cancel);self.output_button=button('打开任务输出',self.open_output);self.task_bar=row(self.status,self.progress,self.stop_task_button,self.output_button,button('任务 / 日志',lambda:self.log.setVisible(not self.log.isVisible())));layout.addWidget(self.task_bar);self.stop_task_button.hide();self.output_button.hide()
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(1500);self.log.setMaximumHeight(85);layout.addWidget(self.log);self.log.hide()
        from .workspace import install
        install(self)
        recent=self.config.get('recent',[])
        if recent and Path(recent[0]).exists():self.load_project(recent[0])

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'nav'):
            self.nav.hide()
            self.tracking_window.events.setVisible(event.size().width()>=1000)

    def page(self,title):
        w=QWidget();v=QVBoxLayout(w);heading=QLabel(title);heading.setObjectName('heading');v.addWidget(heading);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(w);self.pages.addWidget(scroll);return v

    def guard(self):
        if not self.project:raise ValueError('请先打开或创建项目')
        if self.task.busy:raise ValueError('后台任务运行中，请先等待完成或停止')

    def append_log(self,text):self.log.appendPlainText(text.rstrip())

    def new_project(self):
        parent=QFileDialog.getExistingDirectory(self,'选择项目父文件夹')
        if not parent:return
        name,ok=QInputDialog.getText(self,'新建项目','项目名称')
        if ok and name:
            if Path(name).name!=name or any(c in name for c in '<>:"/\\|?*'):raise ValueError('项目名称无效')
            self.load_project(Path(parent)/name)

    def open_project(self):
        path=QFileDialog.getExistingDirectory(self,'打开项目')
        if path:self.load_project(path)

    def load_project(self,path):
        if self.task.busy:raise ValueError('任务运行中无法切换项目')
        self.save_annotation();self.current_image=None
        self.project=Project(path);self.label_store=self.project.labels
        self.tracking_window.sync_project(reset=True)
        self.project_title.setText(self.project.root.name);self.project_title.setToolTip(str(self.project.root));self.review_batch=None
        self.config['recent']=[str(self.project.root)]+[p for p in self.config.get('recent',[]) if p!=str(self.project.root)][:9]
        save_settings(self.config);self.refresh()
        train_config=read_json(self.project.config/'train.json',{})
        for key,widget in [('epochs',self.epochs),('batch',self.batch),('lr0',self.lr),('imgsz',self.imgsz)]:
            if key in train_config:widget.setValue(train_config[key])
        if 'device' in train_config:self.device.setCurrentText(train_config['device'])
        if 'model' in train_config:self.train_model.setCurrentText(train_config['model'])
        self.restore_position()
        for key,checked in train_config.get('augmentation',{}).items():
            if key in self.augmentation:self.augmentation[key].setChecked(checked)

    def refresh(self):
        if not self.project:return
        stats=self.project.stats();self.summary.setText(f"图片 {stats['total']}     已标注 {stats['annotated']}     已审负样本 {stats['empty']}     待处理 {stats['pending']}     无效标签 {stats['invalid']}")
        review=ReviewStore(self.project);records=review.records();pending=sum(review.status(p.name,records)=='pending' for p in self.project.image_paths());confirmed=sum(review.status(p.name,records)=='confirmed' for p in self.project.image_paths());self.summary.setText(f"共 {stats['total']} 张图片 · 已完成 {confirmed} · 待完成 {pending} · 历史图片 {stats['total']-confirmed-pending}")
        if hasattr(self,'library_summary'):self.library_summary.setText(self.summary.text())
        self.home_stats.setPlainText(json.dumps(stats['classes'],ensure_ascii=False,indent=2))
        self.recent.clear();self.recent.addItems(self.config.get('recent',[]))
        log=self.project.root/'activity.log';self.activities.setPlainText(log.read_text(encoding='utf-8')[-10000:] if log.exists() else '暂无活动')
        self.files.clear();self.files.addItems([p.name for p in self.project.image_paths()])
        current=self.library_group.currentData();self.library_group.blockSignals(True);self.library_group.clear()
        self.library_group.addItem('全部素材','all');self.library_group.addItem('待完成','pending')
        for batch in sorted({e.get('batch') or e.get('source_task') for e in records.values() if e.get('batch') or e.get('source_task')}):
            self.library_group.addItem(read_json(self.project.config/'groups.json',{}).get(batch,batch),batch)
        index=self.library_group.findData(current);self.library_group.setCurrentIndex(max(0,index));self.library_group.blockSignals(False);self.filter_library()
        self.tracking_window.sync_project()
        self.classes.clear();self.classes.addItems(self.label_store.classes)
        self.versions.clear();store=DatasetStore(self.project);self.versions.addItems(store.list_versions())
        self.eval_version.clear();self.eval_version.addItems(store.list_versions())
        if store.active():self.versions.setCurrentText(store.active());self.eval_version.setCurrentText(store.active())
        previous_train=weight(self.train_model);previous_test=weight(self.test_model)
        self.train_model.clear();self.test_model.clear()
        models=[str(p) for p in self.project.models.glob('*.pt')]+model_paths()
        for combo in (self.train_model,self.test_model):
            for path in models:combo.addItem(Path(path).name,path)
        if previous_train:
            index=self.train_model.findData(previous_train)
            if index>=0:self.train_model.setCurrentIndex(index)
            else:self.train_model.setCurrentText(previous_train)
        if previous_test:
            index=self.test_model.findData(previous_test)
            if index>=0:self.test_model.setCurrentIndex(index)
            else:self.test_model.setCurrentText(previous_test)
        selected_experiment=self.experiment_list.currentRow()
        self.experiments=[]
        path=self.project.models/'experiments.jsonl'
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                try:self.experiments.append(json.loads(line))
                except ValueError:pass
        self.experiment_list.clear();self.experiment_list.addItems([f"{e.get('experiment_id','')}  {e.get('status','')}  {e.get('metrics',{})}" for e in self.experiments]);self.experiment_list.setCurrentRow(min(selected_experiment,len(self.experiments)-1))

    def build_home(self):
        v=self.page('项目概览');self.summary=QLabel('尚未打开项目');v.addWidget(self.summary)
        self.home_stats=QPlainTextEdit();self.home_stats.setReadOnly(True);v.addWidget(self.home_stats)
        v.addWidget(QLabel('最近项目'));self.recent=QListWidget();self.recent.itemDoubleClicked.connect(lambda i:self.load_project(i.text()));v.addWidget(self.recent)
        v.addWidget(QLabel('活动记录'));self.activities=QPlainTextEdit();self.activities.setReadOnly(True);v.addWidget(self.activities)

    def build_data(self):
        v=self.page('数据管理 · 图片与标签成对操作')
        self.library_summary=QLabel('导入图片即可标注；视频可直接抽帧或用 SAM2。');v.addWidget(self.library_summary)
        self.library_group=QComboBox();self.library_group.currentIndexChanged.connect(self.filter_library)
        v.addWidget(row(self.library_group,button('重命名分组',self.rename_group),button('继续上次标注',self.restore_position),button('标注当前集合',self.annotate_library)))
        split=QSplitter();v.addWidget(split,1);self.files=QListWidget();self.files.setSelectionMode(QAbstractItemView.ExtendedSelection);split.addWidget(self.files)
        self.data_preview=QLabel('双击图片进入标注');self.data_preview.setAlignment(Qt.AlignCenter);split.addWidget(self.data_preview)
        self.files.currentTextChanged.connect(self.preview_data);self.files.itemDoubleClicked.connect(self.annotate_selected)

    def filter_library(self,*args):
        if not self.project:return
        group=self.library_group.currentData();review=ReviewStore(self.project);records=review.records()
        for i in range(self.files.count()):
            item=self.files.item(i);entry=records.get(item.text(),{})
            item.setHidden(group=='pending' and review.status(item.text(),records)!='pending' or group not in ('all','pending',None) and group not in (entry.get('batch'),entry.get('source_task')))

    def rename_group(self):
        if not self.project:return
        group=self.library_group.currentData()
        if group in ('all','pending',None):raise ValueError('请先选择一个导入分组')
        title,ok=QInputDialog.getText(self,'分组名称','显示名称',text=self.library_group.currentText())
        if ok and title.strip():
            path=self.project.config/'groups.json';names=read_json(path,{});names[group]=title.strip();save_json(path,names);self.refresh()

    def annotate_library(self):
        names=[self.files.item(i).text() for i in range(self.files.count()) if not self.files.item(i).isHidden()]
        if names:self.open_review_batch({'names':names})

    def import_files(self):
        self.guard();paths,_=QFileDialog.getOpenFileNames(self,'导入图片','','Images (*.jpg *.jpeg *.png *.bmp *.webp *.gif)')
        if paths:self.import_materials(paths)

    def import_materials(self,paths):
        from .imports import import_images
        self.save_annotation()
        names=import_images(self.project,list(paths))
        self.refresh()
        if names:self.open_review_batch({'names':names})

    def remember_position(self):
        if not self.project or not self.current_image or self.current_image.parent!=self.project.images:return
        save_json(self.project.config/'workspace.json',dict(schema=1,image=self.current_image.name,
            filter=self.review_filter.currentIndex(),batch=self.review_batch,class_name=self.classes.currentText()))

    def restore_position(self):
        if not self.project:return
        state=read_json(self.project.config/'workspace.json',{})
        self.review_batch=state.get('batch');index=state.get('filter',2)
        self.review_filter.blockSignals(True);self.review_filter.setCurrentIndex(index);self.review_filter.blockSignals(False)
        self.filter_review(index)
        names=[p.name for p in self.images]
        if state.get('image') in names:self.image_index=names.index(state['image']);self.show_image()
        elif self.images:
            self.image_index=next((i for i,p in enumerate(self.images) if ReviewStore(self.project).status(p.name)!='confirmed'),0);self.show_image()
        if state.get('class_name'):self.classes.setCurrentText(state['class_name'])
        self.route(2 if self.images and state else 1)

    def merge_folder(self):
        self.guard();path=QFileDialog.getExistingDirectory(self,'递归合并图片文件夹（同名跳过）')
        if path:self.import_materials(Path(path).rglob('*'))

    def rename_images(self):
        self.guard();prefix,ok=QInputDialog.getText(self,'批量重命名','前缀',text='image_')
        if not ok:return
        start,ok=QInputDialog.getInt(self,'批量重命名','起始编号',1,0,999999)
        if not ok:return
        preview=self.project.rename_preview(prefix,start)
        text='\n'.join(f'{a.name} → {b.name}' for a,b in preview[:15])
        if QMessageBox.question(self,'重命名预览',text+'\n标签将同步重命名。')==QMessageBox.Yes:
            self.save_annotation();self.current_image=None;self.project.batch_rename(prefix,start);self.refresh()

    def copy_files(self,cut):
        self.guard();self.clipboard_files=[self.project.images/i.text() for i in self.files.selectedItems()];self.cut_files=cut

    def paste_files(self):
        self.guard()
        for source in self.clipboard_files:
            if source.parent==self.project.images:continue
            source_labels=Labels(source.parent.parent/'Main_labels')
            boxes=source_labels.load(source.stem)
            source_classes=source_labels.classes
            if any(b.cls>=len(source_classes) for b in boxes):raise ValueError('来源项目包含未知类别，无法复制标签')
            names=list(self.project.labels.classes)
            for box in boxes:
                if source_classes[box.cls] not in names:names.append(source_classes[box.cls])
            added=self.project.import_images([source])
            if added:
                self.project.labels.set_classes(names)
                if (source_labels.folder/(source.stem+'.txt')).exists():
                    remapped=[Box(names.index(source_classes[b.cls]),b.x1,b.y1,b.x2,b.y2,b.origin,b.score) for b in boxes]
                    self.project.labels.save(source.stem,remapped)
                if self.cut_files:
                    Project(source.parent.parent).trash_image(source)
        self.refresh()

    def delete_files(self):
        self.guard();items=self.files.selectedItems()
        if items and QMessageBox.question(self,'移除图片',f'将 {len(items)} 张图片及标签移至项目 .trash？')==QMessageBox.Yes:
            for i in items:self.project.trash_image(self.project.images/i.text())
            self.current_image=None;self.refresh()

    def preview_data(self,name):
        if self.project and name:
            pix=QPixmap(str(self.project.images/name));self.data_preview.setPixmap(pix.scaled(600,500,Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def inspect_images(self):
        self.guard();size,ok=QInputDialog.getInt(self,'检查图片','最短边尺寸（0 仅检查损坏）',0,0,10000)
        if ok:self.start_task('inspect_images',min_size=size)

    def extract_video(self):
        self.guard();path,_=QFileDialog.getOpenFileName(self,'选择视频','','Videos (*.mp4 *.avi *.mov *.mkv)')
        if not path:return
        interval,ok=QInputDialog.getItem(self,'视频抽帧','每隔多少帧抽一帧？',['5','10','15','20','30'],'10',False)
        if ok:self.start_task('extract',video=path,frame_step=int(interval))

    def build_annotation(self):
        v=self.page('专注标注')
        self.classes=QComboBox();self.classes.currentIndexChanged.connect(lambda i:setattr(self.canvas,'class_id',max(0,i)))
        self.annotation_mode=QComboBox();self.annotation_mode.addItems(['选择 / 移动','绘制矩形','SAM 点选','SAM 框选']);self.annotation_mode.currentIndexChanged.connect(lambda i:setattr(self.canvas,'mode',['select','draw','sam_point','sam_box'][i]))
        v.addWidget(row(self.classes,button('编辑类别',self.edit_classes),self.annotation_mode,button('AI 预标注',self.ai_dialog)))
        self.canvas=AnnotationCanvas();v.addWidget(self.canvas,1);self.canvas.changed.connect(self.annotation_changed);self.canvas.prompt.connect(self.sam_prompt);self.canvas.navigate.connect(self.navigate_image)
        self.annotation_status=QLabel('A/D 切图 · W 画框 · Del 删除 · R 适应 · Ctrl+C/V 复制粘贴 · 空格拖动')
        self.previous_image_button=button('上一张 A',lambda:self.navigate_image(-1));self.next_image_button=button('下一张 D',lambda:self.navigate_image(1))
        for control in (self.previous_image_button,self.next_image_button):control.setAutoRepeat(True);control.setAutoRepeatDelay(300);control.setAutoRepeatInterval(100)
        v.addWidget(row(self.previous_image_button,self.annotation_status,self.next_image_button,button('适应 R',self.canvas.fit)))
        self.review_filter=QComboBox();self.review_filter.addItems(['当前图片集合','项目待完成','项目全部图片']);self.review_filter.currentIndexChanged.connect(self.filter_review)
        self.completion_button=button('完成并下一张 F',self.confirm_next)
        self.completion_shortcut=QShortcut('F',self.canvas);self.completion_shortcut.setContext(Qt.WidgetShortcut);self.completion_shortcut.setAutoRepeat(False)
        self.completion_shortcut.activated.connect(lambda:self.confirm_next() if not self.canvas.read_only else None)
        self.completion_button.setToolTip('F：完成当前图片并进入下一张；仅在标注画布获得焦点时生效，长按不会连续确认')
        from .workspace import menu_button
        v.addWidget(row(self.review_filter,menu_button('编辑 ▾',[('删除框',self.canvas.delete_selected),('撤销',lambda:self.canvas.history_step(-1)),('重做',lambda:self.canvas.history_step(1)),('清除 AI 框',self.clear_ai),('全部接受当前集合',self.accept_all)]),self.completion_button))
        self.canvas.mode_changed.connect(lambda mode:self.annotation_mode.setCurrentIndex(['select','draw','sam_point','sam_box'].index(mode)))
        self.sam_model=QComboBox();self.sam_model.setEditable(True);self.sam_model.addItems(model_paths(True))
        self.annotation_advanced=QGroupBox('高级设置 · SAM 模型');self.annotation_advanced.setCheckable(True);self.annotation_advanced.setChecked(False);av=QVBoxLayout(self.annotation_advanced);content=row(self.sam_model,button('浏览 SAM',lambda:self.browse_model(self.sam_model)));av.addWidget(content);content.hide();self.annotation_advanced.toggled.connect(content.setVisible);v.addWidget(self.annotation_advanced)

    def annotate_selected(self,item):
        self.annotate_library();self.image_index=next(i for i,p in enumerate(self.images) if p.name==item.text());self.show_image();self.nav.setCurrentRow(2)

    def open_annotation_folder(self):
        self.guard();folder=QFileDialog.getExistingDirectory(self,'图片文件夹')
        if not folder:return
        selected=Path(folder)
        if (selected/'task.json').is_file() and (selected/'video_images').is_dir():
            self.import_video_run(str(selected));return
        if selected.name=='video_images' and (selected.parent/'task.json').is_file():
            self.import_video_run(str(selected.parent));return
        labels=QFileDialog.getExistingDirectory(self,'标签文件夹（取消则使用同级 _labels）')
        self.save_annotation();self.review_batch=None;self.label_store=Labels(labels or folder+'_labels');self.current_image=None
        self.images=sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS);self.image_index=0;self.classes.clear();self.classes.addItems(self.label_store.classes)
        self.show_image()

    def show_image(self):
        self.sam_request=None
        if not self.images:
            self.current_image=None;self.canvas.scene().clear();self.canvas.image_path=None;self.annotation_status.setText('没有符合筛选条件的图片');return
        self.current_image=None
        path=self.images[self.image_index];boxes=self.label_store.load(path.stem);names=self.label_store.classes
        max_id=max((b.cls for b in boxes),default=-1)
        if max_id>=len(names):
            raise ValueError(f'{path.name} 标签类别超出 classes.txt 范围，请检查类别表或重新导入')
        self.canvas.load(path,boxes,names);self.current_image=path
        self.annotation_dirty=False
        self.completion_button.setText('完成并下一张 F' if boxes else '确认无目标并下一张 F')
        self.remember_position()
        status=ReviewStore(self.project).status(path.name) if self.project and path.parent==self.project.images else 'external'
        self.annotation_status.setText(f'{self.image_index+1}/{len(self.images)}  '+{'pending':'待完成','confirmed':'已完成','legacy':'原有图片','external':'外部图片'}[status]);self.annotation_status.setToolTip(str(path))

    def annotation_changed(self):
        self.annotation_dirty=True;self.save_annotation();self.completion_button.setText('完成并下一张 F' if self.canvas.boxes() else '确认无目标并下一张 F')
        if self.project and self.current_image and self.current_image.parent==self.project.images:
            review=ReviewStore(self.project);records=review.records()
            if self.current_image.name in records:records[self.current_image.name]['status']='pending';review.write(records)

    def save_annotation(self):
        if self.current_image and self.label_store and not (self.task.busy and self.task.last_task['kind']=='prelabel'):
            boxes=self.canvas.boxes()
            if self.annotation_dirty or boxes!=self.label_store.load(self.current_image.stem):
                self.label_store.save(self.current_image.stem,boxes)
            self.annotation_dirty=False

    def import_video_run(self,run):
        self.guard();self.save_annotation()
        self.start_task('import_video',source_run=str(run))

    def open_review_batch(self,result):
        self.save_annotation();self.current_image=None;self.label_store=self.project.labels
        self.review_batch=list(result['names']);self.images=[self.project.images/n for n in self.review_batch]
        self.review_filter.blockSignals(True);self.review_filter.setCurrentIndex(0);self.review_filter.blockSignals(False)
        self.classes.clear();self.classes.addItems(self.label_store.classes);self.image_index=0;self.show_image();self.nav.setCurrentRow(2)

    def filter_review(self,index):
        if not self.project:return
        self.save_annotation();self.current_image=None;self.label_store=self.project.labels
        review=ReviewStore(self.project);records=review.records();paths=self.project.image_paths()
        if index==1:paths=[p for p in paths if review.status(p.name,records)=='pending']
        elif index==0 and self.review_batch is not None:paths=[self.project.images/n for n in self.review_batch if (self.project.images/n).exists()]
        self.images=paths;self.image_index=0;self.classes.clear();self.classes.addItems(self.label_store.classes);self.show_image()

    def confirm_next(self):
        if not self.current_image:return
        if self.current_image.parent!=self.project.images:raise ValueError('请先导入项目再复审')
        self.save_annotation();self.label_store.save(self.current_image.stem,self.canvas.boxes());ReviewStore(self.project).confirm([self.current_image.name])
        records=ReviewStore(self.project).records();pending=[p for p in self.images if ReviewStore(self.project).status(p.name,records)!='confirmed']
        if pending:
            ordered=self.images[self.image_index+1:]+self.images[:self.image_index+1]
            target=next(p for p in ordered if p in pending);self.image_index=self.images.index(target);self.show_image()
        else:
            self.refresh();self.route(1)
            dialog=QMessageBox(self);dialog.setWindowTitle('本批标注完成');dialog.setText(f'当前集合 {len(self.images)} 张图片已全部完成。');dialog.addButton('回素材库',QMessageBox.AcceptRole);train_button=dialog.addButton('去训练',QMessageBox.ActionRole);dialog.exec_()
            if dialog.clickedButton()==train_button:self.route(4)

    def accept_all(self):
        self.guard()
        if not self.images:return
        if any(p.parent!=self.project.images for p in self.images):raise ValueError('请先导入项目再复审')
        if QMessageBox.question(self,'全部接受',f'接受当前集合的 {len(self.images)} 张图片及标签？空标签将作为负样本。')!=QMessageBox.Yes:return
        self.save_annotation();ReviewStore(self.project).confirm([p.name for p in self.images])
        if self.review_filter.currentIndex()==1:self.filter_review(1)
        else:self.show_image()

    def navigate_image(self,step):
        if not self.images:return
        self.save_annotation();self.image_index=max(0,min(len(self.images)-1,self.image_index+step));self.show_image()

    def edit_classes(self):
        self.guard();old=self.label_store.classes
        text,ok=QInputDialog.getMultiLineText(self,'类别管理','每行一个类别；改名请保持行顺序；删除类别会移除其框并备份', '\n'.join(old))
        if not ok:return
        names=[n.strip() for n in text.splitlines() if n.strip()]
        mapping={i:names.index(n) for i,n in enumerate(old) if n in names}
        unmatched_old=[i for i,n in enumerate(old) if n not in names];unmatched_new=[i for i,n in enumerate(names) if n not in old]
        for a,b in zip(unmatched_old,unmatched_new):mapping[a]=b
        self.save_annotation();self.label_store.reorder(names,mapping);self.classes.clear();self.classes.addItems(names)
        if self.current_image:self.show_image()
        self.tracking_window.sync_project()

    def clear_ai(self):
        if self.current_image:
            boxes=[b for b in self.canvas.boxes() if b.origin!='AI'];self.label_store.save(self.current_image.stem,boxes);self.show_image()

    def sam_prompt(self,prompt):
        self.guard()
        if not self.current_image or not self.label_store.classes:raise ValueError('请先选择图片并创建类别')
        self.sam_request=uuid.uuid4().hex
        self.sam_class=self.classes.currentIndex()
        self.start_task('sam',model=weight(self.sam_model),image=str(self.current_image),class_id=self.classes.currentIndex(),
                        imgsz=self.config.get('sam_imgsz',1024),device=self.tracking_window.device.currentText(),request=self.sam_request,**prompt)

    def ai_dialog(self):
        self.guard()
        if not self.images or not self.label_store.classes:raise ValueError('请先打开图片并设置类别')
        self.save_annotation();model,_=QFileDialog.getOpenFileName(self,'选择 YOLO 权重',str(self.project.models),'Weights (*.pt)')
        if model:self.pending_model_info=model;self.start_task('model_info',model=model)

    def ai_mapping(self,names):
        dialog=QDialog(self);dialog.setWindowTitle('AI 预标注 · 类别映射');layout=QVBoxLayout(dialog);form=QFormLayout();layout.addLayout(form)
        combos={};classes=self.label_store.classes
        for key,name in names.items():
            combo=QComboBox();combo.addItems(['跳过']+classes);combo.setCurrentIndex(classes.index(name)+1 if name in classes else 0);form.addRow(f'{key}: {name}',combo);combos[key]=combo
        scope=QComboBox();scope.addItems(['当前图片','未标注图片','全部图片']);form.addRow('范围',scope)
        replace=QCheckBox('覆盖旧标注');form.addRow(replace)
        conf=number(.5,.01,1,2);iou=number(.45,.01,1,2);form.addRow('置信度',conf);form.addRow('IoU',iou)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);layout.addWidget(buttons);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec_()!=QDialog.Accepted:return
        mapping={k:c.currentIndex()-1 for k,c in combos.items() if c.currentIndex()>0}
        if not mapping:raise ValueError('至少映射一个类别')
        paths=[self.current_image] if scope.currentIndex()==0 else self.images
        if scope.currentIndex()==1:paths=[p for p in paths if not (self.label_store.folder/(p.stem+'.txt')).exists()]
        self.start_task('prelabel',model=self.pending_model_info,labels=str(self.label_store.folder),images=list(map(str,paths)),mapping=mapping,
                        replace=replace.isChecked(),conf=conf.value(),iou=iou.value(),device=self.tracking_window.device.currentText())

    def open_tracking(self):
        self.guard();self.nav.setCurrentRow(3)

    def build_tracking(self):
        from .tracking_ui import TrackingWindow
        self.tracking_window=TrackingWindow(self);self.pages.addWidget(self.tracking_window)

    def build_train(self):
        v=self.page('训练')
        self.versions=QComboBox();v.addWidget(row(QLabel('数据集版本'),self.versions,button('重新划分',lambda:self.create_dataset(False)),button('增量更新',lambda:self.create_dataset(True)),button('激活版本',self.activate_version)))
        form=QFormLayout();v.addLayout(form)
        self.train_model=QComboBox();self.train_model.setEditable(True);form.addRow('初始权重',row(self.train_model,button('浏览',lambda:self.browse_model(self.train_model))))
        self.epochs=number(50,1,100000);self.batch=number(16,1,1024);self.lr=number(.001,.000001,1,6);self.imgsz=number(640,32,4096)
        self.device=QComboBox();self.device.setEditable(True);self.device.addItems(['0','cpu','0,1'])
        form.addRow('训练轮次 / 设备',row(self.epochs,self.device))
        advanced=QGroupBox('高级设置 · Batch / 学习率 / 尺寸 / 数据增强');advanced.setCheckable(True);advanced.setChecked(False);v.addWidget(advanced);av=QVBoxLayout(advanced);content=QWidget();af=QFormLayout(content);av.addWidget(content);af.addRow('Batch / 学习率 / 输入尺寸',row(self.batch,self.lr,self.imgsz));content.hide();advanced.toggled.connect(content.setVisible)
        self.augmentation={};augrow=QWidget();auglayout=QGridLayout(augrow)
        for title,key,default in [('水平翻转','fliplr',True),('缩放','scale',True),('马赛克','mosaic',True),('色彩','hsv',True),('垂直翻转','flipud',False),('旋转','degrees',False),('混合','mixup',False),('平移','translate',True)]:
            c=QCheckBox(title);c.setChecked(default);self.augmentation[key]=c;index=len(self.augmentation)-1;auglayout.addWidget(c,index//4,index%4)
        af.addRow('数据增强',augrow);af.addRow(button('更多训练参数',self.advanced_dialog));af.addRow(button('恢复默认参数',self.reset_train_defaults))
        self.pinned_train=row(QLabel('Batch'),number(16,1,1024),QLabel('学习率'),number(.001,.000001,1,6),QLabel('尺寸'),number(640,32,4096))
        for original,copy in zip((self.batch,self.lr,self.imgsz),self.pinned_train.findChildren((QSpinBox,QDoubleSpinBox))):
            copy.valueChanged.connect(original.setValue);original.valueChanged.connect(copy.setValue)
        form.addRow(self.pinned_train);self.pinned_train.setVisible(self.config.get('pin_train',False))
        pin=QCheckBox('将 Batch / 学习率 / 尺寸固定到常用区');pin.setChecked(self.config.get('pin_train',False));af.addRow(pin)
        def pin_changed(checked):
            self.pinned_train.setVisible(checked);self.config['pin_train']=checked;save_settings(self.config)
        pin.toggled.connect(pin_changed)
        af.addRow(row(button('保存本项目预设',self.save_train_preset),button('载入预设',self.load_train_preset)))
        v.addWidget(row(button('开始训练',self.train),button('查看训练曲线',self.show_curves),button('对比选中实验',self.compare_experiments)))
        self.curves=QLabel('训练完成或运行中可查看 results.png');self.curves.setAlignment(Qt.AlignCenter);v.addWidget(self.curves)
        self.experiment_list=QListWidget();self.experiment_list.setSelectionMode(QAbstractItemView.ExtendedSelection);self.experiment_list.currentRowChanged.connect(lambda _:self.show_curves());v.addWidget(self.experiment_list,1)

    def reset_train_defaults(self):
        self.batch.setValue(16);self.lr.setValue(.001);self.imgsz.setValue(640)
        for key,c in self.augmentation.items():c.setChecked(key in ('fliplr','scale','mosaic','hsv','translate'))
        if self.project:save_json(self.project.models/'advanced_train_params.json',dict(schema_version=2,params=ADVANCED))

    def save_train_preset(self):
        self.guard();save_json(self.project.config/'train_preset.json',dict(batch=self.batch.value(),lr=self.lr.value(),imgsz=self.imgsz.value(),epochs=self.epochs.value(),augmentation={k:c.isChecked() for k,c in self.augmentation.items()},advanced=read_json(self.project.models/'advanced_train_params.json',dict(schema_version=2,params=ADVANCED))))
        self.status.setText('已保存项目预设')

    def load_train_preset(self):
        self.guard();preset=read_json(self.project.config/'train_preset.json',{})
        if not preset:raise ValueError('本项目尚无预设，请先保存')
        for key,control in [('batch',self.batch),('lr',self.lr),('imgsz',self.imgsz),('epochs',self.epochs)]:control.setValue(preset[key])
        for key,value in preset['augmentation'].items():self.augmentation[key].setChecked(value)
        save_json(self.project.models/'advanced_train_params.json',preset['advanced'])

    def create_dataset(self,incremental):
        self.guard();self.save_annotation()
        review=ReviewStore(self.project);records=review.records();excluded=sum(review.status(p.name,records)=='pending' for p in self.project.image_paths())
        self.append_log(f'本次新建数据集将排除 {excluded} 张待复审图片')
        self.status.setText(f'待复审排除：{excluded} 张')
        dialog=QDialog(self);dialog.setWindowTitle('创建训练数据版本');form=QFormLayout(dialog);form.addRow(QLabel(f'排除 {excluded} 张待完成图片。已完成空标签将作为负样本。'));ratio=number(70,1,98);validation=number(20,1,98);seed=number(42,0,2147483647);form.addRow('训练集百分比',ratio);form.addRow('验证集百分比',validation);form.addRow('随机种子',seed);buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);form.addRow(buttons);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        values=None
        if dialog.exec_()==QDialog.Accepted:
            if ratio.value()+validation.value()>=100:raise ValueError('训练与验证比例总和必须小于 100%，剩余部分为测试集')
            values=dict(ratios=[ratio.value()/100,validation.value()/100,(100-ratio.value()-validation.value())/100],seed=seed.value())
        if values:self.start_task('dataset',incremental=incremental,**values)

    def activate_version(self):
        self.guard();DatasetStore(self.project).activate(self.versions.currentText());self.refresh()

    def advanced_dialog(self):
        self.guard();path=self.project.models/'advanced_train_params.json';current=read_json(path,{'schema_version':2,'params':ADVANCED})
        params=dict(ADVANCED,**current.get('params',{}));dialog=QDialog(self);dialog.setWindowTitle('高级训练参数');dialog.resize(650,740)
        layout=QVBoxLayout(dialog);scroll=QScrollArea();scroll.setWidgetResizable(True);content=QWidget();groups=QVBoxLayout(content);scroll.setWidget(content);layout.addWidget(scroll)
        editors={};sections=[('优化器',['optimizer','momentum','weight_decay','warmup_epochs','warmup_momentum','lrf']),('损失',['box','cls','dfl']),('资源与训练',['freeze','max_det','workers','patience','save_period','amp','rect','seed','cache','fraction']),('增强',['perspective','shear','close_mosaic'])]
        known=set()
        for title,keys in sections+[('其他参数',[k for k in params if k not in set().union(*(set(keys) for _,keys in sections))])]:
            box=QGroupBox(title);form=QFormLayout(box);groups.addWidget(box)
            for key in keys:
                editor=field(json.dumps(params[key],ensure_ascii=False));form.addRow(key,editor);editors[key]=editor
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);layout.addWidget(buttons);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec_()==QDialog.Accepted:
            values={k:json.loads(w.text()) for k,w in editors.items()}
            save_json(path,dict(schema_version=2,params=values))

    def train(self):
        self.guard();store=DatasetStore(self.project);version=self.versions.currentText();data=store.yaml_path(version)
        if self.imgsz.value()%32:raise ValueError('输入尺寸必须是 32 的倍数')
        params=dict(ADVANCED);params.update(read_json(self.project.models/'advanced_train_params.json',{}).get('params',{}))
        params.update(epochs=self.epochs.value(),batch=self.batch.value(),lr0=self.lr.value(),imgsz=self.imgsz.value(),device=self.device.currentText())
        values=dict(AUGMENTS,flipud=.01,degrees=10,mixup=.15)
        for key,check in self.augmentation.items():
            keys=['hsv_h','hsv_s','hsv_v'] if key=='hsv' else [key]
            for k in keys:params[k]=values[k] if check.isChecked() else 0.
        save_json(self.project.config/'train.json',dict(epochs=self.epochs.value(),batch=self.batch.value(),lr0=self.lr.value(),imgsz=self.imgsz.value(),device=self.device.currentText(),model=weight(self.train_model),augmentation={k:c.isChecked() for k,c in self.augmentation.items()}))
        self.start_task('train',model=weight(self.train_model),params=params,dataset=str(data),dataset_version=version)

    def compare_experiments(self):
        selected=[self.experiments[self.experiment_list.row(i)] for i in self.experiment_list.selectedItems()]
        if len(selected)<2:raise ValueError('请选择至少两个实验')
        keys=set().union(*(e.get('params',{}) for e in selected));diff={k:[e.get('params',{}).get(k) for e in selected] for k in keys if len({str(e.get('params',{}).get(k)) for e in selected})>1}
        json_dialog(self,'实验对比',{'experiments':[{k:e.get(k) for k in ('experiment_id','metrics','duration','dataset_version')} for e in selected],'parameter_differences':diff})

    def show_curves(self):
        if not self.project:return
        selected=self.experiment_list.currentRow()
        candidates=[Path(self.experiments[selected]['output'])/'results.png'] if 0<=selected<len(self.experiments) else list(self.project.runs.rglob('results.png'))
        candidates=[p for p in candidates if p.exists()]
        if not candidates:self.curves.clear();self.curves.setText('所选实验没有训练曲线');return
        if candidates:self.curves.setPixmap(QPixmap(str(max(candidates,key=lambda p:p.stat().st_mtime))).scaled(1000,330,Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def build_test(self):
        v=self.page('模型');form=QFormLayout();v.addLayout(form)
        self.test_model=QComboBox();self.test_model.setEditable(True);form.addRow('模型',row(self.test_model,button('浏览',lambda:self.browse_model(self.test_model))))
        self.model_operation=QComboBox();self.model_operation.addItems(['推理测试','测试集评估','导出模型']);form.addRow('操作',self.model_operation)
        self.model_device=QComboBox();self.model_device.setEditable(True);self.model_device.addItems(['0','cpu']);form.addRow('推理 / 评估设备',self.model_device)
        self.test_source=field();self.source_row=row(self.test_source,button('文件',self.browse_test_file),button('文件夹',self.browse_test_dir));form.addRow('输入',self.source_row)
        self.test_mode=QComboBox();self.test_mode.addItems(['单图','批量图片','视频','测试集评估'])
        self.conf=number(.25,.001,1,3);self.iou=number(.45,.01,1,2);self.test_controls=row(self.test_mode,self.conf,self.iou,button('运行测试',self.test));form.addRow('推理',self.test_controls)
        self.eval_version=QComboBox();self.eval_controls=row(self.eval_version,button('评估 test 分组',self.test));form.addRow('评估数据版本',self.eval_controls)
        self.export_format=QComboBox();self.export_format.addItems(['ONNX','OpenVINO','TensorRT','TorchScript']);self.precision=QComboBox();self.precision.addItems(['FP32','FP16','INT8'])
        self.export_controls=row(self.export_format,self.precision,button('高级设置',self.export_settings),button('导出模型',self.export));form.addRow('导出',self.export_controls)
        def switch_operation(index):
            self.source_row.setVisible(index==0);self.test_controls.setVisible(index==0);self.eval_controls.setVisible(index==1);self.export_controls.setVisible(index==2);self.model_device.setVisible(index!=2)
            for field,visible in [(self.source_row,index==0),(self.test_controls,index==0),(self.eval_controls,index==1),(self.export_controls,index==2),(self.model_device,index!=2)]:form.labelForField(field).setVisible(visible)
        self.model_operation.currentIndexChanged.connect(switch_operation);switch_operation(0)
        self.result_image=QLabel();self.result_image.setAlignment(Qt.AlignCenter);v.addWidget(self.result_image,1)
        self.results=QPlainTextEdit();self.results.setReadOnly(True);self.results.setMaximumHeight(150);v.addWidget(button('结果详情',lambda:self.results.setVisible(not self.results.isVisible())));v.addWidget(self.results);self.results.hide()
        self.detection_table=QTableWidget();self.detection_table.setEditTriggers(QAbstractItemView.NoEditTriggers);v.addWidget(self.detection_table,1)

    def browse_test_file(self):
        path,_=QFileDialog.getOpenFileName(self,'选择测试输入')
        if path:self.test_source.setText(path)

    def browse_test_dir(self):
        path=QFileDialog.getExistingDirectory(self,'测试图片文件夹')
        if path:self.test_source.setText(path)

    def test(self):
        self.guard();kwargs=dict(model=weight(self.test_model),conf=self.conf.value(),iou=self.iou.value(),device=self.model_device.currentText())
        if self.model_operation.currentIndex()==1 or self.test_mode.currentIndex()==3:self.start_task('evaluate',dataset=str(DatasetStore(self.project).yaml_path(self.eval_version.currentText())),**kwargs)
        else:self.start_task('predict',source=self.test_source.text(),mode=['image','batch','video'][self.test_mode.currentIndex()],**kwargs)

    def export_settings(self):
        self.guard();path=self.project.models/'onnx_export_params.json';value=read_json(path,dict(imgsz=640,opset=18,dynamic=False,simplify=True,batch=1))
        result=json_dialog(self,'导出参数',value)
        if result:save_json(path,result)

    def export(self):
        self.guard();fmt=['onnx','openvino','engine','torchscript'][self.export_format.currentIndex()]
        params=read_json(self.project.models/'onnx_export_params.json',dict(imgsz=640,opset=18,dynamic=False,simplify=True,batch=1))
        if fmt!='onnx':params={k:v for k,v in params.items() if k in ('imgsz','batch','dynamic')}
        params['quantize']=[32,16,8][self.precision.currentIndex()]
        params['device']='0' if fmt=='engine' or params['quantize']==16 else 'cpu'
        if params['quantize']==8:params['data']=str(DatasetStore(self.project).yaml_path())
        self.start_task('export',model=weight(self.test_model),format=fmt,params=params)

    def build_settings(self):
        v=self.page('设置');form=QFormLayout();v.addLayout(form)
        self.brand=field(self.config.get('brand','YoloTrain Studio'));self.logo=field(self.config.get('logo',''));self.sam_size=number(self.config.get('sam_imgsz',1024),32,4096)
        form.addRow('应用名称',self.brand);form.addRow('LOGO 文件',row(self.logo,button('浏览',self.browse_logo)));form.addRow('SAM 输入尺寸',self.sam_size)
        v.addWidget(button('保存设置',self.persist_settings));v.addWidget(QLabel('YoloTrain Studio 1.0.0\n本地运行 · 独立实现 · 所有功能直接开放\n耗时任务在独立进程中运行，输出保留于项目 runs。'))
        v.addStretch()

    def browse_logo(self):
        path,_=QFileDialog.getOpenFileName(self,'选择 LOGO','','Images (*.png *.jpg *.ico)')
        if path:self.logo.setText(path)

    def persist_settings(self):
        if self.sam_size.value()%32:raise ValueError('SAM 输入尺寸必须是 32 的倍数')
        self.config.update(brand=self.brand.text(),logo=self.logo.text(),sam_imgsz=self.sam_size.value());save_settings(self.config);self.setWindowTitle(self.brand.text())
        from PyQt5.QtGui import QIcon
        if self.logo.text():self.setWindowIcon(QIcon(self.logo.text()))

    def browse_model(self,combo):
        path,_=QFileDialog.getOpenFileName(self,'选择模型','','Weights (*.pt)')
        if path:combo.addItem(Path(path).name,path);combo.setCurrentIndex(combo.count()-1)

    def start_task(self,kind,**kwargs):
        self.guard();run=kwargs.pop('run',None) or str(self.project.new_run(kind))
        task=dict(kind=kind,run=run,project=str(self.project.root),**kwargs)
        if 'model' in task and not Path(task['model']).is_file():raise ValueError('模型路径不存在')
        self.stop_task_button.show();self.output_button.hide();self.status.setText(f'运行：{kind}');self.progress.setValue(0);self.task.start(task)

    def on_event(self,event):
        kind=event['event']
        if kind=='progress':self.progress.setValue(round(event['value']*1000));self.status.setText(event.get('text',''))
        elif kind=='error':self.append_log(event['message']);QMessageBox.critical(self,'任务失败',event['message'])
        elif kind=='cancelled':self.status.setText('任务已停止')
        elif kind=='epoch':self.append_log(json.dumps(event,ensure_ascii=False));self.show_curves()
        elif kind.startswith('tracking_') and self.tracking_window:self.tracking_window.on_event(event)
        elif kind=='result':
            result=event['result'];self.last_result=result;task_kind=self.task.last_task['kind']
            if task_kind in ('predict','evaluate','export'):self.results.setPlainText(json.dumps(result,ensure_ascii=False,indent=2))
            records=result.get('detections',result.get('per_class',[])) if task_kind in ('predict','evaluate') else []
            headers=list(records[0]) if records else []
            self.detection_table.clear();self.detection_table.setColumnCount(len(headers));self.detection_table.setRowCount(len(records));self.detection_table.setHorizontalHeaderLabels(headers)
            for i,record in enumerate(records):
                for j,key in enumerate(headers):self.detection_table.setItem(i,j,QTableWidgetItem(str(record[key])))
            self.detection_table.resizeColumnsToContents()
            if task_kind=='sam' and self.current_image and result.get('request')==self.sam_request and result.get('image')==str(self.current_image) and self.classes.currentIndex()==self.sam_class:
                for box in result['boxes']:self.canvas.add_box(Box(**box))
                self.canvas.changed.emit()
            if task_kind=='predict' and result.get('outputs'):
                pix=QPixmap(result['outputs'][0]);self.result_image.setPixmap(pix.scaled(950,380,Qt.KeepAspectRatio,Qt.SmoothTransformation))
            if task_kind=='inspect_images' and result['bad']:
                if QMessageBox.question(self,'图片检查',f"发现 {len(result['bad'])} 张问题图片，移至 .trash？\n"+'\n'.join(x['path'] for x in result['bad'][:8]))==QMessageBox.Yes:
                    for item in result['bad']:self.project.trash_image(item['path'])

    def task_finished(self,ok):
        kind=self.task.last_task['kind']
        self.stop_task_button.hide();self.output_button.show()
        self.status.setText('任务完成' if ok else '任务失败 / 已停止')
        if ok:self.progress.setValue(1000)
        if self.project:self.refresh()
        if ok and kind=='model_info':QTimer.singleShot(0,lambda:self.ai_mapping(self.last_result['names']))
        if kind=='prelabel' and self.current_image:self.show_image()
        if kind in ('tracking','extract') and str(self.task.run)==self.tracking_window.run:self.tracking_window.finished(ok)
        if kind=='import_video' and ok:QTimer.singleShot(0,lambda:self.open_review_batch(self.last_result))
        if kind in ('extract','tracking') and ok:QTimer.singleShot(0,lambda:self.import_video_run(str(self.task.run)))

    def open_folder(self,path):QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def open_output(self):
        if self.task.run:self.open_folder(self.task.run)

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()

    def dropEvent(self,event):
        self.guard();paths=[]
        for url in event.mimeData().urls():
            p=Path(url.toLocalFile());paths.extend(p.rglob('*') if p.is_dir() else [p])
        videos=[p for p in paths if p.suffix.lower() in ('.mp4','.avi','.mov','.mkv')]
        if videos:self.open_tracking();self.tracking_window.load_video(videos[0])
        else:self.import_materials(paths)

    def closeEvent(self,event):
        self.save_annotation()
        if self.task.busy:
            answer=QMessageBox.question(self,'后台任务运行中','停止任务并等待安全退出？再次关闭可强制终止。')
            if answer==QMessageBox.Yes:
                if (self.task.run/'cancel').exists():self.task.kill()
                else:self.task.cancel()
            event.ignore();return
        event.accept()


def main():
    if '--worker' in sys.argv:
        from .worker import main as worker_main
        return worker_main(sys.argv[sys.argv.index('--worker')+1])
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling,True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps,True)
    app=QApplication(sys.argv);app.setApplicationName('YoloTrainStudio');app.setWindowIcon(QIcon(str(bundled_logo())))
    app.setStyleSheet('''QMainWindow,QDialog {background:#f3f6fb;} QWidget {font-family:"Microsoft YaHei UI";font-size:15px;color:#1f2937;} QPushButton {background:#ffffff;border:1px solid #cbd5e1;border-radius:6px;padding:5px 10px;min-height:22px;} QPushButton:hover {background:#dbeafe;border-color:#3b82f6;} QPushButton:checked {background:#dbeafe;color:#1d4ed8;border-color:#60a5fa;} QToolButton {background:white;border:1px solid #cbd5e1;border-radius:5px;padding:5px 10px;} QGroupBox {border:1px solid #dbe2eb;border-radius:5px;margin-top:10px;padding-top:10px;} QGroupBox::title {subcontrol-origin:margin;left:8px;} QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {background:white;border:1px solid #cbd5e1;border-radius:4px;padding:4px;min-height:22px;} QListWidget,QPlainTextEdit {background:white;border:1px solid #dbe2eb;border-radius:6px;} QListWidget::item {padding:8px;} QListWidget::item:selected {background:#dbeafe;color:#1e40af;} QLabel#heading {font-size:20px;font-weight:600;padding:4px 0;} QLabel#projectTitle {font-weight:600;} QProgressBar {border:1px solid #cbd5e1;border-radius:5px;text-align:center;min-height:20px;max-height:24px;} QProgressBar::chunk {background:#3b82f6;}''')
    def exception_hook(typ,value,tb):
        import traceback
        traceback.print_exception(typ,value,tb)
        QMessageBox.critical(None,'操作未完成',str(value))
    sys.excepthook=exception_hook
    window=Window()
    available=app.primaryScreen().availableGeometry();window.resize(min(1200,available.width()),min(780,available.height()));window.show()
    return app.exec_()


if __name__=='__main__':raise SystemExit(main())
