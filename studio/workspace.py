"""User-facing workspaces; legacy page routing remains an internal API."""
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QStackedWidget,QPushButton,
    QLabel,QMenu,QDialog,QToolButton,QComboBox,QFormLayout,QScrollArea)


def menu_button(text, actions):
    b=QToolButton();b.setText(text);b.setPopupMode(QToolButton.InstantPopup)
    menu=QMenu(b)
    for title,callback in actions:menu.addAction(title,callback)
    b.setMenu(menu);return b


def install(window):
    w=window
    # Detach existing views from the old seven-page navigation.
    views=[]
    for i in range(w.pages.count()):
        page=w.pages.widget(i)
        if hasattr(page,'takeWidget'):page=page.takeWidget()
        views.append(page)
    central=QWidget();outer=QVBoxLayout(central);outer.setContentsMargins(10,8,10,8);outer.setSpacing(6)
    top=QHBoxLayout();outer.addLayout(top)
    top.addWidget(menu_button('项目 ▾',[('新建项目',w.new_project),('打开项目',w.open_project),('最近项目',lambda:route(0)),('应用设置',lambda:route(6))]))
    top.addWidget(w.project_title,1)
    w.workspace_buttons=[]
    for title,index in [('数据与标注',1),('训练',4),('模型',5)]:
        b=QPushButton(title);b.setCheckable(True);b.clicked.connect(lambda checked=False,i=index:route(i));top.addWidget(b);w.workspace_buttons.append(b)
    w.workspace_stack=QStackedWidget();outer.addWidget(w.workspace_stack,1)
    data=QWidget();dv=QVBoxLayout(data);dv.setContentsMargins(0,0,0,0)
    tools=QHBoxLayout();dv.addLayout(tools)
    tools.addWidget(menu_button('导入素材 ▾',[('图片 / YOLO 标签',w.import_files),('图片文件夹',w.merge_folder),('视频：抽帧或 SAM2',w.open_tracking),('已有视频结果',w.tracking_window.browse_import)]))
    w.data_tabs=[]
    for title,index in [('素材库',1),('专注标注',2),('视频导入',3)]:
        b=QPushButton(title);b.setCheckable(True);b.clicked.connect(lambda checked=False,i=index:route(i));tools.addWidget(b);w.data_tabs.append(b)
    tools.addStretch()
    tools.addWidget(menu_button('更多 ▾',[('批量重命名',w.rename_images),('检查 / 尺寸清理',w.inspect_images),('复制',lambda:w.copy_files(False)),('剪切',lambda:w.copy_files(True)),('粘贴',w.paste_files),('移至回收目录',w.delete_files),('恢复追踪任务',w.tracking_window.restore),('打开项目目录',lambda:w.open_folder(w.project.root))]))
    w.data_stack=QStackedWidget();dv.addWidget(w.data_stack,1)
    w.data_stack.setMinimumSize(0,0)
    from PyQt5.QtWidgets import QSizePolicy
    w.data_stack.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Ignored)
    for page in views[1:4]:w.data_stack.addWidget(page)
    w.workspace_stack.addWidget(data)
    for index in (4,5):
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(views[index]);w.workspace_stack.addWidget(scroll)
    outer.addWidget(w.task_bar);outer.addWidget(w.log)
    w.setCentralWidget(central)
    # Keep the old stack/nav alive solely for source-compatible routing and tests.
    w.pages.setParent(central);w.pages.hide();w.nav.setParent(central);w.nav.hide()
    def route(index):
        if index in (0,6):
            dialog=QDialog(w);dialog.setWindowTitle('项目概览' if index==0 else '应用设置');dialog.resize(650,550)
            layout=QVBoxLayout(dialog);layout.addWidget(views[index]);dialog.exec_();views[index].setParent(w);views[index].hide();return
        group=0 if index in (1,2,3) else index-3
        w.workspace_stack.setCurrentIndex(group)
        for i,b in enumerate(w.workspace_buttons):b.setChecked(i==group)
        if group==0:
            w.data_stack.setCurrentIndex(index-1)
            w.annotation_advanced.setVisible(w.height()>=550)
            for label in views[2].findChildren(QLabel):
                if label.objectName()=='heading':label.setVisible(w.height()>=550)
            for i,b in enumerate(w.data_tabs):b.setChecked(i==index-1)
        if w.nav.currentRow()!=index:w.nav.setCurrentRow(index)
    w.route=route;w.nav.currentRowChanged.connect(route);route(1)

